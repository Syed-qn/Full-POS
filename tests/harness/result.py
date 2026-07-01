from __future__ import annotations
from dataclasses import dataclass, field
from decimal import Decimal


@dataclass
class OutboundCapture:
    prefix: str
    body: str
    msg_type: str


@dataclass
class TranscriptTurnResult:
    inbound_text: str
    outbounds: list[OutboundCapture] = field(default_factory=list)
    cart_rows: list[dict] = field(default_factory=list)
    subtotal: Decimal | None = None
    total: Decimal | None = None
    phase: str | None = None
    state: dict = field(default_factory=dict)


@dataclass
class TranscriptResult:
    turns: list[TranscriptTurnResult] = field(default_factory=list)

    def last_outbound(self) -> OutboundCapture | None:
        for turn in reversed(self.turns):
            if turn.outbounds:
                return turn.outbounds[-1]
        return None

    def final_cart(self) -> list[dict]:
        for turn in reversed(self.turns):
            if turn.cart_rows:
                return turn.cart_rows
        return []
