from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from urllib.parse import parse_qsl

from flask import jsonify, request

# Production app and models live in server_prod.py. This thin entrypoint keeps
# the existing API/UI while adding Telegram Mini App authentication.
from server_prod import User, app, db, jwt_encode

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_AUTH_MAX_AGE = int(os.environ.get("TELEGRAM_AUTH_MAX_AGE", "86400"))


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

    # The Telegram numeric ID is the account identity. We keep the existing
    # schema unchanged by using an internal, non-user-facing email key.
    telegram_id = str(tg_user["id"])
    account_key = f"tg_{telegram_id}@telegram.local"
    user = User.query.filter_by(email=account_key).first()
    display_name = " ".join(filter(None, [tg_user.get("first_name"), tg_user.get("last_name")])).strip()
    display_name = display_name[:50] or str(tg_user.get("username") or "PRIME USER")[:50]

    if user is None:
        user = User(email=account_key, password_hash=None, name=display_name)
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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8765")))
