import os

os.environ["PRIME_JWT_SECRET"] = "test-secret-please-change"
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["GEMINI_API_KEY"] = ""
os.environ["TELEGRAM_BOT_TOKEN"] = "123456:TEST_TOKEN"

from server import app, db, User


def setup_function():
    app.config["TESTING"] = True
    app.config["RATELIMIT_ENABLED"] = False
    with app.app_context():
        db.drop_all()
        db.create_all()


def test_register_and_login():
    c = app.test_client()
    r = c.post("/api/auth/register", json={"name": "Test", "email": "test@example.com", "password": "long-test-password"})
    assert r.status_code == 201
    token = r.get_json()["token"]
    assert c.get("/api/me", headers={"Authorization": f"Bearer {token}"}).status_code == 200
    r = c.post("/api/auth/login", json={"email": "test@example.com", "password": "long-test-password"})
    assert r.status_code == 200


def test_private_music_requires_auth():
    assert app.test_client().get("/api/music").status_code == 401


def test_leaderboard_is_public():
    c = app.test_client()
    c.post("/api/auth/register", json={"name": "A", "email": "a@example.com", "password": "long-test-password"})
    assert c.get("/api/leaderboard").status_code == 200
