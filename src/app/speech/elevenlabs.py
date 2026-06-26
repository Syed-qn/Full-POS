import httpx

from app.config import get_settings

# ElevenLabs Scribe speech-to-text endpoint (multipart upload of the audio file).
_STT_URL = "https://api.elevenlabs.io/v1/speech-to-text"


class ElevenLabsTranscriber:
    """Speech-to-text via ElevenLabs Scribe.

    A single multipart ``POST /v1/speech-to-text`` with the audio bytes; auth is
    the ``xi-api-key`` header. Scribe auto-detects language (Arabic / Hindi /
    English supported), so ``language`` is only passed when explicitly given.

    NOTE: ElevenLabs' Free plan has NO commercial licence — use a paid plan
    (Starter+) for live customer traffic. The key comes from APP_ELEVENLABS_API_KEY.
    """

    def __init__(self) -> None:
        settings = get_settings()
        self._api_key = settings.elevenlabs_api_key.get_secret_value()
        self._model = settings.elevenlabs_stt_model or "scribe_v1"

    async def transcribe(
        self, audio: bytes, *, mime: str = "audio/ogg", language: str | None = None
    ) -> str:
        if not self._api_key:
            raise RuntimeError("APP_ELEVENLABS_API_KEY is not configured")
        if not audio:
            return ""
        headers = {"xi-api-key": self._api_key}
        data: dict[str, str] = {"model_id": self._model}
        if language:
            data["language_code"] = language
        files = {"file": ("voice-note", audio, mime or "audio/ogg")}
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(_STT_URL, headers=headers, data=data, files=files)
        resp.raise_for_status()
        return (resp.json().get("text") or "").strip()
