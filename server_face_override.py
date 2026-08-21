"""Production entrypoint for calibrated PRIME scoring and ELO."""

import math
import os

import requests
from flask import jsonify

from server import app
import server_prod

_configured_model = os.environ.get("GEMINI_MODEL", "").strip()
if _configured_model in {"", "gemini-2.5-flash-lite", "gemini-2.5-flash"}:
    _configured_model = "gemini-3.5-flash-lite"
server_prod.GEMINI_MODEL = _configured_model

STRICT_FACE_PROMPT = """You are the PRIME visual presentation evaluator.
Give a STRICT, RATIONAL and EVIDENCE-BASED 0-100 evaluation of ONLY visible, non-sensitive presentation characteristics. The goal is honest calibration, not kindness and not artificial harshness.
Do not identify the person. Do not infer or score age, race, ethnicity, religion, health, disability, sexual orientation, or any other sensitive trait. Do not diagnose, speculate about medical/genetic conditions, or sexualize. Evaluate only visible presentation characteristics.
REFERENCE SCALE: 0-29 SUB 3; 30-44 SUB 5; 45-59 LTN; 60-74 MTN; 75-79 HTN; 80-94 CHAD; 95-100 TRUE ADAM.
Use the full 0-100 range naturally. Never choose 50 merely because a photo is ordinary and never choose a low score merely to appear strict. 50 is the actual midpoint. Clearly above-average dimensions can be 60-74; genuinely strong ones can be 75-89; exceptional ones can be 90+. Do not cluster every metric around 50. Do not invent weaknesses. Photo quality affects presentation primarily. Score each metric independently before the overall result.
Metrics: symmetry, proportion, grooming, hair, skin_appearance, presentation.
Return ONLY valid JSON with score, type, summary, metrics, tips, confidence. All numeric fields are integers 0-100.
"""


def _strict_gemini_json(prompt: str, image_b64: str | None = None, mime: str = "image/jpeg"):
    if not server_prod.GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is missing in Render Environment")
    parts = [{"text": STRICT_FACE_PROMPT if image_b64 else prompt}]
    if image_b64:
        parts.append({"inline_data": {"mime_type": mime, "data": image_b64}})
    payload = {"contents": [{"parts": parts}], "generationConfig": {"responseMimeType": "application/json"}}
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{server_prod.GEMINI_MODEL}:generateContent"
    response = requests.post(url, params={"key": server_prod.GEMINI_API_KEY}, json=payload, timeout=45)
    response.raise_for_status()
    text = "".join(part.get("text", "") for candidate in response.json().get("candidates", []) for part in candidate.get("content", {}).get("parts", []))
    return server_prod.extract_json(text)

server_prod.gemini_json = _strict_gemini_json


def _trend_tier(score: int) -> str:
    score = max(0, min(100, int(score)))
    if score <= 29: return "SUB 3"
    if score <= 44: return "SUB 5"
    if score <= 59: return "LTN"
    if score <= 74: return "MTN"
    if score <= 79: return "HTN"
    if score <= 94: return "CHAD"
    return "TRUE ADAM"


def _strict_trend_score(metrics: dict, model_score=None) -> int:
    keys = ["symmetry", "proportion", "grooming", "hair", "skin_appearance", "presentation"]
    weights = [1.20, 1.35, 0.95, 0.90, 0.80, 0.80]
    values = []
    for key in keys:
        try: value = int(metrics.get(key, 50))
        except (TypeError, ValueError): value = 50
        values.append(max(0, min(100, value)))
    geometric = math.exp(sum(w * math.log(max(1.0, v)) for v, w in zip(values, weights)) / sum(weights))
    delta = geometric - 50.0
    calibrated = 50.0 + math.copysign(abs(delta) ** 1.03, delta)
    weak_penalty = sum(max(0, 40 - value) * 0.12 for value in values)
    very_weak_penalty = sum(1.5 for value in values if value < 25)
    return max(0, min(100, round(calibrated - weak_penalty - very_weak_penalty)))

_original_face_ai = app.view_functions.get("face_ai")


def _face_ai_trend():
    response = _original_face_ai()
    try:
        payload = response.get_json(silent=True) if hasattr(response, "get_json") else None
        if not isinstance(payload, dict) or "analysis_id" not in payload:
            return response
        metrics = payload.get("metrics") if isinstance(payload.get("metrics"), dict) else {}
        score = _strict_trend_score(metrics, payload.get("score"))
        tier = _trend_tier(score)
        analysis = server_prod.FaceAnalysis.query.get(payload["analysis_id"])
        if analysis is not None:
            analysis.score = score
            analysis.analysis_type = tier
            user = server_prod.User.query.get(analysis.user_id)
            if user is not None:
                user.prime_score = score
            server_prod.db.session.commit()
        payload["score"] = score
        payload["type"] = tier
        payload["tier"] = tier
        return jsonify(payload)
    except Exception:
        server_prod.db.session.rollback()
        app.logger.exception("PRIME score calibration failed; returning original result")
        return response

if _original_face_ai is not None:
    app.view_functions["face_ai"] = _face_ai_trend

# Register the current photo-based ELO implementation. It preserves the
# existing /api/elo/match-v2 route used by the Mini App and adds a practice
# opponent when no real participant is available yet.
import elo_v3  # noqa: E402,F401

__all__ = ["app"]

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8765")), debug=False)
