import os

os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["PRIME_JWT_SECRET"] = "test-secret-only"
os.environ["COOKIE_SECURE"] = "0"
os.environ["GEMINI_API_KEY"] = ""

from server_prod import app, db


def setup_function():
    app.config.update(TESTING=True, RATELIMIT_ENABLED=False)
    with app.app_context():
        db.drop_all()
        db.create_all()


def auth(client, email="test@example.com"):
    response = client.post("/api/auth/register", json={"name": "Test", "email": email, "password": "long-enough-password"})
    assert response.status_code == 201
    return response.get_json()["token"]


def test_health_and_auth():
    client = app.test_client()
    assert client.get("/health").status_code == 200
    token = auth(client)
    assert client.get("/api/me", headers={"Authorization": f"Bearer {token}"}).get_json()["name"] == "Test"


def test_auth_is_required():
    client = app.test_client()
    assert client.get("/api/me").status_code == 401
    assert client.post("/api/elo/match", json={}).status_code == 401


def test_profile_isolated_and_leaderboard_public():
    client = app.test_client()
    token_a = auth(client, "a@example.com")
    token_b = auth(client, "b@example.com")
    assert client.get("/api/leaderboard").status_code == 200
    a = client.get("/api/me", headers={"Authorization": f"Bearer {token_a}"}).get_json()
    b = client.get("/api/me", headers={"Authorization": f"Bearer {token_b}"}).get_json()
    assert a["id"] != b["id"]


def test_elo_history_is_user_scoped():
    client = app.test_client()
    token = auth(client)
    response = client.post("/api/elo/match", headers={"Authorization": f"Bearer {token}"}, json={})
    assert response.status_code == 200
    history = client.get("/api/elo/history", headers={"Authorization": f"Bearer {token}"})
    assert history.status_code == 200
    assert len(history.get_json()) == 1


def test_music_requires_ownership():
    client = app.test_client()
    token = auth(client)
    response = client.get("/api/music/not-a-real-track", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 404
