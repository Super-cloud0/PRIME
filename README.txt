PRIME — production architecture

UI
- Existing PRIME visual language and core screens are preserved.
- Added a small authentication overlay and a global leaderboard screen.

Backend
- Flask + SQLAlchemy.
- PostgreSQL is the production database via DATABASE_URL.
- Each account owns its profile, face-analysis history, ELO history and music library.
- JWT bearer authentication protects private APIs.
- Passwords use scrypt with per-password random salts.
- Gemini is server-side only; GEMINI_API_KEY is never sent to the browser.
- Face-analysis results are persisted; images are processed in memory and are not stored.
- Music files are stored outside the database in a per-user media directory and are only streamable by their owner.
- Global leaderboard is public; profile, AI, history and music APIs require authentication.

Development
1. Copy .env.example to .env and set PRIME_JWT_SECRET.
2. Install: pip install -r requirements.txt
3. Run: python server.py
4. Tests: pytest -q

Production with Docker
1. Set POSTGRES_PASSWORD, PRIME_JWT_SECRET and GEMINI_API_KEY in the environment.
2. Run: docker compose up --build -d
3. Open port 8765 through a TLS reverse proxy.

Secrets
- Never commit .env, API keys, JWT secrets or production passwords.
- Rotate credentials immediately if a secret is ever exposed.

CI
GitHub Actions runs Python compilation and pytest on pushes and pull requests.
