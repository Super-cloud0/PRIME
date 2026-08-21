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


# Production Gemini vision implementation. Render starts gunicorn as server:app,
# so this compatibility layer owns the production Face AI route.
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
            "temperature": 0.0,
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

    prompt = """You are PRIME's STRICT visual self-improvement evaluator. Analyze ONLY visible, non-sensitive presentation features in the supplied photo. Never identify the person and never infer or mention age, race, ethnicity, religion, health, disability, sexual orientation, or other sensitive traits. Do not diagnose, sexualize, or make claims about immutable identity.

Your job is NOT to be nice. Your job is to produce a CONSISTENT, CONSERVATIVE, NON-INFLATED score. Do not give compliments merely because the photo is clear or the person looks generally pleasant. Penalize visible weaknesses and do not compensate for them with generic positivity.

CALIBRATION — follow this scale literally:
- 0-19: extremely poor visible presentation / unusable image quality for evaluation.
- 20-29: very weak visible presentation with many clear issues.
- 30-39: below average with several noticeable issues.
- 40-49: somewhat below average.
- 50-59: ordinary / average presentation. 50 is the true midpoint, not a bad score.
- 60-69: clearly above average, with multiple strengths and only limited weaknesses.
- 70-79: strong presentation; clearly uncommon and polished.
- 80-89: exceptional presentation; very few visible weaknesses.
- 90-94: extremely exceptional and rare; only use when the visible presentation is close to outstanding across nearly every scored dimension.
- 95-100: extraordinarily rare, near-perfect visible presentation. Almost never use this range.

IMPORTANT CALIBRATION RULES:
1. Do NOT default to 70, 80, or 90. Average people must cluster around 45-60.
2. A normal attractive/pleasant-looking photo is NOT automatically 70+.
3. A good haircut, clear skin appearance, or good lighting alone is NOT enough for a high score.
4. Any obvious weakness must lower the relevant metric and the overall score.
5. Judge the supplied image, not an imagined better version of the person.
6. Do not infer anything that is not clearly visible.
7. Lighting, camera angle, expression, image quality, grooming, hair, visible skin presentation, facial presentation, symmetry and proportion must be judged separately where visible.
8. If a dimension cannot be judged reliably from this image, lower confidence and use a neutral score for that dimension rather than inventing a strength.
9. Keep the score internally consistent: the overall score should approximately reflect the average of the visible metrics, with no unexplained boost.
10. Be especially conservative with scores above 70. A score above 80 requires strong evidence across nearly all visible dimensions.

Return ONLY valid JSON with exactly this shape: {"score": integer 0-100, "type": string, "summary": string, "metrics": {"symmetry": integer 0-100, "proportion": integer 0-100, "grooming": integer 0-100, "hair": integer 0-100, "skin_appearance": integer 0-100, "presentation": integer 0-100}, "tips": [string, ...], "confidence": integer 0-100}.

Give 3-5 direct, practical, safe improvement tips. Do not flatter the user. If the face is not clearly visible, confidence must be <=20 and do not invent observations."""

    try:
        result = _gemini_json_compat(prompt, base64.b64encode(raw).decode("ascii"), data.get("mime", "image/jpeg"))
        source_metrics = result.get("metrics") or {}
        allowed = {"symmetry", "proportion", "grooming", "hair", "skin_appearance", "presentation"}
        metrics = {}
        for key in allowed:
            value = source_metrics.get(key)
            if isinstance(value, (int, float)):
                metrics[key] = max(0, min(100, int(value)))

        if metrics:
            metric_average = round(sum(metrics.values()) / len(metrics))
        else:
            metric_average = 50

        model_score = result.get("score", metric_average)
        try:
            model_score = max(0, min(100, int(model_score)))
        except (TypeError, ValueError):
            model_score = metric_average

        # The model's headline score is deliberately given little influence.
        # This prevents flattering one-off scores from overriding its own metrics.
        score = round(metric_average * 0.75 + model_score * 0.25)

        # Strict ceiling unless the model provides consistently exceptional metrics.
        if score >= 90 and (not metrics or min(metrics.values()) < 85):
            score = 89
        if score >= 80 and (not metrics or sum(v >= 75 for v in metrics.values()) < 5):
            score = min(score, 79)

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


server_prod.gemini_json = _gemini_json_compat
server_prod.app.view_functions["face_ai"] = server_prod.auth_required(_face_ai_fixed)


with app.app_context():
    db.create_all()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8765")))
