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

import server_prod
from server_prod import User, app, db, jwt_encode, password_hash

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_AUTH_MAX_AGE = int(os.environ.get("TELEGRAM_AUTH_MAX_AGE", "86400"))
TELEGRAM_WEBAPP_URL = os.environ.get("TELEGRAM_WEBAPP_URL", "").strip()
TELEGRAM_WEBHOOK_SECRET = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "").strip()


def validate_telegram_init_data(init_data: str) -> dict:
    if not TELEGRAM_BOT_TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN is missing in Render Environment")
    if not init_data or len(init_data) > 8192:
        raise ValueError("Telegram initData is empty or invalid")

    fields = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = fields.pop("hash", "")
    if not received_hash or "user" not in fields or "auth_date" not in fields:
        raise ValueError("Telegram initData is missing hash, user or auth_date")

    data_check_string = "\n".join(f"{key}={value}" for key, value in sorted(fields.items()))
    secret_key = hmac.new(b"WebAppData", TELEGRAM_BOT_TOKEN.encode(), hashlib.sha256).digest()
    expected_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected_hash, received_hash):
        raise ValueError("invalid Telegram signature — check that TELEGRAM_BOT_TOKEN is the same token used by the bot")

    try:
        auth_date = int(fields["auth_date"])
    except (TypeError, ValueError):
        raise ValueError("invalid Telegram auth_date")
    if abs(int(time.time()) - auth_date) > TELEGRAM_AUTH_MAX_AGE:
        raise ValueError("Telegram authorization expired — reopen PRIME from the bot")

    try:
        user = json.loads(fields["user"])
    except json.JSONDecodeError:
        raise ValueError("invalid Telegram user JSON")
    if not user.get("id"):
        raise ValueError("Telegram user id missing")
    return user


@app.post("/api/auth/telegram")
def telegram_auth():
    try:
        payload = request.get_json(silent=True) or {}
        init_data = str(payload.get("initData", ""))
        if not init_data:
            init_data = request.headers.get("X-Telegram-Init-Data", "")
        tg_user = validate_telegram_init_data(init_data)

        telegram_id = str(tg_user["id"])
        account_key = f"tg_{telegram_id}@telegram.local"
        user = User.query.filter_by(email=account_key).first()
        display_name = " ".join(filter(None, [tg_user.get("first_name"), tg_user.get("last_name")])).strip()
        display_name = display_name[:50] or str(tg_user.get("username") or "PRIME USER")[:50]

        if user is None:
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
        token = jwt_encode(user.id)
        return jsonify({"token": token, "user": {
            "id": user.id,
            "name": user.name,
            "elo": user.elo,
            "prime_score": user.prime_score,
            "wins": user.wins,
            "losses": user.losses,
            "games": user.games,
        }})
    except ValueError as exc:
        db.session.rollback()
        return jsonify({"error": str(exc)}), 401
    except RuntimeError as exc:
        db.session.rollback()
        return jsonify({"error": str(exc)}), 503
    except Exception as exc:
        db.session.rollback()
        app.logger.exception("Telegram authentication failed")
        return jsonify({"error": f"Telegram auth server error: {type(exc).__name__}: {exc}"}), 500


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
        app.logger.exception("Telegram webhook outbound request failed")
    return jsonify({"ok": True})


# Gemini vision compatibility patch.
# The current Gemini 2.5 Flash / Flash-Lite API no longer needs the old
# temperature/responseMimeType settings used by the previous implementation.
# Keep the existing /api/face-ai route, but make its Gemini helper robust.
def _gemini_json_compat(prompt: str, image_b64: str | None = None, mime: str = "image/jpeg"):
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("AI service is not configured: GEMINI_API_KEY is missing")

    parts = [{"text": prompt}]
    if image_b64:
        parts.append({"inline_data": {"mime_type": mime if mime.startswith("image/") else "image/jpeg", "data": image_b64}})

    payload = {
        "contents": [{"parts": parts}],
        "generationConfig": {"maxOutputTokens": 2048},
    }

    configured = os.environ.get("GEMINI_MODEL", "").strip()
    models = []
    for model in [configured, "gemini-2.5-flash-lite", "gemini-2.5-flash"]:
        if model and model not in models:
            models.append(model)

    errors = []
    for model in models:
        try:
            response = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
                json=payload,
                timeout=60,
            )
            if response.ok:
                body = response.json()
                text = "".join(
                    part.get("text", "")
                    for candidate in body.get("candidates", [])
                    for part in candidate.get("content", {}).get("parts", [])
                    if isinstance(part, dict)
                ).strip()
                if not text:
                    raise RuntimeError("Gemini returned an empty response")
                return server_prod.extract_json(text)

            try:
                detail = response.json().get("error", {}).get("message", response.text)
            except Exception:
                detail = response.text
            errors.append(f"{model}: HTTP {response.status_code}: {str(detail)[:240]}")
        except requests.RequestException as exc:
            errors.append(f"{model}: {type(exc).__name__}: {str(exc)[:180]}")

    raise RuntimeError("Gemini request failed; " + " | ".join(errors))


server_prod.gemini_json = _gemini_json_compat


with app.app_context():
    db.create_all()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8765")))
