import pytest

from app.speech.fake import FakeTranscriber
from app.speech.factory import get_transcriber


async def test_fake_decodes_utf8_audio_bytes():
    # A test can register UTF-8 "audio" and get exactly that transcript back, so
    # the whole voice->text->ordering path is assertable without a real provider.
    t = FakeTranscriber()
    assert await t.transcribe(b"two chicken biryani") == "two chicken biryani"


async def test_fake_falls_back_to_canned_for_binary_or_empty():
    t = FakeTranscriber()
    assert await t.transcribe(b"") == FakeTranscriber.canned
    assert await t.transcribe(b"\x00\x01\xff\xfe") == FakeTranscriber.canned


def test_factory_returns_fake_by_default():
    # conftest pins APP_STT_PROVIDER=fake.
    assert isinstance(get_transcriber(), FakeTranscriber)


def test_factory_unknown_provider_raises(monkeypatch):
    get_transcriber.cache_clear()
    import app.speech.factory as factory

    class _S:
        stt_provider = "nope"

    monkeypatch.setattr(factory, "get_settings", lambda: _S())
    with pytest.raises(ValueError, match="Unknown STT provider"):
        get_transcriber()
    get_transcriber.cache_clear()  # don't leak the bad provider to other tests
