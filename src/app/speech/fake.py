class FakeTranscriber:
    """Deterministic transcriber for tests/dev — no network, no cost, no real STT.

    Behaviour:
      * If the audio bytes decode as UTF-8 text, that text is returned. This lets
        a test register ``b"chicken biryani"`` as the fake voice note (via
        ``MockProvider.set_media``) and get exactly that transcript back, so the
        whole voice → text → ordering pipeline can be asserted end-to-end.
      * Otherwise (real binary audio, or empty bytes) it returns ``canned`` — a
        class attribute so a test can set it to "" to exercise the
        "couldn't catch that" fallback, or to any phrase, without a real provider.

    NOT for production: it does not actually transcribe speech.
    """

    canned: str = "chicken biryani"

    async def transcribe(
        self, audio: bytes, *, mime: str = "audio/ogg", language: str | None = None
    ) -> str:
        try:
            text = audio.decode("utf-8").strip()
        except (UnicodeDecodeError, AttributeError):
            text = ""
        return text or self.canned
