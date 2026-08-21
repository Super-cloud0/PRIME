from __future__ import annotations

import base64
import json
import os
import time
import uuid

import requests
from flask import jsonify, request

# Register Telegram auth/webhook routes on the same Flask app used by Render.
import server  # noqa: F401
from server_prod import FaceAnalysis, app, auth_required, db, extract_json, limiter


def gemini_json_strict(prompt: str, image_b64: str, mime: str) -> dict:
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not configured on Render")

    payload = {
        "contents": [{
            "role": "user",
            "parts": [
                {"text": prompt},
                {"inline_data": {"mime_type": mime, "data": image_b64}},
            ],
        }],
        "generationConfig": {
            "temperature": 0,
            "maxOutputTokens": 2048,
            "responseMimeType": "application/json",
        },
    }

    # Do not allow an old Render GEMINI_MODEL value to select a retired model.
    # The previous 2.5 models are explicitly rejected by Google's current API.
    configured = os.environ.get("GEMINI_MODEL", "").strip()
    retired = {"gemini-2.5-flash-lite", "gemini-2.5-flash"}
    models = []
    if configured and configured not in retired:
        models.append(configured)
    models.append("gemini-3.5-flash-lite")

    last_error = "unknown Gemini error"
    for model in dict.fromkeys(models):
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        for attempt in range(2):
            try:
                response = requests.post(
                    url,
                    params={"key": api_key},
                    headers={"Content-Type": "application/json"},
                    json=payload,
                    timeout=60,
                )

                if not response.ok:
                    try:
                        error = response.json().get("error", {})
                        message = error.get("message") or response.text[:500]
                    except Exception:
                        message = response.text[:500]
                    last_error = f"Gemini {response.status_code}: {message}"

                    if response.status_code == 404:
                        break
                    if response.status_code in (400, 429, 500, 502, 503, 504):
                        if attempt == 0:
                            time.sleep(1.5)
                            continue
                        break
                    raise RuntimeError(last_error)

                body = response.json()
                text = "".join(
                    part.get("text", "")
                    for candidate in body.get("candidates", [])
                    for part in candidate.get("content", {}).get("parts", [])
                    if isinstance(part, dict)
                )
                if not text.strip():
                    feedback = body.get("promptFeedback") or {}
                    reason = feedback.get("blockReason") or "no text returned"
                    last_error = f"Gemini returned no analysis ({reason})"
                    break

                result = extract_json(text)
                if not isinstance(result, dict):
                    raise RuntimeError("Gemini returned invalid JSON object")
                return result

            except requests.RequestException as exc:
                last_error = f"Gemini request failed: {type(exc).__name__}: {exc}"
                if attempt == 0:
                    time.sleep(1.5)
                    continue
                break

    raise RuntimeError(last_error)


@app.post("/api/face-ai", endpoint="face_ai_override")
@auth_required
def face_ai_override(user):
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

    prompt = """You are PRIME's STRICT visual presentation evaluator.
Analyze ONLY visible, non-sensitive appearance and presentation characteristics in THIS photo.
Do not identify the person. Do not infer or mention age, race, ethnicity, religion, health, disability, sexual orientation, gender identity, or other sensitive traits. Do not diagnose. Do not sexualize.
Be genuinely strict and calibrated. Do not give a high score merely because of flattering lighting. Do not reward a single strong feature with a high overall score. Do not invent flaws.
Evaluate only visible evidence: grooming, hairstyle, visible skin presentation, visually observable symmetry, facial proportion/harmony, lighting, angle, image quality, and overall presentation.
Calibration: 0-29 extremely weak; 30-39 clearly weak; 40-49 below average; 50-59 ordinary/average; 60-69 above average; 70-79 strong and uncommon; 80-89 excellent and rare; 90-94 exceptional and very rare; 95-100 extraordinarily rare.
Most ordinary photos MUST remain around 45-60. 70+ requires consistently strong visible evidence. 80+ requires exceptional performance across nearly every metric. 90+ should be almost never used.
If a dimension cannot be judged reliably, use a neutral value rather than guessing positively.
Return ONLY valid JSON with exactly these keys: score, type, summary, metrics, tips, confidence.
metrics MUST contain exactly: symmetry, proportion, grooming, hair, skin_appearance, presentation. All numeric values are integers 0-100.
type must be one of SUB 5, MTN, HTN, LTN, CHAD.
tips must contain 3-5 practical, safe, non-medical suggestions tied to visible weaknesses.
confidence is confidence in visible evidence, 0-100.
"""

    try:
        result = gemini_json_strict(prompt, base64.b64encode(raw).decode("ascii"), mime)
        required = ["symmetry", "proportion", "grooming", "hair", "skin_appearance", "presentation"]
        source_metrics = result.get("metrics") if isinstance(result.get("metrics"), dict) else {}
        metrics = {}
        for key in required:
            try:
                metrics[key] = max(0, min(100, int(source_metrics.get(key, 0))))
            except (TypeError, ValueError):
                metrics[key] = 0

        # Do not trust Gemini's headline score. Recalculate a conservative
        # score from component metrics so one flattering output cannot inflate it.
        weights = {
            "symmetry": 0.22,
            "proportion": 0.22,
            "grooming": 0.15,
            "hair": 0.12,
            "skin_appearance": 0.14,
            "presentation": 0.15,
        }
        raw_score = sum(metrics[key] * weights[key] for key in required)
        score = 50 + (raw_score - 50) * 0.75
        weak = sum(1 for value in metrics.values() if value < 50)
        very_weak = sum(1 for value in metrics.values() if value < 40)
        score -= weak * 1.5
        score -= very_weak * 2.0

        if min(metrics.values()) < 55:
            score = min(score, 69)
        if sum(value >= 70 for value in metrics.values()) < 5:
            score = min(score, 74)
        if sum(value >= 80 for value in metrics.values()) < 5:
            score = min(score, 79)
        if sum(value >= 90 for value in metrics.values()) < 5:
            score = min(score, 89)
        score = max(10, min(95, round(score)))

        tips = [str(v).strip()[:300] for v in (result.get("tips") or []) if str(v).strip()][:5]
        confidence = max(0, min(100, int(result.get("confidence", 0))))

        analysis = FaceAnalysis(
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
    except RuntimeError as exc:
        db.session.rollback()
        app.logger.error("PRIME face AI runtime error: %s", exc)
        return jsonify({"error": f"AI analysis failed: {exc}"}), 502
    except requests.RequestException as exc:
        db.session.rollback()
        app.logger.error("PRIME face AI request error: %s", exc)
        return jsonify({"error": f"AI service temporarily unavailable: {exc}"}), 502
    except Exception as exc:
        db.session.rollback()
        app.logger.exception("PRIME face AI unexpected error")
        return jsonify({"error": f"AI analysis failed: {type(exc).__name__}: {exc}"}), 502
