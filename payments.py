from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from functools import wraps

from flask import jsonify, request

import server as server_module
import server_prod
from server_prod import User, auth_required

db = server_prod.db
app = server_prod.app

# PRIME Pro: a soft-gated subscription paid with Telegram Stars (currency
# "XTR" in the Bot API -- no external payment provider/PCI surface needed,
# Telegram itself handles the actual charge). Everything below only tracks
# *entitlement* (pro_until) and *usage* (DailyUsage) -- the money movement
# itself happens entirely inside Telegram between the user and Telegram.
PRIME_PRO_PRICE_STARS = int(os.environ.get("PRIME_PRO_PRICE_STARS", "150"))
PRIME_PRO_DURATION_DAYS = int(os.environ.get("PRIME_PRO_DURATION_DAYS", "7"))
FREE_BATTLE_DAILY_LIMIT = int(os.environ.get("FREE_BATTLE_DAILY_LIMIT", "2"))
# Every invoice payload starts with one of these so the webhook can recognize
# and safely ignore payloads it didn't create (e.g. if this bot is ever
# reused for something else) instead of trusting arbitrary payload strings.
PRO_INVOICE_PAYLOAD_PREFIX = "prime_pro_7d"
# One-time purchase alternative to the weekly subscription -- math-wise, a
# single higher-ticket sale is worth more toward a fixed revenue goal than a
# weekly sub with typical churn on this kind of app (see the business-plan
# calculator this was modeled against), and it removes renewal risk entirely.
PRIME_LIFETIME_PRICE_STARS = int(os.environ.get("PRIME_LIFETIME_PRICE_STARS", "999"))
LIFETIME_INVOICE_PAYLOAD_PREFIX = "prime_pro_lifetime"
# Not a real forever -- just far enough out that is_pro() never has to special-
# case it, so every gate written against pro_until keeps working unchanged.
LIFETIME_DURATION_DAYS = 36500


class ProSubscription(db.Model):
    # Deliberately a separate table rather than a new column on User: a
    # SQLAlchemy declarative model's mapped attributes come from the class
    # body, so a column added by a raw ALTER TABLE alone (the pattern
    # reminders.py/server_prod.py use for existing columns) is invisible to
    # the ORM unless User itself is also edited in server_prod.py. Keeping
    # subscription state in its own table avoids touching that file at all
    # -- one row per subscriber, created on first purchase.
    __tablename__ = "pro_subscription"
    user_id = db.Column(db.String(36), db.ForeignKey("user.id", ondelete="CASCADE"), primary_key=True)
    pro_until = db.Column(db.DateTime(timezone=True), nullable=True)
    is_lifetime = db.Column(db.Boolean, nullable=False, default=False)


class StarPayment(db.Model):
    # Audit trail of completed Telegram Stars payments -- not used to derive
    # entitlement (user.pro_until is the source of truth for that), this is
    # for bookkeeping/support/future revenue reporting only.
    __tablename__ = "star_payment"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(36), db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    amount_stars = db.Column(db.Integer, nullable=False)
    invoice_payload = db.Column(db.String(120), nullable=False)
    telegram_charge_id = db.Column(db.String(120), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, index=True, default=lambda: datetime.now(timezone.utc))


class DailyUsage(db.Model):
    # Generic per-user/per-feature/per-day counter, used to cap free-tier
    # face battles without needing a dedicated table per gated feature.
    __tablename__ = "daily_usage"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(36), db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    feature = db.Column(db.String(30), nullable=False)
    day = db.Column(db.String(10), nullable=False)  # UTC "YYYY-MM-DD", not a DateTime -- it's a bucket key, not an instant
    count = db.Column(db.Integer, nullable=False, default=0)
    __table_args__ = (db.UniqueConstraint("user_id", "feature", "day", name="uq_daily_usage_user_feature_day"),)


def _ensure_lifetime_column():
    # pro_subscription shipped before is_lifetime existed -- if this ever runs
    # against a deployment that already created the table with the old shape,
    # db.create_all() alone won't add the missing column (same reasoning as
    # server_prod.py's _ensure_*_column helpers). Harmless no-op on a fresh
    # database, where create_all() below creates the table with the column
    # already in place.
    try:
        from sqlalchemy import inspect as _sa_inspect
        with app.app_context():
            inspector = _sa_inspect(db.engine)
            if "pro_subscription" not in inspector.get_table_names():
                return
            columns = {col["name"] for col in inspector.get_columns("pro_subscription")}
            if "is_lifetime" not in columns:
                with db.engine.begin() as conn:
                    conn.execute(db.text('ALTER TABLE pro_subscription ADD COLUMN is_lifetime BOOLEAN NOT NULL DEFAULT FALSE'))
    except Exception:
        app.logger.exception("PRIME auto-migrate for pro_subscription.is_lifetime failed (non-fatal)")


_ensure_lifetime_column()


# Both tables are brand new, so (like analytics.py's AnalyticsEvent) call
# db.create_all() again here -- server.py already called it once, before this
# module is even imported, so it never picked these up on its own.
with app.app_context():
    db.create_all()


def _aware_utc(ts):
    # SQLite (local dev/tests) drops the UTC offset on read for a
    # DateTime(timezone=True) column; Postgres (production) does not. Since
    # every timestamp here is always stored/generated as UTC, a naive value
    # just needs the tzinfo re-attached, never converted.
    if ts is not None and ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts


def _today_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _subscription_for(user_id: str) -> ProSubscription | None:
    return ProSubscription.query.get(user_id)


def is_pro(user: User) -> bool:
    sub = _subscription_for(user.id)
    until = _aware_utc(sub.pro_until) if sub else None
    return bool(until) and until > datetime.now(timezone.utc)


def _pro_payload(user: User) -> dict:
    sub = _subscription_for(user.id)
    return {
        "is_pro": is_pro(user),
        "is_lifetime": bool(sub and sub.is_lifetime),
        "pro_until": sub.pro_until.isoformat() if sub and sub.pro_until else None,
        "price_stars": PRIME_PRO_PRICE_STARS,
        "duration_days": PRIME_PRO_DURATION_DAYS,
        "lifetime_price_stars": PRIME_LIFETIME_PRICE_STARS,
        "battle_daily_limit": FREE_BATTLE_DAILY_LIMIT,
    }


@app.get("/api/pay/status")
@auth_required
def pay_status(user):
    return jsonify(_pro_payload(user))


@app.post("/api/pay/create-invoice")
@auth_required
def create_invoice(user):
    if not server_module.TELEGRAM_BOT_TOKEN:
        return jsonify({"error": "TELEGRAM_BOT_TOKEN is not configured"}), 503

    plan = str((request.get_json(silent=True) or {}).get("plan", "weekly")).strip().lower()
    if plan == "lifetime":
        prefix, price, title = LIFETIME_INVOICE_PAYLOAD_PREFIX, PRIME_LIFETIME_PRICE_STARS, "PRIME Pro Навсегда"
        description = "Разовая покупка: полный разбор по всем 6 метрикам, конкретные советы и безлимит батлов сравнения — без ограничения по времени."
        price_label = "PRIME Pro (навсегда)"
    else:
        plan = "weekly"
        prefix, price, title = PRO_INVOICE_PAYLOAD_PREFIX, PRIME_PRO_PRICE_STARS, "PRIME Pro"
        description = (
            f"Полный разбор по всем 6 метрикам, конкретные советы на неделю и безлимит батлов "
            f"сравнения на {PRIME_PRO_DURATION_DAYS} дней."
        )
        price_label = f"PRIME Pro ({PRIME_PRO_DURATION_DAYS} дней)"

    # user.id is embedded directly in the payload (not looked up separately)
    # so the webhook can grant Pro from the payload alone, with no session/
    # cookie context available at that point -- the trailing random suffix is
    # just so payloads aren't guessable/replayable across users.
    payload = f"{prefix}:{user.id}:{uuid.uuid4().hex[:12]}"
    try:
        data = server_module.telegram_api("createInvoiceLink", {
            "title": title,
            "description": description,
            "payload": payload,
            # Telegram Stars payments: currency must be "XTR" and
            # provider_token must be an empty string (no external provider).
            "currency": "XTR",
            "provider_token": "",
            "prices": [{"label": price_label, "amount": price}],
        })
    except Exception as exc:
        app.logger.exception("PRIME payments: createInvoiceLink failed")
        return jsonify({"error": f"failed to create invoice: {exc}"}), 502
    return jsonify({"invoice_link": data.get("result"), "price_stars": price, "plan": plan})


def _grant_pro_from_payment(message: dict, successful_payment: dict):
    payload = str(successful_payment.get("invoice_payload", ""))
    parts = payload.split(":")
    if len(parts) < 2 or parts[0] not in (PRO_INVOICE_PAYLOAD_PREFIX, LIFETIME_INVOICE_PAYLOAD_PREFIX):
        app.logger.warning("PRIME payments: unrecognized invoice payload %r", payload)
        return
    is_lifetime_purchase = parts[0] == LIFETIME_INVOICE_PAYLOAD_PREFIX
    user_id = parts[1]
    user = User.query.get(user_id)
    if user is None:
        app.logger.warning("PRIME payments: payment for unknown user_id %r", user_id)
        return

    default_amount = PRIME_LIFETIME_PRICE_STARS if is_lifetime_purchase else PRIME_PRO_PRICE_STARS
    try:
        amount = int(successful_payment.get("total_amount", default_amount))
    except (TypeError, ValueError):
        amount = default_amount

    now = datetime.now(timezone.utc)
    sub = _subscription_for(user.id)
    if sub is None:
        sub = ProSubscription(user_id=user.id)
        db.session.add(sub)
    if is_lifetime_purchase:
        sub.is_lifetime = True
        sub.pro_until = now + timedelta(days=LIFETIME_DURATION_DAYS)
    else:
        # Stack on top of remaining time rather than from "now" if they renew
        # early -- a normal subscription-extension behavior, not a special
        # case. A lifetime holder buying the weekly plan again (unlikely, but
        # not blocked) just keeps their lifetime status untouched.
        current_until = _aware_utc(sub.pro_until)
        base = current_until if current_until and current_until > now else now
        sub.pro_until = base + timedelta(days=PRIME_PRO_DURATION_DAYS)

    db.session.add(StarPayment(
        user_id=user.id,
        amount_stars=amount,
        invoice_payload=payload,
        telegram_charge_id=str(successful_payment.get("telegram_payment_charge_id", ""))[:120],
    ))
    db.session.commit()

    chat_id = (message.get("chat") or {}).get("id") or user.telegram_chat_id
    if chat_id:
        if sub.is_lifetime:
            confirmation_text = (
                "✅ <b>PRIME Pro Навсегда активирован!</b>\n\n"
                "Без ограничения по времени доступны: полный разбор по метрикам с конкретными советами и безлимит батлов сравнения."
            )
        else:
            confirmation_text = (
                "✅ <b>PRIME Pro активирован!</b>\n\n"
                f"Действует до {sub.pro_until.strftime('%d.%m.%Y')}.\n"
                "Теперь доступны: полный разбор по метрикам с конкретными советами и безлимит батлов сравнения."
            )
        try:
            server_module.telegram_api("sendMessage", {
                "chat_id": int(chat_id),
                "text": confirmation_text,
                "parse_mode": "HTML",
            })
        except Exception:
            app.logger.exception("PRIME payments: failed to send Pro-activated confirmation")


# Wrap the Telegram webhook (already wrapped once by analytics.py, itself
# wrapping the original from server.py) the same way both of those wrap it --
# grab whatever is currently registered, add payments-specific handling on
# top, and fall through to it for everything this module doesn't care about.
_original_webhook = app.view_functions.get("telegram_webhook")


def _webhook_with_payments():
    update = request.get_json(silent=True) or {}

    # Telegram requires answerPreCheckoutQuery within 10 seconds of the user
    # tapping "Pay", before it will actually charge them -- this must be
    # handled here, not deferred to background work.
    pre_checkout = update.get("pre_checkout_query")
    if pre_checkout:
        try:
            payload = str(pre_checkout.get("invoice_payload", ""))
            ok = payload.startswith(PRO_INVOICE_PAYLOAD_PREFIX + ":") or payload.startswith(LIFETIME_INVOICE_PAYLOAD_PREFIX + ":")
            answer = {"pre_checkout_query_id": pre_checkout.get("id"), "ok": ok}
            if not ok:
                answer["error_message"] = "Invoice expired or invalid — please try again from the app."
            server_module.telegram_api("answerPreCheckoutQuery", answer)
        except Exception:
            app.logger.exception("PRIME payments: answerPreCheckoutQuery failed")
        return jsonify({"ok": True})

    message = update.get("message") or {}
    successful_payment = message.get("successful_payment")
    if successful_payment:
        try:
            _grant_pro_from_payment(message, successful_payment)
        except Exception:
            db.session.rollback()
            app.logger.exception("PRIME payments: failed to grant Pro after successful_payment")
        # Deliberately does NOT fall through to _original_webhook() here --
        # that would also fire the generic "here's how to open PRIME"
        # welcome message right after a payment, which reads as a mistake
        # (as if the payment didn't register) rather than a confirmation.
        return jsonify({"ok": True})

    return _original_webhook()


if _original_webhook is not None:
    app.view_functions["telegram_webhook"] = _webhook_with_payments


# --- Gate 1: per-metric AI advice (the "why + how to fix" detail) -------
# /api/advice is defined in server_prod.py already wrapped in @auth_required,
# so app.view_functions["advice"] takes no args and resolves the user itself.
# Re-deriving the user here via server_prod.current_user() (rather than
# threading a flag through the original route) keeps this additive instead
# of requiring an edit to server_prod.py.
_original_advice = app.view_functions.get("advice")


def _advice_with_pro_gate():
    user = server_prod.current_user()
    if user is not None and not is_pro(user):
        return jsonify({
            "pro_locked": True,
            "tips": [],
            "focus": [],
        })
    return _original_advice()


if _original_advice is not None:
    app.view_functions["advice"] = _advice_with_pro_gate


# --- Gate 2: unlimited face battles ------------------------------------
# /api/face/compare is defined in server_face_override.py, also already
# wrapped in @auth_required.
_original_compare = app.view_functions.get("face_compare")


def _compare_with_daily_limit():
    user = server_prod.current_user()
    if user is None:
        return _original_compare()  # let auth_required's own 401 fire normally

    if not is_pro(user):
        today = _today_str()
        usage = DailyUsage.query.filter_by(user_id=user.id, feature="face_compare", day=today).first()
        used = usage.count if usage else 0
        if used >= FREE_BATTLE_DAILY_LIMIT:
            return jsonify({
                "pro_locked": True,
                "used": used,
                "limit": FREE_BATTLE_DAILY_LIMIT,
            })

    response = _original_compare()
    # Only count it if the comparison actually succeeded -- a failed AI call
    # (502) shouldn't burn someone's daily allowance.
    try:
        status_code = response[1] if isinstance(response, tuple) else response.status_code
    except Exception:
        status_code = 200
    if status_code == 200 and not is_pro(user):
        today = _today_str()
        usage = DailyUsage.query.filter_by(user_id=user.id, feature="face_compare", day=today).first()
        if usage is None:
            usage = DailyUsage(user_id=user.id, feature="face_compare", day=today, count=0)
            db.session.add(usage)
        usage.count += 1
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            app.logger.exception("PRIME payments: failed to record face_compare usage (non-fatal)")
    return response


if _original_compare is not None:
    app.view_functions["face_compare"] = _compare_with_daily_limit
