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


async def fetch_waba_owner_business(waba_id: str, access_token: str) -> str:
    """Return the id of the business portfolio that owns the WABA, or ''.

    Needed to create a catalog under the right business. Best-effort — never raises.
    """
    if not waba_id:
        return ""
    url = f"{_graph_base()}/{waba_id}"
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(
                url,
                params={"fields": "owner_business_info,on_behalf_of_business_info"},
                headers={"Authorization": f"Bearer {access_token}"},
            )
        if resp.status_code != 200:
            logger.warning(
                "fetch_waba_owner_business non-200 waba=%s http=%s body=%s",
                waba_id, resp.status_code, resp.text[:300],
            )
            return ""
        body = resp.json() or {}
        for key in ("owner_business_info", "on_behalf_of_business_info"):
            info = body.get(key) or {}
            bid = str(info.get("id") or "").strip()
            if bid:
                return bid
        return ""
    except httpx.HTTPError as exc:
        logger.warning("fetch_waba_owner_business request failed waba=%s: %s", waba_id, exc)
        return ""


async def create_owned_catalog(business_id: str, access_token: str, *, name: str) -> str:
    """Create a Commerce catalog under the business portfolio; return its id or ''.

    Best-effort — a failure just leaves the store without a catalog (set later),
    never blocks connecting. Requires catalog_management + business_management on
    the token (granted by the tech-provider Embedded Signup).
    """
    if not business_id:
        return ""
    url = f"{_graph_base()}/{business_id}/owned_product_catalogs"
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                url,
                data={"name": name.strip() or "WhatsApp Catalog", "vertical": "commerce"},
                headers={"Authorization": f"Bearer {access_token}"},
            )
        if resp.status_code != 200:
            logger.warning(
                "create_owned_catalog non-200 business=%s http=%s body=%s",
                business_id, resp.status_code, resp.text[:300],
            )
            return ""
        return str((resp.json() or {}).get("id") or "").strip()
    except httpx.HTTPError as exc:
        logger.warning("create_owned_catalog request failed business=%s: %s", business_id, exc)
        return ""


async def connect_catalog_to_waba(waba_id: str, catalog_id: str, access_token: str) -> bool:
    """Connect a catalog to the WABA so it's usable for WhatsApp commerce.

    Best-effort — POST /{waba_id}/product_catalogs {catalog_id}. Returns True on
    success, False (logged) otherwise. Never raises.
    """
    if not (waba_id and catalog_id):
        return False
    url = f"{_graph_base()}/{waba_id}/product_catalogs"
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                url,
                data={"catalog_id": catalog_id},
                headers={"Authorization": f"Bearer {access_token}"},
            )
        if resp.status_code == 200 and (resp.json() or {}).get("success", True):
            return True
        logger.warning(
            "connect_catalog_to_waba non-success waba=%s catalog=%s http=%s body=%s",
            waba_id, catalog_id, resp.status_code, resp.text[:300],
        )
        return False
    except httpx.HTTPError as exc:
        logger.warning(
            "connect_catalog_to_waba request failed waba=%s catalog=%s: %s",
            waba_id, catalog_id, exc,
        )
        return False


async def ensure_waba_catalog(
    waba_id: str, access_token: str, *, business_name: str = ""
) -> str:
    """Return a catalog id connected to the WABA, creating one if none exists.

    New restaurants arrive from Embedded Signup with no catalog — so a customer's
    catalogue-ordering can't work until one is made. Rather than sending the manager
    to Commerce Manager, we auto-provision during connect: reuse an existing linked
    catalog if present, otherwise create one under the WABA's owner business and
    connect it. Entirely best-effort — any failure yields '' and the manager can
    still set a catalog later; it never blocks the WhatsApp connection.
    """
    existing = await fetch_waba_catalog_id(waba_id, access_token)
    if existing:
        return existing
    business_id = await fetch_waba_owner_business(waba_id, access_token)
    if not business_id:
        return ""
    name = f"{business_name} WhatsApp".strip() if business_name else "WhatsApp Catalog"
    catalog_id = await create_owned_catalog(business_id, access_token, name=name)
    if not catalog_id:
        return ""
    await connect_catalog_to_waba(waba_id, catalog_id, access_token)
    return catalog_id


async def fetch_display_phone_number(phone_number_id: str, access_token: str) -> str:
    """Return the E.164 display number for a WhatsApp phone_number_id, or ''.

    This is the number customers actually message — the INBOUND routing key. We
    read it from Meta rather than trusting anything typed at signup, so a
    restaurant's stored phone always equals its real WhatsApp number.
    """
    if not phone_number_id:
        return ""
    url = f"{_graph_base()}/{phone_number_id}"
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(
                url,
                params={"fields": "display_phone_number"},
                headers={"Authorization": f"Bearer {access_token}"},
            )
        if resp.status_code != 200:
            logger.warning(
                "fetch_display_phone_number non-200 pid=%s http=%s body=%s",
                phone_number_id, resp.status_code, resp.text[:300],
            )
            return ""
        return str((resp.json() or {}).get("display_phone_number") or "").strip()
    except httpx.HTTPError as exc:
        logger.warning(
            "fetch_display_phone_number request failed pid=%s: %s", phone_number_id, exc
        )
        return ""


async def connect_embedded_signup(
    *, code: str, phone_number_id: str, waba_id: str, business_name: str = ""
) -> dict[str, str]:
    """Full Embedded Signup connect: exchange code, subscribe WABA, ensure a Commerce
    catalog exists (auto-create if none), and return creds shaped for
    apply_meta_settings():
    {wa_phone_number_id, wa_business_account_id, wa_access_token[, catalog_id]}.

    catalog_id is included only when the WABA ends up with a linked catalog — either
    one it already had, or one we just auto-provisioned — so we never wipe an
    existing catalog_id nor set an empty one for a store where provisioning failed.
    """
    token = await exchange_code_for_token(code)
    await subscribe_app_to_waba(waba_id, token)
    creds: dict[str, str] = {
        "wa_phone_number_id": (phone_number_id or "").strip(),
        "wa_business_account_id": (waba_id or "").strip(),
        "wa_access_token": token,
    }
    catalog_id = await ensure_waba_catalog(waba_id, token, business_name=business_name)
    if catalog_id:
        creds["catalog_id"] = catalog_id
    # The real WhatsApp display number → becomes the restaurant's inbound routing
    # phone. Returned under a non-settings key; the router applies it to the column.
    display = await fetch_display_phone_number(phone_number_id, token)
    if display:
        creds["display_phone_number"] = display
    return creds
