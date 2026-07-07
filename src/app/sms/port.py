from typing import Protocol


class SmsPort(Protocol):
    async def send(self, *, to_phone: str, body: str) -> str: ...
