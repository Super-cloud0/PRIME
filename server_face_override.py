"""Production entrypoint for Render.

The actual Flask app and Face AI implementation live in server.py.
This module intentionally re-exports the same app so Render can keep using
`gunicorn server_face_override:app` without registering a second /api/face-ai
route or a second Gemini implementation.
"""

from server import app

__all__ = ["app"]


if __name__ == "__main__":
    import os
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8765")))
