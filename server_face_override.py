"""Production entrypoint for Render with strict PRIME trend calibration."""

import math

from flask import jsonify

from server import app
import server_prod


def _trend_tier(score: int) -> str:
    score = max(1, min(100, int(score)))
    if score <= 24:
        return "SUB 3"
    if score <= 39:
        return "SUB 5"
    if score <= 54:
        return "LTN"
    if score <= 69:
        return "MTN"
    if score <= 79:
        return "HTN"
    if score <= 94:
        return "CHAD"
    return "TRUE ADAM"


def _strict_trend_score(metrics: dict, model_score) -> int:
    keys = ["symmetry", "proportion", "grooming", "hair", "skin_appearance", "presentation"]
    values = []
    for key in keys:
        try:
            values.append(max(0, min(100, int(metrics.get(key, 50)))))
        except (TypeError, ValueError):
            values.append(50)

    # Weighted geometric mean: several weak dimensions cannot be hidden by one
    # strong dimension. This is intentionally much harsher than a plain average.
    weights = [1.15, 1.30, 0.95, 0.90, 0.85, 0.85]
    weight_sum = sum(weights)
    log_sum = sum(w * math.log(max(1.0, v)) for v, w in zip(values, weights))
    base = math.exp(log_sum / weight_sum)

    weak_penalty = sum(max(0, 50 - v) * 0.20 for v in values)
    very_weak_penalty = sum(4 for v in values if v < 35)
    score = round(base - weak_penalty - very_weak_penalty)

    # Gemini's headline number may never inflate the calibrated score.
    try:
        model_score = max(1, min(100, int(model_score)))
        score = min(score, model_score + 2)
    except (TypeError, ValueError):
        pass

    return max(1, min(100, score))


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
    import os
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8765")))
