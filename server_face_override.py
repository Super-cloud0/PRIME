"""Production entrypoint for Render with strict PRIME trend calibration."""

import math
import os

import requests
from flask import jsonify

from server import app
import server_prod


# Gemini 2.5 Flash-Lite is unavailable to new users. If Render still contains
# the old model variable, transparently migrate it instead of breaking deploys.
_configured_model = os.environ.get("GEMINI_MODEL", "").strip()
if _configured_model in {"", "gemini-2.5-flash-lite", "gemini-2.5-flash"}:
    _configured_model = "gemini-3.5-flash-lite"
server_prod.GEMINI_MODEL = _configured_model


STRICT_FACE_PROMPT = """
You are the STRICT PRIME visual presentation evaluator.

This is an entertainment/self-improvement scoring system from 0 to 100. Do NOT
be kind, encouraging, flattering, or average by default. Do NOT give 50 simply
because the person looks ordinary. Use the FULL scale. A score around 50 must
mean genuinely above the midpoint of the reference scale, not "normal".

Evaluate ONLY visible, non-sensitive presentation characteristics in the image:
symmetry, facial proportions, grooming, hair presentation, visible skin
appearance, and photo/presentation quality. Do not identify the person and do
not infer age, race, ethnicity, religion, health, disability, sexual
orientation, or other sensitive traits. Do not diagnose or sexualize.

STRICT CALIBRATION:
- 0-29: SUB 3 — clearly far below the reference midpoint.
- 30-44: SUB 5 — below the reference midpoint.
- 45-59: LTN — lower-than-average / ordinary presentation.
- 60-74: MTN — solidly above the midpoint.
- 75-84: HTN — clearly strong presentation.
- 85-94: CHAD — exceptional presentation.
- 95-100: TRUE ADAM — extremely exceptional and rare.

Do not use the tier labels to decide the score. First score each metric,
then provide the overall score. Do not inflate a weak metric because another
metric is strong. Visible weaknesses must materially lower the corresponding
metric. If the photo quality is poor, lower presentation/confidence rather than
inventing positive details.

Metric anchors:
0-19 = severe visible weakness,
20-34 = clearly weak,
35-49 = below average,
50-64 = average,
65-74 = above average,
75-84 = strong,
85-94 = exceptional,
95-100 = extremely rare.

Return ONLY valid JSON with exactly these keys:
score, type, summary, metrics, tips, confidence.
metrics must contain exactly: symmetry, proportion, grooming, hair,
skin_appearance, presentation.
All numeric fields must be integers from 0 to 100.
If there is no clear face, return low confidence and do not invent a score.
"""


def _strict_gemini_json(prompt: str, image_b64: str | None = None, mime: str = "image/jpeg"):
    """Gemini GenerateContent wrapper compatible with current 3.5 Flash-Lite."""
    if not server_prod.GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is missing in Render Environment")

    effective_prompt = STRICT_FACE_PROMPT if image_b64 else prompt
    parts = [{"text": effective_prompt}]
    if image_b64:
        parts.append({"inline_data": {"mime_type": mime, "data": image_b64}})

    # Gemini 3.5 Flash-Lite deprecates sampling controls such as temperature.
    payload = {
        "contents": [{"parts": parts}],
        "generationConfig": {"responseMimeType": "application/json"},
    }
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{server_prod.GEMINI_MODEL}:generateContent"
    response = requests.post(url, params={"key": server_prod.GEMINI_API_KEY}, json=payload, timeout=45)
    response.raise_for_status()
    text = "".join(
        part.get("text", "")
        for candidate in response.json().get("candidates", [])
        for part in candidate.get("content", {}).get("parts", [])
    )
    return server_prod.extract_json(text)


server_prod.gemini_json = _strict_gemini_json


def _trend_tier(score: int) -> str:
    score = max(0, min(100, int(score)))
    if score <= 29:
        return "SUB 3"
    if score <= 44:
        return "SUB 5"
    if score <= 59:
        return "LTN"
    if score <= 74:
        return "MTN"
    if score <= 84:
        return "HTN"
    if score <= 94:
        return "CHAD"
    return "TRUE ADAM"


def _strict_trend_score(metrics: dict, model_score=None) -> int:
    keys = ["symmetry", "proportion", "grooming", "hair", "skin_appearance", "presentation"]
    weights = [1.20, 1.35, 0.95, 0.90, 0.80, 0.80]
    values = []

    for key in keys:
        try:
            value = int(metrics.get(key, 50))
        except (TypeError, ValueError):
            value = 50
        values.append(max(0, min(100, value)))

    # Geometric mean prevents a single strong metric from hiding several weak
    # ones. The power curve intentionally compresses the middle of the scale:
    # 50-ish raw quality does NOT become an automatic 50/100.
    weight_sum = sum(weights)
    log_sum = sum(w * math.log(max(1.0, value)) for value, w in zip(values, weights))
    geometric = math.exp(log_sum / weight_sum)
    calibrated = 100.0 * ((geometric / 100.0) ** 1.45)

    # Extra penalties make weak dimensions matter instead of averaging them away.
    weak_penalty = sum(max(0, 50 - value) * 0.24 for value in values)
    very_weak_penalty = sum(3 for value in values if value < 30)
    score = round(calibrated - weak_penalty - very_weak_penalty)

    # Gemini's headline score is deliberately ignored. The server computes the
    # final score from the six metrics so the model cannot talk itself upward.
    return max(0, min(100, score))


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
        app.logger.exception("Strict PRIME trend score calibration failed; returning original result")
        return response


if _original_face_ai is not None:
    app.view_functions["face_ai"] = _face_ai_trend

__all__ = ["app"]

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8765")))
