"""Structlog JSON logging configuration (P7-T8).

Call ``configure_logging()`` once at application startup (in lifespan or __main__).
In test environments APP_ENV!=prod, a human-readable renderer is used instead.

NOTE: ``structlog`` is not yet listed in pyproject.toml dependencies.
Add ``"structlog>=24.0"`` to the ``dependencies`` list in pyproject.toml before
deploying to production.
"""
import logging
import sys

import structlog


def configure_logging(*, production: bool = False) -> None:
    """Configure structlog with JSON output (prod) or pretty console (dev)."""
    shared_processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
    ]

    if production:
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=shared_processors + [
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=logging.INFO,
    )


def get_request_id_processor():
    """Return a structlog processor that reads request_id from context vars.

    Returns a tuple of (processor_fn, context_var) so callers can both install
    the processor and set the context variable per-request.

    Usage::

        add_request_id, _request_id_var = get_request_id_processor()
        # set per request:
        _request_id_var.set(str(uuid.uuid4()))
    """
    import contextvars

    _request_id: contextvars.ContextVar[str] = contextvars.ContextVar(
        "request_id", default="-"
    )

    def add_request_id(logger, method, event_dict):  # noqa: ARG001
        event_dict["request_id"] = _request_id.get()
        return event_dict

    return add_request_id, _request_id
