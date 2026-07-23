"""Request-scoped identity of the person performing an action.

``record_audit`` is called from ~200 places, almost none of which have the
staff member in scope — they only know the ROLE they were called with. Rather
than thread a ``staff_id`` argument through every service signature, the HTTP
layer stamps it here once per request and ``record_audit`` reads it.

Nothing outside a request (Celery tasks, webhooks) sets it, so those rows keep
recording the role alone, which is correct: no human performed them.
"""

from contextvars import ContextVar

current_actor_staff_id: ContextVar[int | None] = ContextVar(
    "current_actor_staff_id", default=None
)


def get_actor_staff_id() -> int | None:
    return current_actor_staff_id.get()
