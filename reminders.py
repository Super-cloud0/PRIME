from __future__ import annotations

import hmac
import os
from datetime import datetime, timedelta, timezone

from flask import jsonify, request
from sqlalchemy import func, or_

import server as server_module
import server_prod
from server_prod import FaceAnalysis, User, auth_required

db = server_prod.db
app = server_prod.app

# A user is "due" once REMINDER_STALE_DAYS have passed since their latest
# check-in (the feature is "score once a week", so 7 is the natural default).
# REMINDER_COOLDOWN_DAYS guards against re-sending before a week has passed
# even if the scheduled job or /api/cron/weekly-reminders fires more often
# than once a day -- it also doubles as the concurrency-safety window (see
# send_weekly_reminders()).
REMINDER_STALE_DAYS = int(os.environ.get("REMINDER_STALE_DAYS", "7"))
REMINDER_COOLDOWN_DAYS = int(os.environ.get("REMINDER_COOLDOWN_DAYS", "6"))
CRON_SECRET = os.environ.get("CRON_SECRET", "").strip()


def _weekly_reminder_payload(user: User) -> dict:
    payload = {
        "chat_id": user.telegram_chat_id,
        "text": (
            "📸 <b>Пора на еженедельный чек-ин PRIME</b>\n\n"
            "Прошла неделя с последнего скана — самое время сделать новое фото "
            "и посмотреть, как изменился твой PRIME Score.\n\n"
            "Прогресс видно только в сравнении, так что не пропускай неделю."
        ),
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    markup = server_module.telegram_menu_markup()
    if markup:
        payload["reply_markup"] = markup
    return payload


def send_weekly_reminders() -> dict:
    """
    Nudge every opted-in user whose latest FaceAnalysis is stale. Only users
    with at least one prior check-in are considered -- this is a "keep your
    streak going" reminder, not an onboarding message for people who've never
    tried the feature.

    The claim (setting last_reminder_at) happens with a single conditional
    UPDATE per user *before* the Telegram call, so two overlapping runs (the
    in-process scheduler racing a manual /api/cron/weekly-reminders hit, or
    multiple gunicorn workers) can't both send to the same person.
    """
    if not server_module.TELEGRAM_BOT_TOKEN:
        return {"sent": 0, "candidates": 0, "errors": 0, "reason": "telegram not configured"}

    now = datetime.now(timezone.utc)
    stale_cutoff = now - timedelta(days=REMINDER_STALE_DAYS)
    cooldown_cutoff = now - timedelta(days=REMINDER_COOLDOWN_DAYS)

    latest_checkin = (
        db.session.query(FaceAnalysis.user_id, func.max(FaceAnalysis.created_at).label("last_at"))
        .group_by(FaceAnalysis.user_id)
        .subquery()
    )

    candidates = (
        User.query.join(latest_checkin, User.id == latest_checkin.c.user_id)
        .filter(User.telegram_chat_id.isnot(None))
        .filter(User.reminders_enabled.is_(True))
        .filter(or_(User.last_reminder_at.is_(None), User.last_reminder_at < cooldown_cutoff))
        .filter(latest_checkin.c.last_at < stale_cutoff)
        .all()
    )

    sent = errors = 0
    for user in candidates:
        claimed = User.query.filter(
            User.id == user.id,
            or_(User.last_reminder_at.is_(None), User.last_reminder_at < cooldown_cutoff),
        ).update({"last_reminder_at": now}, synchronize_session=False)
        db.session.commit()
        if not claimed:
            continue  # another run already claimed this user
        try:
            server_module.telegram_api("sendMessage", _weekly_reminder_payload(user))
            sent += 1
        except Exception:
            app.logger.exception("Weekly reminder send failed for user %s", user.id)
            errors += 1

    return {"sent": sent, "candidates": len(candidates), "errors": errors}


@app.get("/api/reminders/status")
@auth_required
def reminders_status(user):
    return jsonify({"enabled": bool(user.reminders_enabled), "linked": bool(user.telegram_chat_id)})


@app.post("/api/reminders/opt-in")
@auth_required
def reminders_opt_in(user):
    enabled = bool((request.get_json(silent=True) or {}).get("enabled", True))
    user.reminders_enabled = enabled
    db.session.commit()
    return jsonify({"enabled": user.reminders_enabled, "linked": bool(user.telegram_chat_id)})


@app.post("/api/cron/weekly-reminders")
def cron_weekly_reminders():
    # Manual/external trigger -- useful for a Render Cron Job hitting this
    # endpoint on a schedule instead of (or in addition to) the in-process
    # scheduler below, and for testing the whole flow on demand.
    if not CRON_SECRET:
        return jsonify({"error": "CRON_SECRET is not configured"}), 503
    supplied = request.headers.get("X-Cron-Secret", "")
    if not hmac.compare_digest(supplied, CRON_SECRET):
        return jsonify({"error": "forbidden"}), 403
    return jsonify(send_weekly_reminders())


def _start_scheduler():
    # Opt-out escape hatch and an implicit "nothing configured" guard --
    # without a bot token there's nowhere to send reminders anyway.
    if os.environ.get("WEEKLY_REMINDERS_DISABLED", "") == "1":
        return
    if not server_module.TELEGRAM_BOT_TOKEN:
        return
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
    except Exception:
        app.logger.warning(
            "APScheduler not installed -- weekly reminders will only run via POST /api/cron/weekly-reminders"
        )
        return

    def _job():
        with app.app_context():
            try:
                app.logger.info("Weekly reminders run: %s", send_weekly_reminders())
            except Exception:
                app.logger.exception("Weekly reminders scheduled run failed")

    hour = int(os.environ.get("WEEKLY_REMINDERS_HOUR_UTC", "12"))
    scheduler = BackgroundScheduler(daemon=True, timezone="UTC")
    scheduler.add_job(_job, "cron", hour=hour, minute=0, id="prime_weekly_reminders", replace_existing=True)
    scheduler.start()


_start_scheduler()
