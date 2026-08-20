from __future__ import annotations

import base64
import json
import os
import requests
import uuid

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
            "temperature": 0.1,
            "maxOutputTokens": 1600,
            "responseMimeType": "application/json",
        },
    }

    configured = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash").strip()
    models = []
    for model in (configured, "gemini-2.5-flash", "gemini-2.5-flash-lite"):
        if model and model not in models:
            models.append(model)

    last_error = "unknown Gemini error"
    for model in models:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        try:
            response = requests.post(
                url,
                headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
                json=payload,
                timeout=60,
            )
            if not response.ok:
                try:
                    error = response.json().get("error", {})
                    last_error = f"Gemini {response.status_code}: {error.get('message', response.text[:300])}"
                except Exception:
                    last_error = f"Gemini {response.status_code}: {response.text[:300]}"
                if response.status_code in (400, 404):
                    continue
                raise RuntimeError(last_error)

            body = response.json()
            text = "".join(
                part.get("text", "")
                for candidate in body.get("candidates", [])
                for part in candidate.get("content", {}).get("parts", [])
                if isinstance(part, dict)
            )
            if text.strip():
                return extract_json(text)
            last_error = "Gemini returned no text"
        except requests.RequestException as exc:
            last_error = f"Gemini request failed: {type(exc).__name__}: {exc}"

    raise RuntimeError(last_error)


@app.post("/api/face-ai", endpoint="face_ai_override")
@auth_required
def face_ai_override(user):
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

    mime = str(data.get("mime") or "image/jpeg").lower().split(";")[0].strip()
    if mime not in {"image/jpeg", "image/png", "image/webp"}:
        mime = "image/jpeg"

    prompt = """You are PRIME's STRICT visual presentation evaluator.
Analyze ONLY visible, non-sensitive appearance and presentation characteristics in THIS photo.
Do not identify the person. Do not infer or mention age, race, ethnicity, religion, health, disability, sexual orientation, gender identity, or other sensitive traits. Do not diagnose. Do not sexualize.
Be genuinely strict and calibrated. Do not give a high score merely because of flattering lighting. 90+ is rare. Most ordinary good photos should land around 55-80.
Evaluate only visible evidence: grooming, hairstyle, skin appearance, visually observable symmetry, facial proportion/harmony, lighting, angle, image quality, and overall presentation. Do not invent flaws.
Calibration: 0-39 major visible problems; 40-54 weak; 55-64 below/around average; 65-74 solid; 75-84 clearly strong; 85-89 excellent and uncommon; 90-100 exceptional and very uncommon.
Return ONLY valid JSON with exactly these keys: score, type, summary, metrics, tips, confidence.
metrics MUST contain exactly: symmetry, proportion, grooming, hair, skin_appearance, presentation. All numeric values are integers 0-100.
type must be one of SUB 5, MTN, HTN, LTN, CHAD.
tips must contain 3-5 practical, safe, non-medical suggestions tied to visible weaknesses.
confidence is confidence in visible evidence, 0-100.
"""

    try:
        result = gemini_json_strict(prompt, base64.b64encode(raw).decode("ascii"), mime)
        score = max(0, min(100, int(result.get("score", 0))))
        required = ["symmetry", "proportion", "grooming", "hair", "skin_appearance", "presentation"]
        source_metrics = result.get("metrics") if isinstance(result.get("metrics"), dict) else {}
        metrics = {}
        for key in required:
            try:
                metrics[key] = max(0, min(100, int(source_metrics.get(key, 0))))
            except (TypeError, ValueError):
                metrics[key] = 0
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
        app.logger.error("PRIME face AI runtime error: %s", exc)
        return jsonify({"error": f"AI analysis failed: {exc}"}), 502
    except requests.RequestException as exc:
        app.logger.error("PRIME face AI request error: %s", exc)
        return jsonify({"error": "AI service temporarily unavailable"}), 502
    except Exception as exc:
        db.session.rollback()
        app.logger.exception("PRIME face AI unexpected error")
        return jsonify({"error": f"AI analysis failed: {type(exc).__name__}: {exc}"}), 502
