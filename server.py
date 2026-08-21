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
    return {"inline_keyboard": [[
        {"text": "🚀 Открыть PRIME", "web_app": {"url": TELEGRAM_WEBAPP_URL}}
    ]]}


def telegram_send_start(chat_id: int, first_name: str = ""):
    name = first_name.strip() or "друг"
    payload = {
        "chat_id": chat_id,
        "text": (
            f"<b>PRIME</b> ⚡\n\n"
            f"Привет, {name}!\n"
            f"Здесь твой персональный профиль, PRIME Score, ELO, сравнения, музыка и AI-советы.\n\n"
            f"Нажми кнопку ниже, чтобы открыть приложение."
        ),
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

    first_name = str((message.get("from") or {}).get("first_name") or "")
    try:
        telegram_send_start(int(chat_id), first_name)
    except Exception:
        app.logger.exception("Telegram webhook outbound request failed")
    return jsonify({"ok": True})


GEMINI_MODEL = "gemini-3.5-flash-lite"
GEMINI_API_VERSION = "v1beta"


def _gemini_json_compat(prompt: str, image_b64: str | None = None, mime: str = "image/jpeg"):
    """Single production Gemini path. Never falls back to retired 2.5 models."""
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is missing in Render Environment")

    parts = [{"text": prompt}]
    if image_b64:
        try:
            base64.b64decode(image_b64, validate=True)
        except Exception as exc:
            raise ValueError(f"server received invalid base64 image: {exc}")
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

    url = f"https://generativelanguage.googleapis.com/{GEMINI_API_VERSION}/models/{GEMINI_MODEL}:generateContent"
    last_error = "unknown Gemini error"
    for attempt in range(2):
        try:
            response = requests.post(
                url,
                params={"key": api_key},
                headers={"Content-Type": "application/json"},
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
                    feedback = body.get("promptFeedback") or {}
                    raise RuntimeError(f"Gemini returned no analysis: {feedback}")
                result = server_prod.extract_json(text)
                if not isinstance(result, dict):
                    raise RuntimeError("Gemini returned invalid JSON object")
                return result

            try:
                detail = response.json().get("error", {}).get("message", response.text[:500])
            except Exception:
                detail = response.text[:500]
            last_error = f"Gemini {response.status_code}: {detail}"
            if response.status_code not in (400, 429, 500, 502, 503, 504) or attempt == 1:
                break
            time.sleep(1.5)
        except requests.RequestException as exc:
            last_error = f"Gemini request failed: {type(exc).__name__}: {exc}"
            if attempt == 1:
                break
            time.sleep(1.5)

    raise RuntimeError(last_error)


def _face_ai_fixed(user):
    data = request.get_json(silent=True) or {}
    image_b64 = data.get("image")
    if not image_b64 or not isinstance(image_b64, str):
        return jsonify({"error": "image is required"}), 400
    if image_b64.startswith("data:") and "," in image_b64:
        image_b64 = image_b64.split(",", 1)[1]

    try:
        raw = base64.b64decode(image_b64, validate=True)
    except Exception:
        return jsonify({"error": "invalid image"}), 400
    if len(raw) > 8 * 1024 * 1024:
        return jsonify({"error": "image too large"}), 413

    mime = str(data.get("mime") or "image/jpeg").lower().split(";")[0].strip()
    if mime not in {"image/jpeg", "image/png", "image/webp"}:
        mime = "image/jpeg"

    prompt = """You are PRIME's strict visual presentation evaluator.
Analyze ONLY visible, non-sensitive presentation characteristics in THIS photo. Do not identify the person. Do not infer or mention age, race, ethnicity, religion, health, disability, sexual orientation, gender identity, or other sensitive traits. Do not diagnose or sexualize.

Be conservative, consistent and honest. Your job is NOT to flatter. Judge only visible evidence and do not invent flaws or strengths. A clear photo, good lighting or one strong feature must NOT inflate the overall score.

CALIBRATION:
0-29 extremely weak; 30-39 clearly weak; 40-49 below average; 50-59 ordinary/average; 60-69 above average; 70-79 strong and uncommon; 80-89 excellent and rare; 90-94 exceptional and very rare; 95-100 extraordinarily rare.
Most ordinary photos MUST remain 45-60. 70+ requires multiple consistently strong visible dimensions. 80+ requires exceptional performance across nearly every dimension. 90+ is almost never appropriate.

Evaluate only: symmetry, proportion/harmony, grooming, hairstyle, visible skin presentation, lighting/angle, image quality and overall presentation. If a dimension cannot be judged reliably, use a neutral value and reduce confidence instead of guessing positively.

Return ONLY valid JSON with exactly this shape:
{"score": integer 0-100, "type": string, "summary": string, "metrics": {"symmetry": integer 0-100, "proportion": integer 0-100, "grooming": integer 0-100, "hair": integer 0-100, "skin_appearance": integer 0-100, "presentation": integer 0-100}, "tips": [string, ...], "confidence": integer 0-100}

Give 3-5 practical, safe improvement tips tied to visible presentation. Do not flatter. If the face is not clearly visible, confidence must be <=20 and observations must remain neutral."""

    try:
        result = _gemini_json_compat(prompt, base64.b64encode(raw).decode("ascii"), mime)
        source_metrics = result.get("metrics") if isinstance(result.get("metrics"), dict) else {}
        keys = ["symmetry", "proportion", "grooming", "hair", "skin_appearance", "presentation"]
        metrics = {}
        for key in keys:
            try:
                metrics[key] = max(0, min(100, int(source_metrics.get(key, 50))))
            except (TypeError, ValueError):
                metrics[key] = 50

        metric_average = round(sum(metrics.values()) / len(metrics))
        try:
            model_score = max(0, min(100, int(result.get("score", metric_average))))
        except (TypeError, ValueError):
            model_score = metric_average

        # Conservative server-side calibration: Gemini's headline score is
        # secondary to its six component metrics.
        score = round(metric_average * 0.8 + model_score * 0.2)
        weak = sum(v < 50 for v in metrics.values())
        very_weak = sum(v < 40 for v in metrics.values())
        score -= weak * 1.5
        score -= very_weak * 2
        if min(metrics.values()) < 55:
            score = min(score, 69)
        if sum(v >= 70 for v in metrics.values()) < 5:
            score = min(score, 74)
        if sum(v >= 80 for v in metrics.values()) < 5:
            score = min(score, 79)
        if sum(v >= 90 for v in metrics.values()) < 5:
            score = min(score, 89)
        score = max(10, min(95, round(score)))

        tips = [str(v).strip()[:300] for v in (result.get("tips") or []) if str(v).strip()][:5]
        try:
            confidence = max(0, min(100, int(result.get("confidence", 0))))
        except (TypeError, ValueError):
            confidence = 0

        analysis = server_prod.FaceAnalysis(
            id=str(uuid.uuid4()),
            user_id=user.id,
            score=score,
            analysis_type=str(result.get("type", "HTN"))[:20],
            summary=str(result.get("summary", "Analysis completed."))[:2000],
            metrics_json=json.dumps(metrics, ensure_ascii=False),
            tips_json=json.dumps(tips, ensure_ascii=False),
            confidence=confidence,
        )
        user.prime_score = score
        db.session.add(analysis)
        db.session.commit()

        return jsonify({
            "score": score,
            "type": analysis.analysis_type,
            "summary": analysis.summary,
            "metrics": metrics,
            "tips": tips,
            "confidence": confidence,
            "analysis_id": analysis.id,
        })
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
