from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import time
import uuid
from urllib.parse import parse_qsl

import requests
from flask import jsonify, request

from server_prod import User, app, db, jwt_encode, password_hash

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_AUTH_MAX_AGE = int(os.environ.get("TELEGRAM_AUTH_MAX_AGE", "86400"))
TELEGRAM_WEBAPP_URL = os.environ.get("TELEGRAM_WEBAPP_URL", "").strip()
TELEGRAM_WEBHOOK_SECRET = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "").strip()


def validate_telegram_init_data(init_data: str) -> dict:
    if not TELEGRAM_BOT_TOKEN:
        raise ValueError("Telegram authentication is not configured")
    if not init_data or len(init_data) > 8192:
        raise ValueError("invalid Telegram init data")

    fields = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = fields.pop("hash", "")
    if not received_hash or "user" not in fields or "auth_date" not in fields:
        raise ValueError("invalid Telegram init data")

    data_check_string = "\n".join(f"{key}={value}" for key, value in sorted(fields.items()))
    secret_key = hmac.new(b"WebAppData", TELEGRAM_BOT_TOKEN.encode(), hashlib.sha256).digest()
    expected_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected_hash, received_hash):
        raise ValueError("invalid Telegram signature")

    try:
        auth_date = int(fields["auth_date"])
    except (TypeError, ValueError):
        raise ValueError("invalid auth date")
    if abs(int(time.time()) - auth_date) > TELEGRAM_AUTH_MAX_AGE:
        raise ValueError("Telegram authorization expired")

    try:
        user = json.loads(fields["user"])
    except json.JSONDecodeError:
        raise ValueError("invalid Telegram user data")
    if not user.get("id"):
        raise ValueError("Telegram user id missing")
    return user


@app.post("/api/auth/telegram")
def telegram_auth():
    try:
        payload = request.get_json(silent=True) or {}
        tg_user = validate_telegram_init_data(str(payload.get("initData", "")))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 401

    telegram_id = str(tg_user["id"])
    account_key = f"tg_{telegram_id}@telegram.local"
    user = User.query.filter_by(email=account_key).first()
    display_name = " ".join(filter(None, [tg_user.get("first_name"), tg_user.get("last_name")])).strip()
    display_name = display_name[:50] or str(tg_user.get("username") or "PRIME USER")[:50]

    if user is None:
        # Telegram-only accounts still satisfy the DB password constraint.
        user = User(
            id=str(uuid.uuid4()),
            email=account_key,
            password_hash=password_hash(secrets.token_urlsafe(32)),
            name=display_name,
        )
        db.session.add(user)
    else:
        user.name = display_name
    db.session.commit()

    return jsonify({"token": jwt_encode(user.id), "user": {
        "id": user.id,
        "name": user.name,
        "elo": user.elo,
        "prime_score": user.prime_score,
        "wins": user.wins,
        "losses": user.losses,
        "games": user.games,
    }})


def telegram_api(method: str, payload: dict):
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")
    response = requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method}",
        json=payload,
        timeout=15,
    )
    response.raise_for_status()
    data = response.json()
    if not data.get("ok"):
        raise RuntimeError(data.get("description", "Telegram API error"))
    return data


def telegram_menu_markup():
    if not TELEGRAM_WEBAPP_URL:
        return None
    return {
        "inline_keyboard": [[
            {"text": "🚀 Открыть PRIME", "web_app": {"url": TELEGRAM_WEBAPP_URL}}
        ]]
    }


def telegram_send_start(chat_id: int, first_name: str = ""):
    name = first_name.strip() or "друг"
    text = (
        f"<b>PRIME</b> ⚡\n\n"
        f"Привет, {name}!\n"
        f"Здесь твой персональный профиль, PRIME Score, ELO, сравнения, музыка и AI-советы.\n\n"
        f"Нажми кнопку ниже, чтобы открыть приложение."
    )
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    markup = telegram_menu_markup()
    if markup:
        payload["reply_markup"] = markup
    else:
        payload["text"] += "\n\nMini App URL пока не настроен на сервере."
    return telegram_api("sendMessage", payload)


@app.post("/api/telegram/webhook")
def telegram_webhook():
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_WEBHOOK_SECRET:
        return jsonify({"error": "Telegram bot is not configured"}), 503

    supplied_secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if not hmac.compare_digest(supplied_secret, TELEGRAM_WEBHOOK_SECRET):
        return jsonify({"error": "forbidden"}), 403

    update = request.get_json(silent=True) or {}
    message = update.get("message") or {}
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    if not chat_id:
        return jsonify({"ok": True})

    text = str(message.get("text") or "").strip()
    first_name = str((message.get("from") or {}).get("first_name") or "")
    try:
        if text.startswith("/start") or text.startswith("/help"):
            telegram_send_start(int(chat_id), first_name)
        else:
            telegram_send_start(int(chat_id), first_name)
    except Exception:
        # Telegram retries failed webhooks; acknowledge the update so one bad
        # outbound request does not cause an endless retry loop.
        pass
    return jsonify({"ok": True})


# The first release uses SQLAlchemy's schema creation on startup so the MVP
# can boot cleanly on a fresh PostgreSQL instance without a migration step.
with app.app_context():
    db.create_all()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8765")))
