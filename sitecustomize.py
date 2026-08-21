"""Early Python startup hook used to register PRIME's optional ELO extensions.

Python imports sitecustomize during normal startup. We import the legacy ELO
module first for compatibility, then the v3 module last so its backward-
compatible view-function overrides are the active production handlers.
Failures are logged but never block application startup.
"""
import logging

logger = logging.getLogger("prime.sitecustomize")
try:
    import elo_v2  # noqa: F401
    import elo_v3  # noqa: F401
except Exception:
    logger.exception("PRIME ELO extension failed to initialize; legacy routes remain available")
