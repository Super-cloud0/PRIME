"""Consent-based PRIME ELO matchmaking.

ELO participants explicitly opt in. Their latest analyzed photo is stored for
pairwise presentation comparisons. No photo is exposed outside an ELO match.
"""
from __future__ import annotations

import base64
import json
import math
import os
import uuid

import requests
from flask import jsonify, request
from sqlalchemy import desc

import server_prod


db = server_prod.db
app = server_prod.app
User = server_prod.User


class EloParticipant(db.Model):
    __tablename__ = "elo_participant"
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
    row = EloParticipant.query.filter_by(user_id=user.id).first()
    if row is None:
        row = EloParticipant(id=str(uuid.uuid4()), user_id=user.id, elo=user.elo or 1000)
        db.session.add(row)
        db.session.flush()
    return row


def _tier(score: int) -> str:
    n = max(0, min(100, int(score)))
    if n <= 29: return "SUB 3"
    if n <= 44: return "SUB 5"
    if n <= 59: return "LTN"
    if n <= 74: return "MTN"
    if n <= 84: return "HTN"
    if n <= 94: return "CHAD"
    return "TRUE ADAM"


def _expected(a: int, b: int) -> float:
    return 1.0 / (1.0 + 10 ** ((b - a) / 400.0))


def _compare_with_gemini(photo_a: bytes, mime_a: str, photo_b: bytes, mime_b: str) -> dict:
    key = server_prod.GEMINI_API_KEY
    if not key:
        raise RuntimeError("GEMINI_API_KEY is missing in Render Environment")
    model = getattr(server_prod, "GEMINI_MODEL", "gemini-3.5-flash-lite")
    prompt = """Compare these TWO photos only on visible, non-sensitive visual presentation quality for a game. Do not identify either person and do not infer age, race, ethnicity, health, disability, religion, sexual orientation or any other sensitive trait. Do not sexualize. Judge only grooming, hair presentation, visible skin presentation, symmetry/proportion when clearly visible, and overall photo presentation. Return ONLY JSON: {\"winner\":\"A\" or \"B\" or \"TIE\",\"confidence\":0-100,\"reason\":string}. Make the comparison evidence-based and do not force a winner when the evidence is genuinely too close."""
    payload = {"contents": [{"parts": [
        {"text": prompt},
        {"inline_data": {"mime_type": mime_a, "data": base64.b64encode(photo_a).decode("ascii")}},
        {"inline_data": {"mime_type": mime_b, "data": base64.b64encode(photo_b).decode("ascii")}},
    ]}], "generationConfig": {"responseMimeType": "application/json", "temperature": 0}}
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    r = requests.post(url, params={"key": key}, json=payload, timeout=60)
    r.raise_for_status()
    text = "".join(part.get("text", "") for c in r.json().get("candidates", []) for part in c.get("content", {}).get("parts", []))
    return server_prod.extract_json(text)


@app.get("/api/elo/status")
@server_prod.auth_required
def elo_status(user):
    row = _participant(user)
    db.session.commit()
    return jsonify({"enabled": row.enabled, "has_photo": bool(row.photo_data), "elo": row.elo, "games": row.games, "wins": row.wins, "losses": row.losses})


@app.post("/api/elo/opt-in")
@server_prod.auth_required
def elo_opt_in(user):
    data = request.get_json(silent=True) or {}
    enabled = bool(data.get("enabled"))
    row = _participant(user)
    if enabled and not row.photo_data:
        return jsonify({"error": "Сначала сделай анализ фото — оно станет твоим ELO-фото."}), 400
    row.enabled = enabled
    db.session.commit()
    return jsonify({"enabled": row.enabled, "has_photo": bool(row.photo_data), "elo": row.elo})


@app.post("/api/elo/photo")
@server_prod.auth_required
def elo_photo(user):
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
    row.photo_data = raw
    row.photo_mime = mime
    db.session.commit()
    return jsonify({"ok": True, "enabled": row.enabled})


@app.post("/api/elo/match-v2")
@server_prod.auth_required
def elo_match_v2(user):
    me = _participant(user)
    if not me.enabled or not me.photo_data:
        return jsonify({"error": "Включи участие в ELO и сначала загрузи фото."}), 400

    candidates = EloParticipant.query.filter(EloParticipant.enabled.is_(True), EloParticipant.photo_data.is_not(None), EloParticipant.user_id != user.id).order_by(desc(EloParticipant.games)).limit(50).all()
    if not candidates:
        return jsonify({"error": "Пока нет другого участника ELO. Пригласи друга и включите ELO."}), 404

    # Prefer opponents within a reasonable rating window; widen when necessary.
    ranked = sorted(candidates, key=lambda x: abs(x.elo - me.elo))
    opponent = ranked[min(len(ranked) - 1, 4)]
    other = db.session.get(User, opponent.user_id)
    if not other:
        return jsonify({"error": "opponent unavailable"}), 404

    try:
        comparison = _compare_with_gemini(me.photo_data, me.photo_mime, opponent.photo_data, opponent.photo_mime)
        winner = str(comparison.get("winner", "TIE")).upper()
        confidence = max(0, min(100, int(comparison.get("confidence", 0))))
        if winner not in {"A", "B", "TIE"}:
            winner = "TIE"
    except Exception as exc:
        db.session.rollback()
        return jsonify({"error": f"ELO comparison failed: {type(exc).__name__}: {exc}"}), 502

    before_a, before_b = me.elo, opponent.elo
    expected_a = _expected(before_a, before_b)
    result_a = 0.5 if winner == "TIE" else (1.0 if winner == "A" else 0.0)
    k = 32
    delta_a = round(k * (result_a - expected_a))
    delta_b = -delta_a

    me.elo = max(400, before_a + delta_a)
    opponent.elo = max(400, before_b + delta_b)
    me.games += 1
    opponent.games += 1
    if winner == "A":
        me.wins += 1; opponent.losses += 1
    elif winner == "B":
        me.losses += 1; opponent.wins += 1

    user.elo = me.elo; user.wins = me.wins; user.losses = me.losses; user.games = me.games
    other.elo = opponent.elo; other.wins = opponent.wins; other.losses = opponent.losses; other.games = opponent.games
    db.session.commit()

    return jsonify({
        "result": winner,
        "confidence": confidence,
        "reason": str(comparison.get("reason", ""))[:500],
        "opponent": {"id": other.id, "name": other.name, "elo_before": before_b, "elo_after": opponent.elo},
        "you": {"id": user.id, "name": user.name, "elo_before": before_a, "elo_after": me.elo, "delta": delta_a},
        "tier": _tier(user.prime_score),
    })


# Create the table automatically for the first production deployment.
with app.app_context():
    db.create_all()
