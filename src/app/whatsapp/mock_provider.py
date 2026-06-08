import uuid
from collections import deque

from app.whatsapp.port import InboundMessage, OutboundMessage


class MockProvider:
    """In-memory WhatsApp provider for tests and the web simulator.

    Thread-safety: not needed — event loop is single-threaded.
    """

    def __init__(self) -> None:
        self._sends: list[OutboundMessage] = []
        self._inbound: deque[InboundMessage] = deque()

    async def send(self, msg: OutboundMessage) -> str:
        wa_id = f"mock-wamid-{uuid.uuid4().hex[:12]}"
        msg.wa_message_id = wa_id
        self._sends.append(msg)
        return wa_id

    def inject_inbound(self, msg: InboundMessage) -> None:
        """Queue an inbound message to be processed by the webhook pipeline."""
        self._inbound.append(msg)

    def drain_sends(self) -> list[OutboundMessage]:
        """Return all recorded sends and clear the log."""
        result = list(self._sends)
        self._sends.clear()
        return result

    def drain_sends_for(self, to_phone: str) -> list[OutboundMessage]:
        """Return sends addressed to `to_phone`, remove only those from the log."""
        matched = [m for m in self._sends if m.to_phone == to_phone]
        self._sends = [m for m in self._sends if m.to_phone != to_phone]
        return matched

    def drain_inbound(self) -> list[InboundMessage]:
        """Return all queued inbound messages and clear the queue."""
        result = list(self._inbound)
        self._inbound.clear()
        return result
