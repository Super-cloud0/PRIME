from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
import uuid
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path

import requests
from flask import Flask, jsonify, request, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import desc, func
from werkzeug.utils import secure_filename

BASE = Path(__file__).resolve().parent
MEDIA_ROOT = Path(os.environ.get("PRIME_MEDIA_ROOT", BASE / "media"))
MEDIA_ROOT.mkdir(parents=True, exist_ok=True)

app = Flask(__name__, static_folder=str(BASE))
app.config.update(
    SQLALCHEMY_DATABASE_URI=os.environ.get("DATABASE_URL", "sqlite:///prime_dev.db"),
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    MAX_CONTENT_LENGTH=10 * 1024 * 1024,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
)
db = SQLAlchemy(app)

JWT_SECRET = os.environ.get("PRIME_JWT_SECRET", "").strip()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
MAX_AUDIO = 25 * 1024 * 1024
ALLOWED_AUDIO = {"mp3", "wav", "ogg", "m4a", "aac", "flac", "webm"}


class User(db.Model):
    id = db.Column(db.String(36), primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=True, index=True)
    password_hash = db.Column(db.String(255), nullable=True)
    name = db.Column(db.String(50), nullable=False, default="PRIME USER")
    elo = db.Column(db.Integer, nullable=False, default=1000)
    prime_score = db.Column(db.Integer, nullable=False, default=50)
    wins = db.Column(db.Integer, nullable=False, default=0)
    losses = db.Column(db.Integer, nullable=False, default=0)
    games = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class FaceAnalysis(db.Model):
    id = db.Column(db.String(36), primary_key=True)
    user_id = db.Column(db.String(36), db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    score = db.Column(db.Integer, nullable=False)
    analysis_type = db.Column(db.String(20), nullable=False)
    summary = db.Column(db.Text, nullable=False, default="")
    metrics_json = db.Column(db.Text, nullable=False, default="{}")
    tips_json = db.Column(db.Text, nullable=False, default="[]")
    confidence = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class EloMatch(db.Model):
    id = db.Column(db.String(36), primary_key=True)
    winner_id = db.Column(db.String(36), db.ForeignKey("user.id", ondelete="SET NULL"))
    loser_id = db.Column(db.String(36), db.ForeignKey("user.id", ondelete="SET NULL"))
    winner_elo_before = db.Column(db.Integer, nullable=False)
    loser_elo_before = db.Column(db.Integer, nullable=False)
    winner_delta = db.Column(db.Integer, nullable=False)
    loser_delta = db.Column(db.Integer, nullable=False)
    opponent_name = db.Column(db.String(50), nullable=False)
    is_bot = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class MusicTrack(db.Model):
    id = db.Column(db.String(36), primary_key=True)
    user_id = db.Column(db.String(36), db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    original_name = db.Column(db.String(255), nullable=False)
    stored_name = db.Column(db.String(100), nullable=False, unique=True)
    mime_type = db.Column(db.String(100), nullable=False)
    size = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


def password_hash(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return f"scrypt${base64.urlsafe_b64encode(salt).decode()}${base64.urlsafe_b64encode(digest).decode()}"


def password_ok(password: str, encoded: str) -> bool:
    try:
        _, salt_b64, digest_b64 = encoded.split("$", 2)
        salt = base64.urlsafe_b64decode(salt_b64.encode())
        expected = base64.urlsafe_b64decode(digest_b64.encode())
        actual = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


def jwt_encode(user_id: str) -> str:
    if not JWT_SECRET:
        raise RuntimeError("PRIME_JWT_SECRET is not configured")
    header = base64.urlsafe_b64encode(b'{"alg":"HS256","typ":"JWT"}').rstrip(b"=").decode()
    payload = base64.urlsafe_b64encode(json.dumps({"sub": user_id, "exp": int(time.time()) + 60 * 60 * 24 * 7}, separators=(",", ":")).encode()).rstrip(b"=").decode()
    body = f"{header}.{payload}"
    sig = base64.urlsafe_b64encode(hmac.new(JWT_SECRET.encode(), body.encode(), hashlib.sha256).digest()).rstrip(b"=").decode()
    return f"{body}.{sig}"


def current_user():
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    try:
        header, payload, signature = auth[7:].split(".")
        body = f"{header}.{payload}"
        expected = base64.urlsafe_b64encode(hmac.new(JWT_SECRET.encode(), body.encode(), hashlib.sha256).digest()).rstrip(b"=").decode()
        if not hmac.compare_digest(signature, expected):
            return None
        raw = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
        data = json.loads(raw)
        if int(data["exp"]) < int(time.time()):
            return None
        return db.session.get(User, data["sub"])
    except Exception:
        return None


def auth_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        user = current_user()
        if not user:
            return jsonify({"error": "authentication required"}), 401
        return fn(user, *args, **kwargs)
    return wrapped


def user_json(user):
    return {"id": user.id, "email": user.email, "name": user.name, "elo": user.elo, "prime_score": user.prime_score, "wins": user.wins, "losses": user.losses, "games": user.games}


@app.get("/")
def index():
    return send_from_directory(BASE, "index.html")


@app.get("/<path:filename>")
def static_files(filename):
    return send_from_directory(BASE, filename)


@app.post("/api/auth/register")
def register():
    data = request.get_json(force=True) or {}
    email = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", ""))
    name = str(data.get("name", "PRIME USER")).strip()[:50] or "PRIME USER"
    if len(password) < 10 or "@" not in email:
        return jsonify({"error": "valid email and password of at least 10 characters required"}), 400
    if User.query.filter_by(email=email).first():
        return jsonify({"error": "email already registered"}), 409
    user = User(id=str(uuid.uuid4()), email=email, password_hash=password_hash(password), name=name)
    db.session.add(user)
    db.session.commit()
    return jsonify({"token": jwt_encode(user.id), "user": user_json(user)}), 201


@app.post("/api/auth/login")
def login():
    data = request.get_json(force=True) or {}
    user = User.query.filter_by(email=str(data.get("email", "")).strip().lower()).first()
    if not user or not user.password_hash or not password_ok(str(data.get("password", "")), user.password_hash):
        return jsonify({"error": "invalid credentials"}), 401
    return jsonify({"token": jwt_encode(user.id), "user": user_json(user)})


@app.get("/api/me")
@auth_required
def me(user):
    return jsonify(user_json(user))


@app.put("/api/profile")
@auth_required
def update_profile(user):
    data = request.get_json(force=True) or {}
    if "name" in data:
        user.name = str(data["name"]).strip()[:50] or user.name
    if "prime_score" in data:
        user.prime_score = max(0, min(100, int(data["prime_score"])))
    db.session.commit()
    return jsonify(user_json(user))


@app.get("/api/profile")
@auth_required
def profile(user):
    return jsonify(user_json(user))


@app.get("/api/leaderboard")
def leaderboard():
    rows = User.query.order_by(desc(User.elo), desc(User.wins), desc(User.prime_score)).limit(100).all()
    return jsonify([{**user_json(u), "rank": i + 1} for i, u in enumerate(rows)])


@app.post("/api/elo/match")
@auth_required
def match(user):
    import random
    opponent = User.query.filter(User.id != user.id).order_by(func.random()).first()
    is_bot = opponent is None
    opp_elo = random.randint(900, 1150) if is_bot else opponent.elo
    opp_name = "PRIME BOT" if is_bot else opponent.name
    my_power = user.prime_score + random.gauss(0, 8)
    opp_power = (random.randint(45, 80) if is_bot else opponent.prime_score) + random.gauss(0, 8)
    win = my_power >= opp_power
    expected = 1 / (1 + 10 ** ((opp_elo - user.elo) / 400))
    k = 32
    user_delta = max(8, round(k * ((1 if win else 0) - expected)))
    user_delta = user_delta if win else -abs(user_delta)
    user_before = user.elo
    user.elo = max(400, user.elo + user_delta)
    user.games += 1
    user.wins += int(win)
    user.losses += int(not win)
    winner_id = user.id if win else (opponent.id if opponent else None)
    loser_id = opponent.id if win and opponent else (user.id if not win else None)
    if opponent:
        opp_expected = 1 - expected
        opp_delta = round(k * ((0 if win else 1) - opp_expected))
        opponent_before = opponent.elo
        opponent.elo = max(400, opponent.elo + opp_delta)
        opponent.games += 1
        opponent.wins += int(not win)
        opponent.losses += int(win)
    else:
        opponent_before = opp_elo
        opp_delta = -user_delta
    db.session.add(EloMatch(id=str(uuid.uuid4()), winner_id=winner_id, loser_id=loser_id, winner_elo_before=user_before if win else opponent_before, loser_elo_before=opponent_before if win else user_before, winner_delta=user_delta if win else opp_delta, loser_delta=opp_delta if win else user_delta, opponent_name=opp_name, is_bot=is_bot))
    db.session.commit()
    return jsonify({"win": win, "delta": user_delta, "opponent": opp_name, "opponent_elo": opp_elo, "elo": user.elo, "is_bot": is_bot})


@app.get("/api/elo/history")
@auth_required
def elo_history(user):
    rows = EloMatch.query.filter((EloMatch.winner_id == user.id) | (EloMatch.loser_id == user.id)).order_by(desc(EloMatch.created_at)).limit(100).all()
    return jsonify([{"id": x.id, "opponent": x.opponent_name, "is_bot": x.is_bot, "created_at": x.created_at.isoformat(), "delta": x.winner_delta if x.winner_id == user.id else x.loser_delta} for x in rows])


def extract_json(text):
    try:
        return json.loads(text.strip())
    except Exception:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end < start:
            raise ValueError("AI did not return JSON")
        return json.loads(text[start:end + 1])


def gemini_json(prompt: str, image_b64: str | None = None, mime: str = "image/jpeg"):
    if not GEMINI_API_KEY:
        raise RuntimeError("AI service is not configured")
    parts = [{"text": prompt}]
    if image_b64:
        parts.append({"inline_data": {"mime_type": mime, "data": image_b64}})
    payload = {"contents": [{"parts": parts}], "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json"}}
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
    response = requests.post(url, params={"key": GEMINI_API_KEY}, json=payload, timeout=45)
    response.raise_for_status()
    text = "".join(p.get("text", "") for c in response.json().get("candidates", []) for p in c.get("content", {}).get("parts", []))
    return extract_json(text)


@app.post("/api/face-ai")
@auth_required
def face_ai(user):
    data = request.get_json(force=True) or {}
    image_b64 = data.get("image")
    if not image_b64:
        return jsonify({"error": "image is required"}), 400
    try:
        raw = base64.b64decode(image_b64, validate=True)
    except Exception:
        return jsonify({"error": "invalid image"}), 400
    if len(raw) > 8 * 1024 * 1024:
        return jsonify({"error": "image too large"}), 413
    prompt = '''You are the PRIME visual self-improvement coach. Analyze only visible, non-sensitive presentation features. Do not identify the person or infer age, race, ethnicity, religion, health, sexual orientation, or other sensitive traits. Do not diagnose or sexualize. Return ONLY JSON with score, type, summary, metrics (symmetry, proportion, grooming, hair, skin_appearance, presentation), tips and confidence. All numeric fields 0-100 integers. Tips must be practical and safe. If no clear face, confidence <=20.'''
    try:
        result = gemini_json(prompt, base64.b64encode(raw).decode("ascii"), data.get("mime", "image/jpeg"))
        score = max(0, min(100, int(result.get("score", 0))))
        result["score"] = score
        result["confidence"] = max(0, min(100, int(result.get("confidence", 0))))
        result["metrics"] = {k: max(0, min(100, int(v))) for k, v in (result.get("metrics") or {}).items()}
        result["tips"] = [str(x)[:300] for x in (result.get("tips") or [])[:5]]
        analysis = FaceAnalysis(id=str(uuid.uuid4()), user_id=user.id, score=score, analysis_type=str(result.get("type", "HTN"))[:20], summary=str(result.get("summary", ""))[:2000], metrics_json=json.dumps(result["metrics"]), tips_json=json.dumps(result["tips"]), confidence=result["confidence"])
        user.prime_score = score
        db.session.add(analysis)
        db.session.commit()
        return jsonify(result | {"analysis_id": analysis.id})
    except requests.RequestException:
        return jsonify({"error": "AI service temporarily unavailable"}), 502
    except Exception as exc:
        return jsonify({"error": "AI analysis failed", "details": str(exc) if app.debug else "request failed"}), 502


@app.get("/api/face/history")
@auth_required
def face_history(user):
    rows = FaceAnalysis.query.filter_by(user_id=user.id).order_by(desc(FaceAnalysis.created_at)).limit(100).all()
    return jsonify([{"id": x.id, "score": x.score, "type": x.analysis_type, "summary": x.summary, "metrics": json.loads(x.metrics_json), "tips": json.loads(x.tips_json), "confidence": x.confidence, "created_at": x.created_at.isoformat()} for x in rows])


@app.post("/api/advice")
@auth_required
def advice(user):
    data = request.get_json(force=True) or {}
    prompt = "Give 4 short, safe, practical self-improvement tips based only on this Prime Score and context. Never diagnose, sexualize, infer sensitive traits, recommend drugs, starvation, steroids or surgery. Context: " + json.dumps({"score": user.prime_score, "name": user.name, "request": str(data.get("request", ""))[:500]})
    try:
        result = gemini_json(prompt)
        return jsonify(result)
    except Exception:
        return jsonify({"tips": ["Keep a stable sleep schedule.", "Train consistently rather than chasing extreme routines.", "Focus on grooming and clothing fit.", "Use consistent lighting and angles for photo comparisons."]})


@app.get("/api/music")
@auth_required
def music_list(user):
    rows = MusicTrack.query.filter_by(user_id=user.id).order_by(desc(MusicTrack.created_at)).all()
    return jsonify([{"id": x.id, "name": x.original_name, "mime": x.mime_type, "size": x.size, "created_at": x.created_at.isoformat(), "url": f"/api/music/{x.id}"} for x in rows])


@app.post("/api/music")
@auth_required
def music_upload(user):
    file = request.files.get("file")
    if not file or not file.filename:
        return jsonify({"error": "file required"}), 400
    ext = Path(secure_filename(file.filename)).suffix.lower().lstrip(".")
    if ext not in ALLOWED_AUDIO:
        return jsonify({"error": "unsupported audio format"}), 415
    raw = file.read(MAX_AUDIO + 1)
    if len(raw) > MAX_AUDIO:
        return jsonify({"error": "audio file too large"}), 413
    track_id = str(uuid.uuid4())
    stored = f"{track_id}.{ext}"
    user_dir = MEDIA_ROOT / user.id
    user_dir.mkdir(parents=True, exist_ok=True)
    (user_dir / stored).write_bytes(raw)
    track = MusicTrack(id=track_id, user_id=user.id, original_name=secure_filename(file.filename)[:255], stored_name=stored, mime_type=file.mimetype or "audio/mpeg", size=len(raw))
    db.session.add(track)
    db.session.commit()
    return jsonify({"id": track.id, "name": track.original_name, "url": f"/api/music/{track.id}"}), 201


@app.get("/api/music/<track_id>")
@auth_required
def music_stream(user, track_id):
    track = MusicTrack.query.filter_by(id=track_id, user_id=user.id).first()
    if not track:
        return jsonify({"error": "track not found"}), 404
    path = MEDIA_ROOT / user.id / track.stored_name
    if not path.is_file():
        return jsonify({"error": "file missing"}), 404
    from flask import send_file
    return send_file(path, mimetype=track.mime_type, conditional=True, download_name=track.original_name)


@app.delete("/api/music/<track_id>")
@auth_required
def music_delete(user, track_id):
    track = MusicTrack.query.filter_by(id=track_id, user_id=user.id).first()
    if not track:
        return jsonify({"error": "track not found"}), 404
    path = MEDIA_ROOT / user.id / track.stored_name
    if path.exists():
        path.unlink()
    db.session.delete(track)
    db.session.commit()
    return jsonify({"ok": True})


@app.get("/health")
def health():
    db.session.execute(db.text("SELECT 1"))
    return jsonify({"status": "ok"})


with app.app_context():
    db.create_all()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "8765")), debug=False)
