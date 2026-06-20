"""In-memory push provider for tests/dev — records sends, never hits the network."""
from __future__ import annotations

from app.notifications.port import PushMessage


class FakePushProvider:
    """Records every push in ``sent`` so tests can assert on them."""

    def __init__(self) -> None:
        self.sent: list[PushMessage] = []

    async def send(self, message: PushMessage) -> bool:
        self.sent.append(message)
        return True
