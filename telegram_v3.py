"""Versioned Telegram Mini App entrypoint.

Telegram clients can keep an old Mini App document even when query-string
cache busting changes. This module gives PRIME a new URL path so Telegram
loads a fresh document while keeping the existing app, API, auth, AI and ELO
handlers untouched.
"""
from urllib.parse import urlsplit, urlunsplit

from flask import send_from_directory

import server
from server_prod import BASE, app

VERSION = "20260821-3"
PATH = f"/__prime/{VERSION}"


def versioned_webapp_url() -> str:
    base = server.TELEGRAM_WEBAPP_URL.strip()
    if not base:
        return ""
    parts = urlsplit(base)
    return urlunsplit((parts.scheme, parts.netloc, PATH + "/", "", ""))


@app.get(f"{PATH}/")
def prime_versioned_index():
    return send_from_directory(BASE, "index.html")


@app.get(f"{PATH}/<path:filename>")
def prime_versioned_static(filename):
    return send_from_directory(BASE, filename)


def versioned_menu_markup():
    url = versioned_webapp_url()
    if not url:
        return None
    return {"inline_keyboard": [[
        {"text": "🚀 Открыть PRIME", "web_app": {"url": url}}
    ]]}


# Patch only the Telegram /start button URL. Authentication, AI, ELO and all
# existing API routes remain owned by their current modules.
server.telegram_menu_markup = versioned_menu_markup
