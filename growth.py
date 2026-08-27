from __future__ import annotations

import os
import re

from flask import jsonify, request

import analytics
import server_prod
from server_prod import User, auth_required

app = server_prod.app

# Set this on Render to the bot's @username (no leading @) once it's known --
# without it, referral links can't be built (t.me/<username>?start=ref_<id>
# needs the username), so /api/growth/referral-link just returns link: null
# and the frontend falls back to sharing the plain app link with no
# attribution, same as before this feature existed.
TELEGRAM_BOT_USERNAME = os.environ.get("TELEGRAM_BOT_USERNAME", "").strip().lstrip("@")

# Telegram sends a plain "/start ref_<id>" (or "/start@BotName ref_<id>" in
# group contexts, though this bot is only ever used in private chats) as the
# message text when someone opens the bot via a t.me/<bot>?start=ref_<id>
# deep link. The payload after "ref_" is the referring user's telegram_chat_id
# -- see referral_link_for() below, which is the only place that value is
# ever put into a link.
_REF_START_RE = re.compile(r"^/start(?:@\w+)?(?:\s+ref_(\d+))?\s*$")


def referral_link_for(telegram_id) -> str | None:
    if not TELEGRAM_BOT_USERNAME or not telegram_id:
        return None
    return f"https://t.me/{TELEGRAM_BOT_USERNAME}?start=ref_{telegram_id}"


@app.get("/api/growth/referral-link")
@auth_required
def growth_referral_link(user):
    return jsonify({
        "link": referral_link_for(user.telegram_chat_id),
        "bot_username": TELEGRAM_BOT_USERNAME or None,
    })


# Fired from the frontend when someone taps one of the share-panel buttons
# (download / native share sheet / Telegram / copy link) -- purely a counter,
# no PII beyond the same telegram_id every other analytics event already
# carries.
_SHARE_CHANNELS = {"download", "native", "telegram", "copy"}


@app.post("/api/growth/share-click")
@auth_required
def growth_share_click(user):
    channel = str((request.get_json(silent=True) or {}).get("channel", "")).strip().lower()
    if channel not in _SHARE_CHANNELS:
        channel = "unknown"
    analytics._log_event("share_click", telegram_id=user.telegram_chat_id, meta=channel)
    return jsonify({"ok": True})


# Wrap the webhook again (this module is imported last in
# server_face_override.py, after analytics.py and payments.py, so this grabs
# whichever wrapper is currently registered and falls through to it) purely
# to notice a referral /start before the normal welcome-message handling in
# server.py's original webhook runs.
_original_webhook = app.view_functions.get("telegram_webhook")


def _webhook_with_growth():
    try:
        update = request.get_json(silent=True) or {}
        message = update.get("message") or {}
        chat_id = (message.get("chat") or {}).get("id")
        match = _REF_START_RE.match(str(message.get("text") or ""))
        if match and match.group(1) and chat_id:
            referrer_id = match.group(1)
            # No self-referral credit, and only the first /start with a
            # referral payload counts per chat_id -- otherwise re-opening an
            # old referral link on every visit would keep inflating the count.
            if str(chat_id) != referrer_id:
                already = analytics.AnalyticsEvent.query.filter_by(
                    event_type="referral_start", telegram_id=int(chat_id)
                ).first()
                if already is None:
                    analytics._log_event("referral_start", telegram_id=int(chat_id), meta=referrer_id[:20])
    except Exception:
        app.logger.exception("PRIME growth: failed to record referral_start (non-fatal)")
    return _original_webhook()


if _original_webhook is not None:
    app.view_functions["telegram_webhook"] = _webhook_with_growth
