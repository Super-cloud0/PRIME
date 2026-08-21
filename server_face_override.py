"""Production entrypoint for Render.

Uses the production Face AI from server.py and applies the TikTok-style PRIME
trend tier calibration to the final 1-100 score.
"""

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


def _strict_trend_score(metrics: dict) -> int:
    keys = ["symmetry", "proportion", "grooming", "hair", "skin_appearance", "presentation"]
    values = []
    for key in keys:
        try:
            values.append(max(0, min(100, int(metrics.get(key, 50)))) )
        except (TypeError, ValueError):
            values.append(50)

    values.sort()
    average = sum(values) / len(values)
    bottom_two = (values[0] + values[1]) / 2
    minimum = values[0]

    # Strict calibration: weak dimensions matter heavily. This prevents a
    # good haircut/lighting from hiding several weak visible dimensions.
    score = (average * 0.50) + (bottom_two * 0.30) + (minimum * 0.20)
    return max(1, min(100, round(score)))


# server.py already registers the authenticated Face AI view. Wrap that exact
# view instead of creating another route, so Render keeps one production path.
_original_face_ai = app.view_functions.get("face_ai")


def _face_ai_trend():
    response = _original_face_ai()
    try:
        payload = response.get_json(silent=True) if hasattr(response, "get_json") else None
        if not isinstance(payload, dict) or "analysis_id" not in payload:
            return response

        metrics = payload.get("metrics") if isinstance(payload.get("metrics"), dict) else {}
        score = _strict_trend_score(metrics)
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
        return jsonify(payload)
    except Exception:
        server_prod.db.session.rollback()
        app.logger.exception("Trend score calibration failed; returning original AI result")
        return response


if _original_face_ai is not None:
    app.view_functions["face_ai"] = _face_ai_trend

__all__ = ["app"]


if __name__ == "__main__":
    import os
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8765")))
