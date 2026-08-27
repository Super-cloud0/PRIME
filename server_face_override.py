"""Production entrypoint for calibrated PRIME scoring and ELO."""

import db_guard  # noqa: F401,E402
import base64
import math
import os
from concurrent.futures import ThreadPoolExecutor

import requests
from flask import jsonify, request

from server import app
import server_prod

_configured_model = os.environ.get("GEMINI_MODEL", "").strip()
if _configured_model in {"", "gemini-2.5-flash-lite", "gemini-2.5-flash"}:
    _configured_model = "gemini-3.5-flash-lite"
server_prod.GEMINI_MODEL = _configured_model

# NOTE on this prompt (2026-08-26 fix): the previous version told the model
# "60-74 can be clearly above-average" as an example of an ordinary result,
# which gave it a ready-made "safe, polite" answer for any face it couldn't
# confidently judge -- an LLM asked to rate appearance strongly prefers not
# to give a below-average score, so it defaulted almost every metric into
# that exact band. Since the final score is a weighted geometric mean of the
# six metrics (see _strict_trend_score below), every metric landing near
# 60-70 meant nearly every photo landed in the same MTN tier regardless of
# the actual photo. This rewrite removes that anchor, states explicitly that
# 45-55 is the honest, unremarkable middle most photos should land in, and
# tells the model that defaulting upward "to be nice" is a failure of the
# tool's purpose, not a kindness.
STRICT_FACE_PROMPT = """You are the PRIME visual presentation evaluator, scoring against the FULL general population -- not against the population of people who send photos to a rating app (which skews the comparison set).
Give a STRICT, RATIONAL and EVIDENCE-BASED 0-100 evaluation of ONLY visible, non-sensitive presentation characteristics. The goal is honest calibration, not kindness and not artificial harshness.
Do not identify the person. Do not infer or score age, race, ethnicity, religion, health, disability, sexual orientation, or any other sensitive trait. Do not diagnose, speculate about medical/genetic conditions, or sexualize. Evaluate only visible presentation characteristics.

CALIBRATION -- read carefully, this is where evaluators most often go wrong:
Score each metric (symmetry, proportion, grooming, hair, skin_appearance, presentation) independently, imagining it plotted against the entire general population for that visible characteristic.
- 45-55 = genuinely typical/average. Most people and most ordinary, unremarkable photos SHOULD land here. This is the honest middle of a bell curve, not a punishment.
- 56-65 = mildly above average: a bit better than most, not exceptional.
- 66-80 = clearly above average: stands out.
- 81-100 = rare, roughly top few percent.
- The same bands apply symmetrically below 45 for genuinely below-average characteristics.
Do NOT default to 60-74 as a "safe" answer when a photo is ordinary or hard to judge -- if a metric genuinely looks average, score it 45-55, not 60+. Inflating an ordinary photo into "above average" to avoid sounding unkind defeats the entire purpose of this tool; it is a failure of the task, not politeness.
Only score a metric above 65 if you can point to specific visible evidence for it (concrete proportions, specific grooming details, etc.) -- never as a generic polite default.
Do not invent weaknesses either -- if something is genuinely above average, say so with an equally high score. The goal is an accurate spread across the population, in both directions.
Photo quality affects presentation primarily. Score each metric independently before writing the overall summary.
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
    # Exponent raised from 1.03 -> 1.18: with the old prompt every metric
    # already clustered near 60-70 (delta ~10-20), so amplifying delta barely
    # mattered -- the prompt fix above is the real fix. This is kept as a
    # secondary safety margin so the tiers stay well-spread even if the model
    # still hedges toward the middle on some photos.
    calibrated = 50.0 + math.copysign(abs(delta) ** 1.18, delta)
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


# Manual two-photo comparison ("face battle"). Unlike /api/elo/match-v2 this
# is NOT matchmaking and does not touch ELO or the leaderboard -- the caller
# supplies both photos directly (e.g. themselves vs a friend, or two public
# figures for content), gets both calibrated scores back plus a winner, and
# nothing is persisted. Runs both Gemini calls concurrently so the request
# doesn't take 2x as long as a single analysis.
_compare_pool = ThreadPoolExecutor(max_workers=4)


def _analyze_one_for_compare(raw: bytes, mime: str) -> dict:
    raw_result = server_prod.gemini_json("", base64.b64encode(raw).decode("ascii"), mime)
    metrics = {
        key: max(0, min(100, int(value)))
        for key, value in (raw_result.get("metrics") or {}).items()
        if isinstance(value, (int, float))
    }
    score = _strict_trend_score(metrics)
    tier = _trend_tier(score)
    return {
        "score": score,
        "tier": tier,
        "type": tier,
        "metrics": metrics,
        "summary": str(raw_result.get("summary", ""))[:2000],
        "confidence": max(0, min(100, int(raw_result.get("confidence", 0)))),
    }


def _decode_compare_photo(data: dict, key: str):
    entry = data.get(key) if isinstance(data.get(key), dict) else {}
    image_b64 = entry.get("image")
    if not image_b64 or not isinstance(image_b64, str):
        return None, (jsonify({"error": f"photo '{key}' is required"}), 400)
    try:
        raw = base64.b64decode(image_b64, validate=True)
    except Exception:
        return None, (jsonify({"error": f"photo '{key}' is invalid"}), 400)
    if len(raw) > 8 * 1024 * 1024:
        return None, (jsonify({"error": f"photo '{key}' is too large"}), 413)
    return (raw, entry.get("mime", "image/jpeg")), None


@app.post("/api/face/compare")
@server_prod.auth_required
@server_prod.limiter.limit("5 per minute")
def face_compare(user):
    data = request.get_json(silent=True) or {}
    photo_a, error_a = _decode_compare_photo(data, "a")
    if error_a:
        return error_a
    photo_b, error_b = _decode_compare_photo(data, "b")
    if error_b:
        return error_b

    try:
        future_a = _compare_pool.submit(_analyze_one_for_compare, *photo_a)
        future_b = _compare_pool.submit(_analyze_one_for_compare, *photo_b)
        result_a = future_a.result()
        result_b = future_b.result()
    except requests.RequestException:
        return jsonify({"error": "AI service temporarily unavailable"}), 502
    except Exception:
        app.logger.exception("PRIME face compare failed")
        return jsonify({"error": "AI analysis failed"}), 502

    if result_a["score"] == result_b["score"]:
        winner = "tie"
    else:
        winner = "a" if result_a["score"] > result_b["score"] else "b"

    return jsonify({"a": result_a, "b": result_b, "winner": winner})


# Register the current photo-based ELO implementation. It preserves the
# existing /api/elo/match-v2 route used by the Mini App and adds a practice
# opponent when no real participant is available yet.
import elo_v3  # noqa: E402,F401

# Weekly check-in reminders: Telegram nudges for users whose last face scan
# is going stale, plus the opt-in/status routes and the /api/cron endpoint
# used to trigger a run on demand.
import reminders  # noqa: E402,F401

# Business analytics: registration/activation funnel behind a password-gated
# /admin page, plus the bot-contact tracking event the funnel needs.
import analytics  # noqa: E402,F401

# PRIME Pro subscription paid with Telegram Stars: invoice creation, the
# pre_checkout_query/successful_payment webhook handling, and the soft
# paywall on /api/advice and /api/face/compare.
import payments  # noqa: E402,F401

# Growth tracking: personal referral links (t.me/<bot>?start=ref_<id>),
# recording who opened the bot via one, and counting taps on the share-card
# panel's buttons -- surfaced on the /admin funnel page.
import growth  # noqa: E402,F401

__all__ = ["app"]

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8765")), debug=False)
