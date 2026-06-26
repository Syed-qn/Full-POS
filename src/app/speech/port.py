from typing import Protocol


class TranscriptionPort(Protocol):
    """Speech-to-text port. Implementations turn spoken audio into text so an
    inbound WhatsApp voice note can be processed exactly like a typed message.

    Chosen at runtime by ``APP_STT_PROVIDER`` (see ``speech/factory.py``): a
    deterministic ``FakeTranscriber`` for tests/dev, a real provider in prod.
    Tests override it via the factory — never hit a real STT API in tests.
    """

    async def transcribe(
        self, audio: bytes, *, mime: str = "audio/ogg", language: str | None = None
    ) -> str:
        """Transcribe ``audio`` to text. ``language`` is an optional ISO hint
        (None = auto-detect). Returns the transcript, or '' if nothing
        intelligible was heard (the caller then asks the customer to retry)."""
        ...
