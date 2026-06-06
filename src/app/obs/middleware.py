"""Re-export SecurityHeadersMiddleware from canonical location (P7-T13).

The canonical implementation lives in ``app.middleware.security``.
This module exists so observability-oriented imports (``app.obs.middleware``)
continue to work without duplicating code.
"""
from app.middleware.security import SecurityHeadersMiddleware  # noqa: F401

__all__ = ["SecurityHeadersMiddleware"]
