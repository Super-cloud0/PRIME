"""Database connection guard loaded before Flask/SQLAlchemy initialization."""

import os
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def _configure_database_timeout() -> None:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        return

    # Render/Postgres URLs can use postgres, postgresql, psycopg or psycopg2
    # driver schemes. Keep the original driver and only add safe libpq options.
    if not url.lower().startswith(("postgres://", "postgresql://")):
        return

    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.setdefault("connect_timeout", "5")
    query.setdefault("options", "-c statement_timeout=5000")
    os.environ["DATABASE_URL"] = urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment)
    )


_configure_database_timeout()
