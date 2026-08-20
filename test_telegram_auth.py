import hashlib
import hmac
import json
import os
import time
from urllib.parse import urlencode

os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["PRIME_JWT_SECRET"] = "test-secret-only"
os.environ["COOKIE_SECURE"] = "0"
os.environ["GEMINI_API_KEY"] = ""
os.environ["TELEGRAM_BOT_TOKEN"] = "123456:TEST_TOKEN"

from server import app, db


def telegram_init_data(user_id=123456789, first_name="Test", auth_date=None):
    auth_date = auth_date or int(time.time())
    user = json.dumps({"id": user_id, "first_name": first_name}, separators=(",", ":"))
    fields = {"auth_date": str(auth_date), "query_id": "AA-test", "user": user}
    check = "\n".join(f"{key}={value}" for key, value in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", os.environ["TELEGRAM_BOT_TOKEN"].encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


def setup_function():
    app.config.update(TESTING=True, RATELIMIT_ENABLED=False)
    with app.app_context():
        db.drop_all()
        db.create_all()


def test_telegram_creates_and_reuses_same_account():
    client = app.test_client()
    payload = {"initData": telegram_init_data()}
    first = client.post("/api/auth/telegram", json=payload)
    assert first.status_code == 200
    first_user = first.get_json()["user"]

    second = client.post("/api/auth/telegram", json=payload)
    assert second.status_code == 200
    second_user = second.get_json()["user"]
    assert second_user["id"] == first_user["id"]
    assert second_user["elo"] == 1000


def test_telegram_rejects_tampered_data():
    client = app.test_client()
    payload = {"initData": telegram_init_data().replace("Test", "Hacker")}
    assert client.post("/api/auth/telegram", json=payload).status_code == 401
