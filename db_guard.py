"""Database connection guard loaded before the Flask app.

Render can occasionally leave a PostgreSQL connection attempt waiting for a long
network timeout. PRIME's Telegram login must fail quickly and visibly instead
of leaving the Mini App on 'Проверяем Telegram…' forever.
"""

import os
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def _configure_database_timeout() -> None:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url or not url.startswith(("postgres://", "postgresql://", "postgresql+psycopg://")):
        return

    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.setdefault("connect_timeout", "8")
    # PostgreSQL statement timeout in milliseconds. This protects auth/profile
    # queries from a dead or stalled database connection.
    query.setdefault("options", "-c statement_timeout=8000")
    os.environ["DATABASE_URL"] = urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment)
    )


_configure_database_timeout()
