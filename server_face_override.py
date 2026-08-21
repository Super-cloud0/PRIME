"""Production entrypoint for Render with calibrated PRIME trend scoring."""

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
You are the PRIME visual presentation evaluator.

Give a strict but rational 0-100 evaluation of ONLY visible, non-sensitive
presentation characteristics. Be honest and evidence-based, but do not punish
a person merely for looking ordinary, and do not force the score downward.
Use the full scale naturally.

Do NOT identify the person and do not infer or score age, race, ethnicity,
religion, health, disability, sexual orientation, or other sensitive traits.
Do not diagnose or sexualize. Evaluate only visible presentation factors.

REFERENCE SCALE:
- 0-29: SUB 3 — clearly very weak visible presentation.
- 30-44: SUB 5 — clearly below average.
- 45-59: LTN — ordinary / lower-than-average presentation.
- 60-74: MTN — clearly above average, solid overall presentation.
- 75-84: HTN — strong presentation across most dimensions.
- 85-94: CHAD — exceptional and uncommon presentation.
- 95-100: TRUE ADAM — extraordinarily exceptional; genuinely rare.

IMPORTANT CALIBRATION:
- 50 is NOT a mandatory default. Give 50 only when the evidence really supports
  the midpoint.
- Do NOT artificially push ordinary photos below 50 just to be "strict".
- A genuinely good-looking / strong presentation can and should score 60-75+.
- MTN must be attainable when the visible evidence supports it.
- 80+ requires clear strength across several dimensions, not one standout trait.
- 90+ is rare and requires exceptional consistency.
- 95+ should be extremely rare.
- Never inflate a weak dimension because another dimension is strong.
- Never lower a dimension simply because the subject is not exceptional.
- Poor lighting or an unusual camera angle should mainly affect presentation and
  confidence, not invent facial weaknesses.

Metric anchors:
0-19 = severe visible weakness,
20-34 = clearly weak,
35-49 = below average,
50-59 = around average,
60-69 = above average,
70-79 = clearly strong,
80-89 = very strong,
90-94 = exceptional,
95-100 = extraordinarily rare.

Score each metric independently first. Then provide the overall score based on
all six metrics. Do not simply copy the overall score from a generic prior.

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
    """Convert six model metrics into a strict-but-rational PRIME score.

    The previous power curve made an average 50/100 set of metrics collapse to
    roughly 36/100. That was too punitive. This version keeps the midpoint
    meaningful, lets genuinely strong presentations reach MTN/HTN, and still
    prevents one excellent metric from hiding several weak ones.
    """
    keys = ["symmetry", "proportion", "grooming", "hair", "skin_appearance", "presentation"]
    weights = [1.20, 1.35, 0.95, 0.90, 0.80, 0.80]
    values = []

    for key in keys:
        try:
            value = int(metrics.get(key, 50))
        except (TypeError, ValueError):
            value = 50
        values.append(max(0, min(100, value)))

    weight_sum = sum(weights)
    log_sum = sum(w * math.log(max(1.0, value)) for value, w in zip(values, weights))
    geometric = math.exp(log_sum / weight_sum)

    # Keep 50 genuinely near the midpoint instead of crushing it into the 30s.
    # A mild curve preserves strictness at the extremes without distorting the
    # middle of the scale.
    delta = geometric - 50.0
    calibrated = 50.0 + math.copysign(abs(delta) ** 1.03, delta)

    # Weak dimensions matter, but only when they are meaningfully weak.
    weak_penalty = sum(max(0, 40 - value) * 0.12 for value in values)
    very_weak_penalty = sum(1.5 for value in values if value < 25)
    score = round(calibrated - weak_penalty - very_weak_penalty)

    # The model headline score is deliberately ignored. The server computes the
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
        app.logger.exception("PRIME score calibration failed; returning original result")
        return response


if _original_face_ai is not None:
    app.view_functions["face_ai"] = _face_ai_trend

__all__ = ["app"]

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8765")))
