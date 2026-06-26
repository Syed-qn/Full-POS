from functools import lru_cache

from app.config import get_settings
from app.speech.fake import FakeTranscriber
from app.speech.port import TranscriptionPort


@lru_cache
def get_transcriber() -> TranscriptionPort:
    """Return the configured speech-to-text provider (APP_STT_PROVIDER)."""
    provider = get_settings().stt_provider
    if provider == "elevenlabs":
        from app.speech.elevenlabs import ElevenLabsTranscriber

        return ElevenLabsTranscriber()
    if provider == "fake":
        return FakeTranscriber()
    raise ValueError(f"Unknown STT provider: {provider!r}")
