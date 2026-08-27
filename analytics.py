from __future__ import annotations

import hmac
import os
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from functools import wraps

from flask import jsonify, request, send_from_directory
from sqlalchemy import func

import server_prod
from server_prod import FaceAnalysis, User

db = server_prod.db
app = server_prod.app

ADMIN_SECRET = os.environ.get("ADMIN_SECRET", "").strip()
ANALYTICS_DAILY_DAYS = int(os.environ.get("ANALYTICS_DAILY_DAYS", "30"))


class AnalyticsEvent(db.Model):
    __tablename__ = "analytics_event"
    id = db.Column(db.Integer, primary_key=True)
    # Kept intentionally small/generic (a handful of event types) rather than
    # a full analytics pipeline -- this exists to answer one business
    # question (how many people who touch the bot end up registering, then
    # actually running an analysis), not to be a general event log.
    event_type = db.Column(db.String(40), nullable=False, index=True)
    telegram_id = db.Column(db.BigInteger, nullable=True, index=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, index=True, default=lambda: datetime.now(timezone.utc))


# This table is brand new, so unlike the reminders/face-photo columns there is
# nothing to ALTER on an existing deployment -- db.create_all() only adds
# tables/columns that are missing, so calling it again here (server.py already
# called it once, before this module was even imported) is a safe way to make
# sure analytics_event exists regardless of import order.
with app.app_context():
    db.create_all()


def _log_event(event_type: str, telegram_id=None):
    # Best-effort: analytics must never be able to break the request it's
    # attached to (the Telegram webhook still has to answer Telegram either
    # way), so any failure here is swallowed after logging.
    try:
        db.session.add(AnalyticsEvent(event_type=event_type, telegram_id=telegram_id))
        db.session.commit()
    except Exception:
        db.session.rollback()
        app.logger.exception("PRIME analytics: failed to log event %s (non-fatal)", event_type)


# Wrap the existing Telegram webhook (defined in server.py) instead of editing
# it directly, the same way server_face_override.py wraps face_ai -- every
# inbound message currently triggers the bot's welcome reply, so counting
# distinct telegram_ids that have ever hit this webhook is the closest proxy
# available for "reached the bot" without adding a /start-specific parser.
_original_webhook = app.view_functions.get("telegram_webhook")


def _webhook_with_analytics():
    try:
        update = request.get_json(silent=True) or {}
        chat_id = ((update.get("message") or {}).get("chat") or {}).get("id")
        if chat_id:
            _log_event("bot_message", telegram_id=int(chat_id))
    except Exception:
        app.logger.exception("PRIME analytics: failed to record bot_message (non-fatal)")
    return _original_webhook()


if _original_webhook is not None:
    app.view_functions["telegram_webhook"] = _webhook_with_analytics


def admin_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not ADMIN_SECRET:
            return jsonify({"error": "ADMIN_SECRET is not configured"}), 503
        supplied = request.headers.get("X-Admin-Secret", "") or request.args.get("key", "")
        if not hmac.compare_digest(supplied, ADMIN_SECRET):
            return jsonify({"error": "forbidden"}), 403
        return fn(*args, **kwargs)
    return wrapped


@app.get("/admin")
def admin_page():
    return send_from_directory(server_prod.BASE, "admin.html")


def _aware_utc(ts):
    # Postgres (production) hands back tz-aware datetimes for a
    # DateTime(timezone=True) column, but SQLite (local dev/tests) silently
    # drops the offset on read -- comparing the two kinds directly raises
    # TypeError. Everything stored here is UTC regardless of backend, so a
    # naive value just needs the tzinfo re-attached, not converted.
    if ts is not None and ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts


def _daily_buckets(timestamps, days: int) -> "OrderedDict[str, int]":
    now = datetime.now(timezone.utc)
    start_day = (now - timedelta(days=days - 1)).date()
    buckets: "OrderedDict[str, int]" = OrderedDict()
    day = start_day
    while day <= now.date():
        buckets[day.isoformat()] = 0
        day += timedelta(days=1)
    for ts in timestamps:
        if not ts:
            continue
        key = ts.date().isoformat()
        if key in buckets:
            buckets[key] += 1
    return buckets


def _pct(part: int, whole: int):
    return round(part / whole * 100, 1) if whole else None


@app.get("/api/admin/funnel")
@admin_required
def admin_funnel():
    now = datetime.now(timezone.utc)
    cutoff_7 = now - timedelta(days=7)
    cutoff_30 = now - timedelta(days=30)

    # Stage 1: first time each Telegram id ever messaged the bot.
    contact_rows = (
        db.session.query(AnalyticsEvent.telegram_id, func.min(AnalyticsEvent.created_at))
        .filter(AnalyticsEvent.event_type == "bot_message", AnalyticsEvent.telegram_id.isnot(None))
        .group_by(AnalyticsEvent.telegram_id)
        .all()
    )
    first_contact_at = {tid: _aware_utc(ts) for tid, ts in contact_rows}

    # Stage 2: every registered account (Telegram or email), by signup time.
    registered_at = {uid: _aware_utc(ts) for uid, ts in User.query.with_entities(User.id, User.created_at).all()}

    # Stage 3: first completed face analysis per user -- "activation" here
    # means they actually ran the core feature at least once, not just opened
    # the app.
    activation_rows = (
        db.session.query(FaceAnalysis.user_id, func.min(FaceAnalysis.created_at))
        .group_by(FaceAnalysis.user_id)
        .all()
    )
    activated_at = {uid: _aware_utc(ts) for uid, ts in activation_rows}

    def stage(mapping):
        values = list(mapping.values())
        return {
            "total": len(values),
            "last7d": sum(1 for ts in values if ts and ts >= cutoff_7),
            "last30d": sum(1 for ts in values if ts and ts >= cutoff_30),
        }

    stages = {
        "bot_contacts": stage(first_contact_at),
        "registrations": stage(registered_at),
        "activations": stage(activated_at),
    }
    conversion = {
        "contact_to_register": _pct(stages["registrations"]["total"], stages["bot_contacts"]["total"]),
        "register_to_activate": _pct(stages["activations"]["total"], stages["registrations"]["total"]),
        "contact_to_activate": _pct(stages["activations"]["total"], stages["bot_contacts"]["total"]),
    }

    days = ANALYTICS_DAILY_DAYS
    contact_buckets = _daily_buckets(first_contact_at.values(), days)
    reg_buckets = _daily_buckets(registered_at.values(), days)
    act_buckets = _daily_buckets(activated_at.values(), days)
    daily = [
        {"date": day, "bot_contacts": contact_buckets[day], "registrations": reg_buckets[day], "activations": act_buckets[day]}
        for day in reg_buckets.keys()
    ]

    return jsonify({
        "generated_at": now.isoformat(),
        "tracking_note": "bot_contacts only counts messages received after this feature was deployed",
        "stages": stages,
        "conversion": conversion,
        "daily": daily,
    })
