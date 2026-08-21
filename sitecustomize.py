"""Early Python startup hook used to register PRIME optional extensions."""
import logging

logger = logging.getLogger("prime.sitecustomize")
try:
    import elo_v2  # noqa: F401
    import elo_v3  # noqa: F401
except Exception:
    logger.exception("PRIME ELO extension failed to initialize; legacy routes remain available")

try:
    import telegram_v3  # noqa: F401
except Exception:
    logger.exception("PRIME Telegram versioned entrypoint failed to initialize; existing Telegram route remains available")
