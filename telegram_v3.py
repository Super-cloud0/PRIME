"""Versioned Telegram Mini App entrypoint with explicit asset cache busting."""
from urllib.parse import urlsplit, urlunsplit

from flask import Response, send_from_directory

import server
from server_prod import BASE, app

VERSION = "20260821-4"
PATH = f"/__prime/{VERSION}"


def versioned_webapp_url() -> str:
    base = server.TELEGRAM_WEBAPP_URL.strip()
    if not base:
        return ""
    parts = urlsplit(base)
    return urlunsplit((parts.scheme, parts.netloc, PATH + "/", "", ""))


@app.get(f"{PATH}/")
def prime_versioned_index():
    # Telegram can cache both the document and referenced JS independently.
    # Return a fresh HTML document with a unique asset version on every new
    # PRIME path version, and explicitly disable caching for the entrypoint.
    html = (BASE / "index.html").read_text(encoding="utf-8")
    for asset in ("style.css", "fetch_guard.js", "share.js", "app.js"):
        html = html.replace(f"{asset}?v=575e807", f"{asset}?v={VERSION}")
    response = Response(html, mimetype="text/html")
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@app.get(f"{PATH}/<path:filename>")
def prime_versioned_static(filename):
    response = send_from_directory(BASE, filename)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


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
