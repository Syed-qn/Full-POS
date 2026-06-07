"""Optional Sentry SDK integration — only initialises when APP_SENTRY_DSN is set."""
import logging

logger = logging.getLogger(__name__)


def init_sentry(dsn: str | None, environment: str = "dev") -> None:
    """Initialize Sentry if DSN is provided. No-op when DSN is empty/None."""
    if not dsn:
        return
    try:
        import sentry_sdk
        sentry_sdk.init(
            dsn=dsn,
            environment=environment,
            traces_sample_rate=0.1,
            profiles_sample_rate=0.0,
        )
        logger.info("Sentry initialised", extra={"environment": environment})
    except ImportError:
        logger.warning("sentry-sdk not installed — skipping Sentry init")
