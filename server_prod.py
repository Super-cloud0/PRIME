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
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import desc, func, or_
from werkzeug.utils import secure_filename

BASE = Path(__file__).resolve().parent
MEDIA_ROOT = Path(os.environ.get("PRIME_MEDIA_ROOT", BASE / "media"))
MEDIA_ROOT.mkdir(parents=True, exist_ok=True)

app = Flask(__name__, static_folder=str(BASE))
app.config.update(
    SQLALCHEMY_DATABASE_URI=os.environ.get("DATABASE_URL", "sqlite:///prime_dev.db"),
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    MAX_CONTENT_LENGTH=35 * 1024 * 1024,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "1") == "1",
    SESSION_COOKIE_SAMESITE="Lax",
)
db = SQLAlchemy(app)
migrate = Migrate(app, db)
limiter = Limiter(key_func=get_remote_address, app=app, default_limits=["300 per hour"], storage_uri=os.environ.get("RATELIMIT_STORAGE_URI", "memory://"))

JWT_SECRET = os.environ.get("PRIME_JWT_SECRET", "").strip()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
MAX_AUDIO = 25 * 1024 * 1024
ALLOWED_AUDIO = {"mp3", "wav", "ogg", "m4a", "aac", "flac", "webm"}


class User(db.Model):
    id = db.Column(db.String(36), primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    name = db.Column(db.String(50), nullable=False, default="PRIME USER")
    elo = db.Column(db.Integer, nullable=False, default=1000)
    prime_score = db.Column(db.Integer, nullable=False, default=50)
    wins = db.Column(db.Integer, nullable=False, default=0)
    losses = db.Column(db.Integer, nullable=False, default=0)
    games = db.Column(db.Integer, nullable=False, default=0)
    telegram_chat_id = db.Column(db.BigInteger, nullable=True, index=True)
    reminders_enabled = db.Column(db.Boolean, nullable=False, default=True)
    last_reminder_at = db.Column(db.DateTime(timezone=True), nullable=True)
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
    # Filename of the source photo under MEDIA_ROOT/<user_id>/, nullable because
    # older rows (analyzed before this column existed) never had one saved.
    # This is what powers the weekly before/after progress view -- without a
    # persisted photo per analysis there is nothing to show side by side with
    # the score history.
    photo_path = db.Column(db.String(100), nullable=True)
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


def _ensure_face_photo_column():
    # This deployment's Dockerfile runs gunicorn directly and does not call
    # `flask db upgrade` on boot (only start_prod.sh/Dockerfile.prod's manual
    # path does), so a normal Alembic migration alone would silently never
    # run against the live Render Postgres database and every /api/face-ai
    # call would 500 the moment code expects a column the table doesn't have.
    # This best-effort check runs once at import time and adds the column
    # directly if it's missing, so the feature works whether or not the
    # migration is ever applied separately. The proper Alembic migration
    # (migrations/versions/0002_face_photo.py) still exists and should be
    # run too -- this is a safety net, not a replacement for it.
    try:
        from sqlalchemy import inspect as _sa_inspect
        with app.app_context():
            inspector = _sa_inspect(db.engine)
            if "face_analysis" not in inspector.get_table_names():
                return  # tables not created yet -- db.create_all()/migration will include the column
            columns = {col["name"] for col in inspector.get_columns("face_analysis")}
            if "photo_path" not in columns:
                with db.engine.begin() as conn:
                    conn.execute(db.text("ALTER TABLE face_analysis ADD COLUMN photo_path VARCHAR(100)"))
    except Exception:
        app.logger.exception("PRIME auto-migrate for face_analysis.photo_path failed (non-fatal)")


_ensure_face_photo_column()


def _ensure_reminder_columns():
    # Same reasoning as _ensure_face_photo_column(): this deployment's
    # Dockerfile runs gunicorn directly without `flask db upgrade`, so the
    # Alembic migration (migrations/versions/0003_weekly_reminders.py) alone
    # would silently never apply to the live Render Postgres database. This
    # best-effort check adds the missing "user" columns directly at import
    # time so weekly reminders work whether or not the migration is run too.
    try:
        from sqlalchemy import inspect as _sa_inspect
        with app.app_context():
            inspector = _sa_inspect(db.engine)
            if "user" not in inspector.get_table_names():
                return  # tables not created yet -- db.create_all()/migration will include the columns
            columns = {col["name"] for col in inspector.get_columns("user")}
            with db.engine.begin() as conn:
                if "telegram_chat_id" not in columns:
                    conn.execute(db.text('ALTER TABLE "user" ADD COLUMN telegram_chat_id BIGINT'))
                if "reminders_enabled" not in columns:
                    conn.execute(db.text('ALTER TABLE "user" ADD COLUMN reminders_enabled BOOLEAN NOT NULL DEFAULT TRUE'))
                if "last_reminder_at" not in columns:
                    conn.execute(db.text('ALTER TABLE "user" ADD COLUMN last_reminder_at TIMESTAMP WITH TIME ZONE'))
    except Exception:
        app.logger.exception("PRIME auto-migrate for user reminder columns failed (non-fatal)")


_ensure_reminder_columns()


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
    payload = base64.urlsafe_b64encode(json.dumps({"sub": user_id, "exp": int(time.time()) + 604800}, separators=(",", ":")).encode()).rstrip(b"=").decode()
    body = f"{header}.{payload}"
    signature = base64.urlsafe_b64encode(hmac.new(JWT_SECRET.encode(), body.encode(), hashlib.sha256).digest()).rstrip(b"=").decode()
    return f"{body}.{signature}"


def current_user():
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer ") or not JWT_SECRET:
        return None
    try:
        header, payload, signature = auth[7:].split(".")
        body = f"{header}.{payload}"
        expected = base64.urlsafe_b64encode(hmac.new(JWT_SECRET.encode(), body.encode(), hashlib.sha256).digest()).rstrip(b"=").decode()
        if not hmac.compare_digest(signature, expected):
            return None
        data = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
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


def user_json(user: User):
    return {"id": user.id, "email": user.email, "name": user.name, "elo": user.elo, "prime_score": user.prime_score, "wins": user.wins, "losses": user.losses, "games": user.games}


@app.get("/health")
def health():
    try:
        db.session.execute(db.text("SELECT 1"))
        return jsonify({"status": "ok"})
    except Exception:
        return jsonify({"status": "degraded"}), 503


@app.get("/")
def index():
    return send_from_directory(BASE, "index.html")


@app.get("/<path:filename>")
def static_files(filename):
    return send_from_directory(BASE, filename)


@app.post("/api/auth/register")
@limiter.limit("5 per minute")
def register():
    data = request.get_json(silent=True) or {}
    email = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", ""))
    name = str(data.get("name", "PRIME USER")).strip()[:50] or "PRIME USER"
    if len(password) < 10 or "@" not in email or len(email) > 255:
        return jsonify({"error": "valid email and password of at least 10 characters required"}), 400
    if not JWT_SECRET:
        return jsonify({"error": "authentication service is not configured"}), 503
    if User.query.filter_by(email=email).first():
        return jsonify({"error": "email already registered"}), 409
    user = User(id=str(uuid.uuid4()), email=email, password_hash=password_hash(password), name=name)
    db.session.add(user)
    db.session.commit()
    return jsonify({"token": jwt_encode(user.id), "user": user_json(user)}), 201


@app.post("/api/auth/login")
@limiter.limit("10 per minute")
def login():
    data = request.get_json(silent=True) or {}
    user = User.query.filter_by(email=str(data.get("email", "")).strip().lower()).first()
    if not user or not password_ok(str(data.get("password", "")), user.password_hash):
        return jsonify({"error": "invalid credentials"}), 401
    if not JWT_SECRET:
        return jsonify({"error": "authentication service is not configured"}), 503
    return jsonify({"token": jwt_encode(user.id), "user": user_json(user)})


@app.get("/api/me")
@auth_required
def me(user):
    return jsonify(user_json(user))


@app.put("/api/profile")
@auth_required
def update_profile(user):
    data = request.get_json(silent=True) or {}
    if "name" in data:
        user.name = str(data["name"]).strip()[:50] or user.name
    db.session.commit()
    return jsonify(user_json(user))


@app.get("/api/profile")
@auth_required
def profile(user):
    return jsonify(user_json(user))


@app.get("/api/leaderboard")
def leaderboard():
    rows = User.query.order_by(desc(User.elo), desc(User.wins), desc(User.prime_score)).limit(100).all()
    return jsonify([{**user_json(user), "rank": i + 1} for i, user in enumerate(rows)])


def elo_expected(rating_a: int, rating_b: int) -> float:
    return 1 / (1 + 10 ** ((rating_b - rating_a) / 400))


@app.post("/api/elo/match")
@auth_required
def match(user):
    import random
    opponent = User.query.filter(User.id != user.id).order_by(func.random()).first()
    is_bot = opponent is None
    opponent_elo = random.randint(900, 1150) if is_bot else opponent.elo
    opponent_name = "PRIME BOT" if is_bot else opponent.name
    my_power = user.prime_score + random.gauss(0, 8)
    opponent_power = (random.randint(45, 80) if is_bot else opponent.prime_score) + random.gauss(0, 8)
    win = my_power >= opponent_power
    expected = elo_expected(user.elo, opponent_elo)
    k = 32
    user_delta = round(k * ((1 if win else 0) - expected))
    user_delta = max(8, user_delta) if win else min(-8, user_delta)
    user_before = user.elo
    user.elo = max(400, user.elo + user_delta)
    user.games += 1
    user.wins += int(win)
    user.losses += int(not win)
    if opponent:
        opponent_delta = round(k * ((0 if win else 1) - (1 - expected)))
        opponent_before = opponent.elo
        opponent.elo = max(400, opponent.elo + opponent_delta)
        opponent.games += 1
        opponent.wins += int(not win)
        opponent.losses += int(win)
    else:
        opponent_before = opponent_elo
        opponent_delta = -user_delta
    winner_id = user.id if win else (opponent.id if opponent else None)
    loser_id = opponent.id if win and opponent else (user.id if not win else None)
    db.session.add(EloMatch(id=str(uuid.uuid4()), winner_id=winner_id, loser_id=loser_id, winner_elo_before=user_before if win else opponent_before, loser_elo_before=opponent_before if win else user_before, winner_delta=user_delta if win else opponent_delta, loser_delta=opponent_delta if win else user_delta, opponent_name=opponent_name, is_bot=is_bot))
    db.session.commit()
    return jsonify({"win": win, "delta": user_delta, "opponent": opponent_name, "opponent_elo": opponent_elo, "elo": user.elo, "is_bot": is_bot})


@app.get("/api/elo/history")
@auth_required
def elo_history(user):
    rows = EloMatch.query.filter(or_(EloMatch.winner_id == user.id, EloMatch.loser_id == user.id)).order_by(desc(EloMatch.created_at)).limit(100).all()
    return jsonify([{"id": row.id, "opponent": row.opponent_name, "is_bot": row.is_bot, "created_at": row.created_at.isoformat(), "delta": row.winner_delta if row.winner_id == user.id else row.loser_delta} for row in rows])


def extract_json(text: str):
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
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
    text = "".join(part.get("text", "") for candidate in response.json().get("candidates", []) for part in candidate.get("content", {}).get("parts", []))
    return extract_json(text)


_PHOTO_EXT_BY_MIME = {"image/jpeg": "jpg", "image/jpg": "jpg", "image/png": "png", "image/webp": "webp"}


def _save_face_photo(user_id: str, analysis_id: str, raw: bytes, mime: str) -> str | None:
    # Best-effort: a failure here must never break the analysis response --
    # the score/tips are the product, the saved photo only powers the
    # progress view, so this never raises.
    try:
        ext = _PHOTO_EXT_BY_MIME.get((mime or "").lower(), "jpg")
        stored_name = f"{analysis_id}.{ext}"
        user_dir = MEDIA_ROOT / user_id
        user_dir.mkdir(parents=True, exist_ok=True)
        (user_dir / stored_name).write_bytes(raw)
        return stored_name
    except Exception:
        app.logger.exception("PRIME failed to persist face-analysis photo (non-fatal)")
        return None


@app.post("/api/face-ai")
@auth_required
@limiter.limit("10 per minute")
def face_ai(user):
    data = request.get_json(silent=True) or {}
    image_b64 = data.get("image")
    if not image_b64 or not isinstance(image_b64, str):
        return jsonify({"error": "image is required"}), 400
    try:
        raw = base64.b64decode(image_b64, validate=True)
    except Exception:
        return jsonify({"error": "invalid image"}), 400
    if len(raw) > 8 * 1024 * 1024:
        return jsonify({"error": "image too large"}), 413
    prompt = """You are the PRIME visual self-improvement coach. Analyze only visible, non-sensitive presentation features. Do not identify the person or infer age, race, ethnicity, religion, health, sexual orientation, or other sensitive traits. Do not diagnose or sexualize. Return ONLY JSON with score, type, summary, metrics (symmetry, proportion, grooming, hair, skin_appearance, presentation), tips and confidence. All numeric fields are 0-100 integers. Tips must be practical and safe. If no clear face, confidence must be <=20."""
    try:
        result = gemini_json(prompt, base64.b64encode(raw).decode("ascii"), data.get("mime", "image/jpeg"))
        score = max(0, min(100, int(result.get("score", 0))))
        metrics = {key: max(0, min(100, int(value))) for key, value in (result.get("metrics") or {}).items() if isinstance(value, (int, float))}
        tips = [str(value)[:300] for value in (result.get("tips") or [])[:5]]
        confidence = max(0, min(100, int(result.get("confidence", 0))))
        analysis_id = str(uuid.uuid4())
        photo_path = _save_face_photo(user.id, analysis_id, raw, data.get("mime", "image/jpeg"))
        analysis = FaceAnalysis(id=analysis_id, user_id=user.id, score=score, analysis_type=str(result.get("type", "HTN"))[:20], summary=str(result.get("summary", ""))[:2000], metrics_json=json.dumps(metrics), tips_json=json.dumps(tips), confidence=confidence, photo_path=photo_path)
        user.prime_score = score
        db.session.add(analysis)
        db.session.commit()
        result.update({"score": score, "metrics": metrics, "tips": tips, "confidence": confidence, "analysis_id": analysis.id, "photo_url": f"/api/face/photo/{analysis.id}" if photo_path else None})
        return jsonify(result)
    except requests.RequestException:
        return jsonify({"error": "AI service temporarily unavailable"}), 502
    except Exception:
        return jsonify({"error": "AI analysis failed"}), 502


@app.get("/api/face/history")
@auth_required
def face_history(user):
    rows = FaceAnalysis.query.filter_by(user_id=user.id).order_by(desc(FaceAnalysis.created_at)).limit(100).all()
    return jsonify([{"id": row.id, "score": row.score, "type": row.analysis_type, "summary": row.summary, "metrics": json.loads(row.metrics_json), "tips": json.loads(row.tips_json), "confidence": row.confidence, "created_at": row.created_at.isoformat(), "photo_url": f"/api/face/photo/{row.id}" if row.photo_path else None} for row in rows])


@app.get("/api/face/photo/<analysis_id>")
@auth_required
def face_photo(user, analysis_id):
    row = FaceAnalysis.query.filter_by(id=analysis_id, user_id=user.id).first()
    if not row or not row.photo_path:
        return jsonify({"error": "photo not found"}), 404
    return send_from_directory(MEDIA_ROOT / user.id, row.photo_path, conditional=True)


# Metric labels kept here (not just client-side) because they're interpolated
# straight into the Gemini prompt below -- the model needs readable names,
# not the raw snake_case keys, to reason about each one specifically.
_METRIC_LABELS = {
    "symmetry": "facial symmetry",
    "proportion": "facial proportion/balance",
    "grooming": "grooming (eyebrows, facial hair, skincare routine visible in photo)",
    "hair": "hairstyle/haircut",
    "skin_appearance": "skin appearance (texture, clarity, tone evenness)",
    "presentation": "overall presentation (photo angle, lighting, expression, styling)",
}


@app.post("/api/advice")
@auth_required
@limiter.limit("20 per minute")
def advice(user):
    # Advice used to be generated from nothing but the bare PRIME score
    # ("Give 4 tips based on score: 62") -- that's disconnected from what's
    # actually weak on this specific person, so the model had nothing to
    # reason about and fell back to generic wellness filler (sleep, diet).
    # This now pulls the user's most recent real analysis (per-metric scores
    # + the AI's own summary of that photo) and asks for one concrete,
    # specific routine per weak metric instead of a flat list of platitudes.
    latest = FaceAnalysis.query.filter_by(user_id=user.id).order_by(desc(FaceAnalysis.created_at)).first()
    safety_rules = "Never diagnose, sexualize, infer sensitive traits (age, race, ethnicity, health, disability, sexual orientation), or recommend drugs, extreme dieting/starvation, steroids, or surgery. Advice must be safe, realistic, and achievable within a week."
    if latest is None:
        prompt = (
            "The user has not analyzed a photo yet, so give general starter advice for someone about to use a visual "
            "self-improvement coach: 4 short, concrete, practical tips covering grooming, skincare basics, hair, and how "
            "to take a good reference photo (lighting/angle) for their first scan. "
            + safety_rules
            + ' Return ONLY valid JSON: {"tips": ["...", "...", "...", "..."], "focus": []}'
        )
    else:
        metrics = json.loads(latest.metrics_json) if latest.metrics_json else {}
        metric_lines = "\n".join(f"- {_METRIC_LABELS.get(key, key)}: {value}/100" for key, value in metrics.items())
        prompt = f"""You are the PRIME visual self-improvement coach giving a weekly check-in plan for a real analyzed photo.

Scores from the user's most recent analysis (0-100 each):
{metric_lines}

The AI's summary of that photo: {latest.summary or "(no summary available)"}

Task: for EVERY metric scoring below 60, write one concrete, specific, actionable routine or technique aimed at that exact metric -- name real steps, techniques, or product CATEGORIES (never brand names), not vague filler like "eat healthy" or "sleep well" unless it is the single most relevant lever for that specific metric. If every metric is 60 or above, still include the two lowest-scoring metrics with a brief maintenance/highlighting tip instead. Order the focus list weakest metric first.
{safety_rules}

Return ONLY valid JSON in this exact shape:
{{"tips": ["4 to 6 short one-line highlights, punchy and specific"], "focus": [{{"metric": "the metric key exactly as given above (e.g. skin_appearance)", "score": <int>, "action": "2-3 concrete sentences: exact steps/technique for this metric, framed as a one-week routine"}}]}}
"""
    try:
        result = gemini_json(prompt)
        tips = [str(value)[:220] for value in (result.get("tips") or [])[:6]]
        focus = []
        for entry in (result.get("focus") or [])[:6]:
            if not isinstance(entry, dict):
                continue
            metric_key = str(entry.get("metric", ""))[:40]
            try:
                score_value = max(0, min(100, int(float(entry.get("score", 0)))))
            except (TypeError, ValueError):
                score_value = None
            focus.append({
                "metric": metric_key,
                "label": _METRIC_LABELS.get(metric_key, metric_key.replace("_", " ")),
                "score": score_value,
                "action": str(entry.get("action", ""))[:500],
            })
        return jsonify({"tips": tips or ["Keep a stable sleep schedule.", "Train consistently rather than chasing extreme routines.", "Focus on grooming and clothing fit.", "Use consistent lighting and angles for photo comparisons."], "focus": focus})
    except Exception:
        app.logger.exception("PRIME advice generation failed; returning fallback")
        return jsonify({"tips": ["Keep a stable sleep schedule.", "Train consistently rather than chasing extreme routines.", "Focus on grooming and clothing fit.", "Use consistent lighting and angles for photo comparisons."], "focus": []})


@app.get("/api/music")
@auth_required
def music_list(user):
    rows = MusicTrack.query.filter_by(user_id=user.id).order_by(desc(MusicTrack.created_at)).all()
    return jsonify([{"id": row.id, "name": row.original_name, "mime": row.mime_type, "size": row.size, "created_at": row.created_at.isoformat(), "url": f"/api/music/{row.id}"} for row in rows])


@app.post("/api/music")
@auth_required
@limiter.limit("30 per hour")
def music_upload(user):
    file = request.files.get("file")
    if not file or not file.filename:
        return jsonify({"error": "file required"}), 400
    filename = secure_filename(file.filename)
    ext = Path(filename).suffix.lower().lstrip(".")
    if ext not in ALLOWED_AUDIO:
        return jsonify({"error": "unsupported audio format"}), 415
    raw = file.read(MAX_AUDIO + 1)
    if len(raw) > MAX_AUDIO:
        return jsonify({"error": "audio file too large"}), 413
    track_id = str(uuid.uuid4())
    stored_name = f"{track_id}.{ext}"
    user_dir = MEDIA_ROOT / user.id
    user_dir.mkdir(parents=True, exist_ok=True)
    (user_dir / stored_name).write_bytes(raw)
    track = MusicTrack(id=track_id, user_id=user.id, original_name=filename[:255], stored_name=stored_name, mime_type=file.mimetype or "audio/*", size=len(raw))
    db.session.add(track)
    db.session.commit()
    return jsonify({"id": track.id, "name": track.original_name, "url": f"/api/music/{track.id}"}), 201


@app.get("/api/music/<track_id>")
@auth_required
def music_stream(user, track_id):
    track = MusicTrack.query.filter_by(id=track_id, user_id=user.id).first()
    if not track:
        return jsonify({"error": "track not found"}), 404
    return send_from_directory(MEDIA_ROOT / user.id, track.stored_name, mimetype=track.mime_type, conditional=True)


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


@app.errorhandler(413)
def too_large(_error):
    return jsonify({"error": "request too large"}), 413


@app.errorhandler(429)
def rate_limited(_error):
    return jsonify({"error": "too many requests"}), 429


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8765")), debug=False)
