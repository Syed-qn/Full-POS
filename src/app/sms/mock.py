import uuid


class MockSmsGateway:
    """Always succeeds, records every send in memory. Used for dev/tests and
    any restaurant that hasn't connected a real SMS provider yet — same role
    as ``MockPaymentProcessor`` for payments."""

    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send(self, *, to_phone: str, body: str) -> str:
        message_id = f"mock_sms_{uuid.uuid4().hex[:16]}"
        self.sent.append({"to_phone": to_phone, "body": body, "message_id": message_id})
        return message_id
