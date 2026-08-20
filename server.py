from __future__ import annotations

import base64
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


# Production Gemini vision implementation.
# This replaces the old server_prod handler at runtime, so Render's
# gunicorn server:app entrypoint always uses this implementation.
def _gemini_json_compat(prompt: str, image_b64: str | None = None, mime: str = "image/jpeg"):
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is missing in Render Environment")

    if image_b64:
        try:
            base64.b64decode(image_b64, validate=True)
        except Exception as exc:
            raise ValueError(f"server received invalid base64 image: {exc}")

    parts = [{"text": prompt}]
    if image_b64:
        safe_mime = mime if isinstance(mime, str) and mime.startswith("image/") else "image/jpeg"
        parts.append({"inline_data": {"mime_type": safe_mime, "data": image_b64}})

    payload = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {
            "maxOutputTokens": 2048,
            "responseMimeType": "application/json",
        },
    }

    configured = os.environ.get("GEMINI_MODEL", "").strip()
    models = []
    for model in [configured, "gemini-2.5-flash-lite", "gemini-2.5-flash"]:
        if model and model not in models:
            models.append(model)

    errors = []
    for model in models:
        for api_version in ("v1beta", "v1"):
            try:
                response = requests.post(
                    f"https://generativelanguage.googleapis.com/{api_version}/models/{model}:generateContent",
                    headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
                    json=payload,
                    timeout=60,
                )
                if not response.ok:
                    try:
                        body = response.json()
                        detail = body.get("error", {}).get("message", response.text)
                    except Exception:
                        detail = response.text
                    errors.append(f"{model}/{api_version}: HTTP {response.status_code}: {str(detail)[:300]}")
                    continue

                body = response.json()
                candidates = body.get("candidates") or []
                if not candidates:
                    prompt_feedback = body.get("promptFeedback") or {}
                    errors.append(f"{model}/{api_version}: no candidates; promptFeedback={str(prompt_feedback)[:300]}")
                    continue

                text_parts = []
                for candidate in candidates:
                    for part in (candidate.get("content") or {}).get("parts") or []:
                        if isinstance(part, dict) and isinstance(part.get("text"), str):
                            text_parts.append(part["text"])
                text = "".join(text_parts).strip()
                if not text:
                    finish = [c.get("finishReason") for c in candidates]
                    errors.append(f"{model}/{api_version}: empty text; finishReason={finish}")
                    continue

                try:
                    return server_prod.extract_json(text)
                except Exception as exc:
                    errors.append(f"{model}/{api_version}: invalid JSON from model: {exc}; raw={text[:500]}")
            except requests.RequestException as exc:
                errors.append(f"{model}/{api_version}: network error {type(exc).__name__}: {str(exc)[:220]}")

    raise RuntimeError("Gemini request failed: " + " | ".join(errors))


def _face_ai_fixed(user):
    data = request.get_json(silent=True) or {}
    image_b64 = data.get("image")
    if not image_b64 or not isinstance(image_b64, str):
        return jsonify({"error": "image is required"}), 400

    try:
        raw = base64.b64decode(image_b64, validate=True)
    except Exception:
        return jsonify({"error": "invalid image"}), 400
    if len(raw) > 8 * 1024 * 1024:
        return jsonify({"error": "image too large"}), 413

    prompt = """You are PRIME's strict visual self-improvement coach. Analyze only visible, non-sensitive presentation features in the supplied photo. Never identify the person and never infer or mention age, race, ethnicity, religion, health, disability, sexual orientation, or other sensitive traits. Do not diagnose or sexualize. Be strict and honest: do not inflate scores. Judge visible presentation quality against a demanding adult grooming/style standard. Return ONLY valid JSON with this exact shape: {score: integer 0-100, type: string, summary: string, metrics: {symmetry: integer, proportion: integer, grooming: integer, hair: integer, skin_appearance: integer, presentation: integer}, tips: [string, ...], confidence: integer 0-100}. All metric values and score must be integers. Give 3-5 practical, safe improvement tips. If the face is not clearly visible, set confidence <=20 and do not invent observations."""

    try:
        result = _gemini_json_compat(prompt, base64.b64encode(raw).decode("ascii"), data.get("mime", "image/jpeg"))
        score = max(0, min(100, int(result.get("score", 0))))
        source_metrics = result.get("metrics") or {}
        metrics = {
            key: max(0, min(100, int(value)))
            for key, value in source_metrics.items()
            if key in {"symmetry", "proportion", "grooming", "hair", "skin_appearance", "presentation"}
            and isinstance(value, (int, float))
        }
        tips = [str(value)[:300] for value in (result.get("tips") or [])[:5]]
        confidence = max(0, min(100, int(result.get("confidence", 0))))
        analysis = server_prod.FaceAnalysis(
            id=str(uuid.uuid4()),
            user_id=user.id,
            score=score,
            analysis_type=str(result.get("type", "HTN"))[:20],
            summary=str(result.get("summary", ""))[:2000],
            metrics_json=json.dumps(metrics),
            tips_json=json.dumps(tips),
            confidence=confidence,
        )
        user.prime_score = score
        db.session.add(analysis)
        db.session.commit()
        result.update({"score": score, "metrics": metrics, "tips": tips, "confidence": confidence, "analysis_id": analysis.id})
        return jsonify(result)
    except requests.RequestException as exc:
        db.session.rollback()
        app.logger.exception("Face AI request failed")
        return jsonify({"error": f"AI service temporarily unavailable: {type(exc).__name__}: {exc}"}), 502
    except Exception as exc:
        db.session.rollback()
        app.logger.exception("Face AI analysis failed")
        return jsonify({"error": f"AI analysis failed: {type(exc).__name__}: {exc}"}), 502


# The production route is registered by server_prod.py. Replace its view
# function so this handler is used without changing Render's start command.
server_prod.gemini_json = _gemini_json_compat
server_prod.app.view_functions["face_ai"] = server_prod.auth_required(_face_ai_fixed)


with app.app_context():
    db.create_all()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8765")))
