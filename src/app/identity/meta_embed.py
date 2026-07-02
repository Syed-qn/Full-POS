"""WhatsApp Embedded Signup — the "Connect with Facebook" popup backend.

The frontend launches Meta's Embedded Signup popup for the tech-provider app
(global wa_app_id + wa_es_config_id). When the manager finishes, the popup hands
the browser a short-lived OAuth ``code`` plus the business's ``phone_number_id`` and
``waba_id``. The browser POSTs those here; we exchange the code for that business's
own long-lived access token, subscribe our app to the WABA (so we receive its
inbound webhooks), and return the creds for the caller to store per-restaurant.

All Graph calls go through httpx and are easily monkeypatched in tests.
"""
from __future__ import annotations

import logging

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


class MetaEmbedError(RuntimeError):
    """Raised when the Embedded Signup code exchange fails."""


def _graph_base() -> str:
    settings = get_settings()
    return f"https://graph.facebook.com/{settings.graph_api_version}"


async def exchange_code_for_token(code: str) -> str:
    """Exchange an Embedded Signup OAuth code for the business's access token.

    Returns the access token string. Raises MetaEmbedError on any failure.
    """
    settings = get_settings()
    app_id = settings.wa_app_id
    app_secret = settings.wa_app_secret.get_secret_value()
    if not (app_id and app_secret):
        raise MetaEmbedError("Meta app not configured (wa_app_id / wa_app_secret)")

    url = f"{_graph_base()}/oauth/access_token"
    params = {
        "client_id": app_id,
        "client_secret": app_secret,
        "code": code,
    }
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(url, params=params)
    except httpx.HTTPError as exc:  # network-level
        raise MetaEmbedError(f"token exchange request failed: {exc}") from exc
    if resp.status_code != 200:
        raise MetaEmbedError(
            f"token exchange failed (HTTP {resp.status_code}): {resp.text[:300]}"
        )
    token = (resp.json() or {}).get("access_token")
    if not token:
        raise MetaEmbedError("token exchange returned no access_token")
    return token


async def subscribe_app_to_waba(waba_id: str, access_token: str) -> bool:
    """Subscribe our app to the business's WABA so we receive its inbound webhooks.

    Best-effort: returns True on success, False (logged) on failure — a manager can
    still fix subscription in Meta later, and this must never block connecting.
    """
    if not waba_id:
        return False
    url = f"{_graph_base()}/{waba_id}/subscribed_apps"
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                url, headers={"Authorization": f"Bearer {access_token}"}
            )
        if resp.status_code == 200 and (resp.json() or {}).get("success"):
            return True
        logger.warning(
            "subscribe_app_to_waba non-success waba=%s http=%s body=%s",
            waba_id, resp.status_code, resp.text[:300],
        )
        return False
    except httpx.HTTPError as exc:
        logger.warning("subscribe_app_to_waba request failed waba=%s: %s", waba_id, exc)
        return False


async def fetch_waba_catalog_id(waba_id: str, access_token: str) -> str:
    """Return the Commerce catalog connected to the WABA, or '' if none/error.

    Best-effort: a store that hasn't linked a catalog yet just yields '' and the
    manager sets it manually later — never raises.
    """
    if not waba_id:
        return ""
    url = f"{_graph_base()}/{waba_id}/product_catalogs"
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(
                url, headers={"Authorization": f"Bearer {access_token}"}
            )
        if resp.status_code != 200:
            logger.warning(
                "fetch_waba_catalog_id non-200 waba=%s http=%s body=%s",
                waba_id, resp.status_code, resp.text[:300],
            )
            return ""
        data = (resp.json() or {}).get("data") or []
        if isinstance(data, list) and data:
            return str(data[0].get("id") or "").strip()
        return ""
    except httpx.HTTPError as exc:
        logger.warning("fetch_waba_catalog_id request failed waba=%s: %s", waba_id, exc)
        return ""


async def connect_embedded_signup(
    *, code: str, phone_number_id: str, waba_id: str
) -> dict[str, str]:
    """Full Embedded Signup connect: exchange code, subscribe WABA, auto-detect the
    Commerce catalog, and return creds shaped for apply_meta_settings():
    {wa_phone_number_id, wa_business_account_id, wa_access_token[, catalog_id]}.

    catalog_id is included only when the WABA has a linked catalog — so we never
    wipe an existing catalog_id for a store that hasn't connected one via Meta.
    """
    token = await exchange_code_for_token(code)
    await subscribe_app_to_waba(waba_id, token)
    creds: dict[str, str] = {
        "wa_phone_number_id": (phone_number_id or "").strip(),
        "wa_business_account_id": (waba_id or "").strip(),
        "wa_access_token": token,
    }
    catalog_id = await fetch_waba_catalog_id(waba_id, token)
    if catalog_id:
        creds["catalog_id"] = catalog_id
    return creds
