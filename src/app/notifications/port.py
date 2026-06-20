"""Push notification port (native rider app).

Abstracts sending a push to a rider's device so the app can be woken when a
delivery is assigned (or, later, on a new chat message). ``FakePushProvider``
records sends for tests/dev; ``ExpoPushProvider`` calls the Expo Push API in
prod. Chosen by ``APP_PUSH_PROVIDER`` via ``notifications/factory.py``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class PushMessage:
    to_token: str
    title: str
    body: str
    # Arbitrary data delivered to the app (e.g. {"type": "assignment",
    # "order_id": 13}) so a tap can deep-link to the right screen.
    data: dict = field(default_factory=dict)


class PushPort(Protocol):
    async def send(self, message: PushMessage) -> bool:
        """Deliver one push. Returns True on success. Never raises for a normal
        delivery failure (a dead token, network error) — returns False and lets
        the caller continue; pushes are best-effort."""
        ...
