"""Resumable Meta image header upload (httpx mock)."""
import pytest

pytestmark = pytest.mark.asyncio


async def test_meta_image_upload_resumable_mock_httpx(monkeypatch):
    from app.marketing.template_meta import MetaTemplateProvider

    class _Resp:
        def __init__(self, payload: dict, content: bytes = b""):
            self._payload = payload
            self.content = content

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return self._payload

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url: str):
            return _Resp({}, content=b"fake-image-bytes")

        async def post(self, url: str, content=None, headers=None):
            if "uploads" in url:
                return _Resp({"id": "upload-session-1"})
            return _Resp({"h": "h:mock-handle-abc"})

    monkeypatch.setattr("app.marketing.template_meta.httpx.AsyncClient", _Client)
    monkeypatch.setenv("APP_MARKETING_SEND_DRY_RUN", "false")
    monkeypatch.setenv("APP_WA_APP_ID", "app-123")
    monkeypatch.setenv("APP_WA_ACCESS_TOKEN", "token-xyz")
    monkeypatch.setenv("APP_WA_BUSINESS_ACCOUNT_ID", "waba-1")
    from app.config import get_settings

    get_settings.cache_clear()
    try:
        prov = MetaTemplateProvider()
        handle = await prov._upload_image_header("https://example.com/header.jpg")
        assert handle == "h:mock-handle-abc"
    finally:
        get_settings.cache_clear()