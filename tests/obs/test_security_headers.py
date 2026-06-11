"""Security headers and CORS tests (P7-T13)."""
import pytest

pytestmark = pytest.mark.asyncio


async def test_security_headers_present(client):
    """Every response must carry the mandatory security headers including CSP."""
    r = await client.get("/health")
    h = {k.lower(): v for k, v in r.headers.items()}
    assert h.get("x-content-type-options") == "nosniff"
    assert h.get("x-frame-options") == "DENY"
    assert "referrer-policy" in h
    assert "content-security-policy" in h


async def test_csp_header_value(client):
    """CSP must restrict all source directives and forbid framing."""
    r = await client.get("/health")
    csp = r.headers.get("content-security-policy", "")
    assert "default-src 'none'" in csp
    assert "frame-ancestors 'none'" in csp


async def test_csp_allows_spa_assets_on_dashboard_paths(client):
    """Non-API (SPA) paths must NOT use default-src 'none' — otherwise the browser
    blocks the dashboard's own bundled JS/CSS and renders a blank page. The CSP
    must permit self scripts/styles plus Google Fonts and map tiles."""
    r = await client.get("/login")
    csp = r.headers.get("content-security-policy", "")
    assert "default-src 'none'" not in csp
    assert "script-src 'self'" in csp
    assert "https://fonts.googleapis.com" in csp
    assert "img-src 'self' data: blob: https:" in csp
    assert "frame-ancestors 'none'" in csp


async def test_csp_strict_on_api_paths(client):
    """API/webhook/machine endpoints stay fully locked down."""
    for path in ("/health", "/api/v1/auth/login", "/webhooks/whatsapp"):
        r = await client.get(path)
        csp = r.headers.get("content-security-policy", "")
        assert "default-src 'none'" in csp, path


async def test_cors_disallows_unlisted_origin(client):
    """An origin not in cors_allow_origins must NOT receive an ACAO header."""
    r = await client.get("/health", headers={"Origin": "https://evil.example"})
    # When cors_allow_origins is empty (default in tests), CORSMiddleware is not
    # mounted at all — so the header is simply absent.
    acao = r.headers.get("access-control-allow-origin", "")
    assert "evil.example" not in acao


async def test_hsts_not_emitted_by_default(client):
    """HSTS header must be absent when hsts_enabled=False (the default)."""
    r = await client.get("/health")
    assert "strict-transport-security" not in {k.lower() for k in r.headers}
