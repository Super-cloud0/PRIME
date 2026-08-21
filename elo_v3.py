from __future__ import annotations

import base64
import html
import random
import uuid

import requests
from flask import jsonify, request

import server_prod


db = server_prod.db
app = server_prod.app
User = server_prod.User


class EloParticipantV3(db.Model):
    __tablename__ = "elo_participant_v3"
    id = db.Column(db.String(36), primary_key=True)
    user_id = db.Column(db.String(36), db.ForeignKey("user.id", ondelete="CASCADE"), unique=True, nullable=False, index=True)
    enabled = db.Column(db.Boolean, nullable=False, default=False, index=True)
    photo_data = db.Column(db.LargeBinary, nullable=True)
    photo_mime = db.Column(db.String(50), nullable=False, default="image/jpeg")
    elo = db.Column(db.Integer, nullable=False, default=1000)
    wins = db.Column(db.Integer, nullable=False, default=0)
    losses = db.Column(db.Integer, nullable=False, default=0)
    games = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, server_default=db.func.now())


def _participant(user):
    row = EloParticipantV3.query.filter_by(user_id=user.id).first()
    if row is None:
        row = EloParticipantV3(id=str(uuid.uuid4()), user_id=user.id, elo=user.elo or 1000)
        db.session.add(row)
        db.session.flush()
    return row


def _tier(score):
    n = max(0, min(100, int(score)))
    if n <= 29: return "SUB 3"
    if n <= 44: return "SUB 5"
    if n <= 59: return "LTN"
    if n <= 74: return "MTN"
    if n <= 79: return "HTN"
    if n <= 94: return "CHAD"
    return "TRUE ADAM"


def _expected(a, b):
    return 1.0 / (1.0 + 10 ** ((b - a) / 400.0))


def _bot_avatar(name: str, elo: int) -> tuple[bytes, str]:
    label = html.escape(name)
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="640" height="640" viewBox="0 0 640 640">
<defs><linearGradient id="g" x1="0" x2="1" y1="0" y2="1"><stop stop-color="#0b0b0b"/><stop offset="1" stop-color="#252525"/></linearGradient></defs>
<rect width="640" height="640" rx="48" fill="url(#g)"/><circle cx="320" cy="250" r="112" fill="#d7d7d7"/><path d="M160 570c16-118 82-176 160-176s144 58 160 176" fill="#9d9d9d"/><text x="320" y="540" fill="#fff" text-anchor="middle" font-family="Arial,sans-serif" font-size="34" font-weight="700">{label}</text><text x="320" y="585" fill="#aaa" text-anchor="middle" font-family="Arial,sans-serif" font-size="28">{elo} ELO</text></svg>'''.encode()
    return svg, "image/svg+xml"


def _compare(photo_a, mime_a, photo_b, mime_b):
    key = server_prod.GEMINI_API_KEY
    if not key:
        raise RuntimeError("GEMINI_API_KEY is missing in Render Environment")
    model = getattr(server_prod, "GEMINI_MODEL", "gemini-3.5-flash-lite") or "gemini-3.5-flash-lite"
    prompt = """You are PRIME's pairwise ELO judge. Compare TWO photos only on visible, non-sensitive presentation quality. Do not identify either person, infer sensitive traits, diagnose, or sexualize. Judge visible grooming, hair, visible skin presentation, symmetry/proportion when clear, and overall presentation. Lighting/angle should primarily affect presentation and confidence. Return TIE when evidence is genuinely too close. Return ONLY JSON: {\"winner\":\"A\"|\"B\"|\"TIE\",\"confidence\":0-100,\"reason\":\"brief evidence-based reason\"}."""
    payload = {"contents": [{"parts": [
        {"text": prompt},
        {"inline_data": {"mime_type": mime_a, "data": base64.b64encode(photo_a).decode("ascii")}},
        {"inline_data": {"mime_type": mime_b, "data": base64.b64encode(photo_b).decode("ascii")}},
    ]}], "generationConfig": {"responseMimeType": "application/json"}}
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    r = requests.post(url, params={"key": key}, json=payload, timeout=60)
    if not r.ok:
        try:
            detail = r.json().get("error", {}).get("message", r.text[:800])
        except Exception:
            detail = r.text[:800]
        raise RuntimeError(f"Gemini compare HTTP {r.status_code}: {detail}")
    text = "".join(part.get("text", "") for c in r.json().get("candidates", []) for part in c.get("content", {}).get("parts", []) if isinstance(part, dict)).strip()
    result = server_prod.extract_json(text)
    winner = str(result.get("winner", "TIE")).upper()
    if winner not in {"A", "B", "TIE"}: winner = "TIE"
    try:
        confidence = max(0, min(100, int(result.get("confidence", 0))))
    except (TypeError, ValueError):
        confidence = 0
    return winner, confidence, str(result.get("reason", ""))[:500]


@app.get("/api/elo/status-v3")
@server_prod.auth_required
def elo_status_v3(user):
    row = _participant(user)
    db.session.commit()
    return jsonify({"enabled": row.enabled, "has_photo": bool(row.photo_data), "elo": row.elo, "games": row.games, "wins": row.wins, "losses": row.losses})


@app.post("/api/elo/opt-in-v3")
@server_prod.auth_required
def elo_opt_in_v3(user):
    enabled = bool((request.get_json(silent=True) or {}).get("enabled"))
    row = _participant(user)
    if enabled and not row.photo_data:
        return jsonify({"error": "Сначала сделай анализ фото — оно станет твоим ELO-фото."}), 400
    row.enabled = enabled
    db.session.commit()
    return jsonify({"enabled": row.enabled, "has_photo": bool(row.photo_data), "elo": row.elo})


@app.post("/api/elo/photo-v3")
@server_prod.auth_required
def elo_photo_v3(user):
    data = request.get_json(silent=True) or {}
    image = data.get("image")
    if not isinstance(image, str) or not image:
        return jsonify({"error": "image is required"}), 400
    try:
        raw = base64.b64decode(image, validate=True)
    except Exception:
        return jsonify({"error": "invalid image"}), 400
    if len(raw) > 6 * 1024 * 1024:
        return jsonify({"error": "image too large"}), 413
    mime = str(data.get("mime") or "image/jpeg").split(";")[0].lower()
    if mime not in {"image/jpeg", "image/png", "image/webp"}:
        mime = "image/jpeg"
    row = _participant(user)
    row.photo_data, row.photo_mime = raw, mime
    db.session.commit()
    return jsonify({"ok": True, "enabled": row.enabled})


@app.post("/api/elo/match-v3")
@server_prod.auth_required
def elo_match_v3(user):
    me = _participant(user)
    if not me.enabled or not me.photo_data:
        return jsonify({"error": "Включи участие в ELO и сначала загрузи фото."}), 400

    candidates = EloParticipantV3.query.filter(EloParticipantV3.enabled.is_(True), EloParticipantV3.photo_data.is_not(None), EloParticipantV3.user_id != user.id).limit(100).all()

    if not candidates:
        bot_elo = random.choice([980, 1100, 1250, 1450, 1650])
        bot_name = f"PRIME TEST {bot_elo}"
        bot_photo, bot_mime = _bot_avatar(bot_name, bot_elo)
        before_a = me.elo
        expected_a = _expected(before_a, bot_elo)
        my_strength = (user.prime_score * 5.0) + random.gauss(0, 8)
        bot_strength = ({980: 38, 1100: 52, 1250: 64, 1450: 76, 1650: 88}[bot_elo] * 5.0) + random.gauss(0, 8)
        winner = "A" if my_strength >= bot_strength else "B"
        result_a = 1.0 if winner == "A" else 0.0
        delta_a = round(32 * (result_a - expected_a))
        me.elo = max(400, before_a + delta_a)
        me.games += 1
        me.wins += int(winner == "A")
        me.losses += int(winner == "B")
        user.elo, user.wins, user.losses, user.games = me.elo, me.wins, me.losses, me.games
        db.session.commit()
        return jsonify({
            "result": winner,
            "confidence": 72,
            "reason": "Practice opponent: real ELO participants are not available yet.",
            "is_bot": True,
            "opponent": {"id": f"bot_{bot_elo}", "name": bot_name, "elo_before": bot_elo, "elo_after": bot_elo, "mime": bot_mime, "photo": base64.b64encode(bot_photo).decode("ascii")},
            "you": {"id": user.id, "name": user.name, "elo_before": before_a, "elo_after": me.elo, "delta": delta_a, "mime": "image/jpeg", "photo": base64.b64encode(me.photo_data).decode("ascii")},
            "tier": _tier(user.prime_score),
        })

    ranked = sorted(candidates, key=lambda row: abs(row.elo - me.elo))
    opponent = random.choice(ranked[:min(5, len(ranked))])
    other = db.session.get(User, opponent.user_id)
    if not other:
        return jsonify({"error": "opponent unavailable"}), 404

    try:
        winner, confidence, reason = _compare(me.photo_data, me.photo_mime, opponent.photo_data, opponent.photo_mime)
    except Exception as exc:
        db.session.rollback()
        return jsonify({"error": f"ELO comparison failed: {type(exc).__name__}: {exc}"}), 502

    before_a, before_b = me.elo, opponent.elo
    expected_a = _expected(before_a, before_b)
    result_a = 0.5 if winner == "TIE" else (1.0 if winner == "A" else 0.0)
    delta_a = round(32 * (result_a - expected_a))
    delta_b = -delta_a
    me.elo, opponent.elo = max(400, before_a + delta_a), max(400, before_b + delta_b)
    me.games += 1
    opponent.games += 1
    if winner == "A": me.wins += 1; opponent.losses += 1
    elif winner == "B": me.losses += 1; opponent.wins += 1
    user.elo, user.wins, user.losses, user.games = me.elo, me.wins, me.losses, me.games
    other.elo, other.wins, other.losses, other.games = opponent.elo, opponent.wins, opponent.losses, opponent.games
    db.session.commit()
    return jsonify({
        "result": winner,
        "confidence": confidence,
        "reason": reason,
        "is_bot": False,
        "opponent": {"id": other.id, "name": other.name, "elo_before": before_b, "elo_after": opponent.elo, "mime": opponent.photo_mime, "photo": base64.b64encode(opponent.photo_data).decode("ascii")},
        "you": {"id": user.id, "name": user.name, "elo_before": before_a, "elo_after": me.elo, "delta": delta_a, "mime": me.photo_mime, "photo": base64.b64encode(me.photo_data).decode("ascii")},
        "tier": _tier(user.prime_score),
    })


# Explicit routes avoid dependence on legacy endpoint names during deployment.
app.add_url_rule("/api/elo/status", endpoint="elo_status_v3_compat", view_func=elo_status_v3, methods=["GET"])
app.add_url_rule("/api/elo/opt-in", endpoint="elo_opt_in_v3_compat", view_func=elo_opt_in_v3, methods=["POST"])
app.add_url_rule("/api/elo/photo", endpoint="elo_photo_v3_compat", view_func=elo_photo_v3, methods=["POST"])
app.add_url_rule("/api/elo/match-v2", endpoint="elo_match_v3_compat", view_func=elo_match_v3, methods=["POST"])
app.add_url_rule("/api/elo/status-v3", endpoint="elo_status_v3_route", view_func=elo_status_v3, methods=["GET"])
app.add_url_rule("/api/elo/opt-in-v3", endpoint="elo_opt_in_v3_route", view_func=elo_opt_in_v3, methods=["POST"])
app.add_url_rule("/api/elo/photo-v3", endpoint="elo_photo_v3_route", view_func=elo_photo_v3, methods=["POST"])

with app.app_context():
    db.create_all()
