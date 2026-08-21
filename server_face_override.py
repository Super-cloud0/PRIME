"""Production entrypoint for Render with strict PRIME trend calibration."""

import base64
import json
import math
import os

import requests
from flask import jsonify

from server import app
import server_prod


# Gemini 2.5 Flash-Lite is unavailable to new users. Keep the production
# default here so Render works even when GEMINI_MODEL is not set.
server_prod.GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite").strip() or "gemini-3.5-flash-lite"


def _strict_gemini_json(prompt: str, image_b64: str | None = None, mime: str = "image/jpeg"):
    """Gemini GenerateContent wrapper compatible with current 3.5 Flash-Lite."""
    if not server_prod.GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is missing in Render Environment")

    parts = [{"text": prompt}]
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


# server_prod.face_ai resolves gemini_json from its module globals, so replacing
# this reference upgrades the existing endpoint without duplicating the endpoint.
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

    # Never let Gemini's own headline score inflate the deterministic score.
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
