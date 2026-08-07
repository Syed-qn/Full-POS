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

    Uses the app's default callback URL (configured in Meta Developer Console).
    Per-WABA ``override_callback_uri`` is intentionally NOT set: production showed
    Biryani (no override) receiving webhooks while Lims (with override) got ✓✓
    delivery but zero inbound events — override can silently break multi-tenant
    routing when verify-token or callback state drifts.

    Best-effort: returns True on success, False (logged) on failure — a manager can
    still fix subscription in Meta later, and this must never block connecting.
    """
    if not waba_id:
        return False
    url = f"{_graph_base()}/{waba_id}/subscribed_apps"
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                url,
                headers={"Authorization": f"Bearer {access_token}"},
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


async def unsubscribe_app_from_waba(waba_id: str, access_token: str) -> bool:
    """Remove our app from the WABA so Embedded Signup can connect again.

    Meta's popup shows "already connected" while subscribed_apps still lists our app
    — even after the dashboard disconnect clears local creds. Best-effort.
    """
    if not waba_id:
        return False
    url = f"{_graph_base()}/{waba_id}/subscribed_apps"
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.delete(
                url,
                headers={"Authorization": f"Bearer {access_token}"},
            )
        if resp.status_code == 200 and (resp.json() or {}).get("success"):
            return True
        logger.warning(
            "unsubscribe_app_from_waba non-success waba=%s http=%s body=%s",
            waba_id, resp.status_code, resp.text[:300],
        )
        return False
    except httpx.HTTPError as exc:
        logger.warning(
            "unsubscribe_app_from_waba request failed waba=%s: %s", waba_id, exc
        )
        return False


async def read_waba_catalog_id(waba_id: str, access_token: str) -> str | None:
    """The catalog attached to the WABA: an id, '' for confirmed-none, None if we
    could not tell.

    The three-way answer matters. ``fetch_waba_catalog_id`` collapses a failed read
    into '', which is indistinguishable from "nothing is attached" — and callers that
    act on that difference will do the wrong thing (prod, La Cafe Aug 2026: a timed-out
    read looked like an empty WABA, so the switch skipped the unlink and Meta refused
    the link with 2388027 "maximum one product catalogue").
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
                "read_waba_catalog_id non-200 waba=%s http=%s body=%s",
                waba_id, resp.status_code, resp.text[:300],
            )
            return None
        data = (resp.json() or {}).get("data") or []
        if isinstance(data, list) and data:
            return str(data[0].get("id") or "").strip()
        # The edge listed nothing. That is NOT proof of an empty WABA: prod (La Cafe,
        # Aug 2026) had this edge return [] while POST refused with 2388027 "maximum
        # one product catalogue". Ask the node itself as a second opinion.
        return await _read_catalog_via_node(waba_id, access_token)
    except httpx.HTTPError as exc:
        logger.warning("read_waba_catalog_id request failed waba=%s: %s", waba_id, exc)
        return None


async def _read_catalog_via_node(waba_id: str, access_token: str) -> str | None:
    """Second opinion: GET /{waba_id}?fields=product_catalogs.

    Some WABAs enumerate nothing on the /product_catalogs edge yet still report a
    linked catalog on the node's field expansion. Returns an id, '' for a confirmed
    empty node, or None when the call itself fails.
    """
    url = f"{_graph_base()}/{waba_id}"
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(
                url,
                params={"fields": "product_catalogs{id,name}"},
                headers={"Authorization": f"Bearer {access_token}"},
            )
        if resp.status_code != 200:
            logger.warning(
                "_read_catalog_via_node non-200 waba=%s http=%s body=%s",
                waba_id, resp.status_code, resp.text[:300],
            )
            return None
        body = resp.json() or {}
        data = ((body.get("product_catalogs") or {}).get("data")) or []
        if isinstance(data, list) and data:
            cid = str(data[0].get("id") or "").strip()
            logger.info("_read_catalog_via_node found %s on waba=%s", cid, waba_id)
            return cid
        return ""
    except httpx.HTTPError as exc:
        logger.warning("_read_catalog_via_node request failed waba=%s: %s", waba_id, exc)
        return None


async def fetch_waba_catalog_id(waba_id: str, access_token: str) -> str:
    """Return the Commerce catalog connected to the WABA, or '' if none/error.

    Kept for callers that only need "is there one" and treat failure as absent.
    Anything that MUTATES the link must use :func:`read_waba_catalog_id` instead so
    it can tell "none" from "unknown".
    """
    return await read_waba_catalog_id(waba_id, access_token) or ""


async def register_phone_number(
    phone_number_id: str, access_token: str, pin: str
) -> bool:
    """Register (activate) the number on the Cloud API so it can send/receive.

    Embedded Signup often leaves a number ``status=PENDING`` (not messageable —
    customers see "invite to WhatsApp"). POST /{pid}/register with a 6-digit 2FA pin
    flips it to CONNECTED. Best-effort: returns True on success, False (logged) on
    failure — never raises, never blocks the connection. A number already registered
    with a DIFFERENT pin returns False (expected on reconnect); it's already live.
    """
    if not (phone_number_id and pin):
        return False
    url = f"{_graph_base()}/{phone_number_id}/register"
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                url,
                data={"messaging_product": "whatsapp", "pin": pin},
                headers={"Authorization": f"Bearer {access_token}"},
            )
        if resp.status_code == 200 and (resp.json() or {}).get("success"):
            return True
        logger.warning(
            "register_phone_number non-success pid=%s http=%s body=%s",
            phone_number_id, resp.status_code, resp.text[:300],
        )
        return False
    except httpx.HTTPError as exc:
        logger.warning("register_phone_number request failed pid=%s: %s", phone_number_id, exc)
        return False


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


async def list_owned_catalogs(business_id: str, access_token: str) -> list[dict]:
    """Return the catalogs owned by a business as [{'id','name'}], newest-id first.

    Used to pick up the catalog a manager just shared with our app during Embedded
    Signup (selecting a catalog in the popup shares it with the app but does NOT
    attach it to the WABA — we attach it ourselves). Best-effort — returns [] on error.

    NOTE: our system-user token CANNOT create a catalog (Meta requires a human
    business admin — POST owned_product_catalogs → code 10 "aren't an admin"). It
    can only read + attach. So creation stays a one-time human step; everything
    after (attach + product sync) is automated.
    """
    if not business_id:
        return []
    # A business portfolio can hold catalogs on two different edges: ones it OWNS,
    # and ones SHARED into it from another business ("client" catalogs). Commerce
    # Manager lists both together, so querying only owned_product_catalogs made a
    # shared catalog invisible in the picker even though the manager can see it.
    cats: list[dict] = []
    seen: set[str] = set()
    for edge in ("owned_product_catalogs", "client_product_catalogs"):
        url = f"{_graph_base()}/{business_id}/{edge}"
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.get(
                    url,
                    params={"fields": "id,name", "limit": 100},
                    headers={"Authorization": f"Bearer {access_token}"},
                )
            if resp.status_code != 200:
                logger.warning(
                    "list_owned_catalogs non-200 business=%s edge=%s http=%s body=%s",
                    business_id, edge, resp.status_code, resp.text[:300],
                )
                continue
            for c in (resp.json() or {}).get("data") or []:
                cid = str(c.get("id") or "")
                if cid and cid not in seen:
                    seen.add(cid)
                    cats.append({"id": cid, "name": c.get("name") or ""})
        except httpx.HTTPError as exc:
            logger.warning(
                "list_owned_catalogs request failed business=%s edge=%s: %s",
                business_id, edge, exc,
            )
    # Highest numeric id ≈ most recently created — the one the manager just made.
    cats.sort(key=lambda c: int(c["id"]) if c["id"].isdigit() else 0, reverse=True)
    return cats


# Meta: "WhatsApp Business account should have maximum one product catalogue".
# Returned when a catalog is already attached — proof one exists even if our read
# of the WABA failed.
_ALREADY_HAS_CATALOG_SUBCODE = 2388027


async def link_catalog_to_waba(
    waba_id: str, catalog_id: str, access_token: str
) -> tuple[bool, int | None]:
    """Attach a catalog, returning (ok, error_subcode).

    The subcode is what lets the caller distinguish "Meta says one is already
    attached" from any other failure, and recover instead of giving up.
    """
    if not (waba_id and catalog_id):
        return False, None
    url = f"{_graph_base()}/{waba_id}/product_catalogs"
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                url,
                data={"catalog_id": catalog_id},
                headers={"Authorization": f"Bearer {access_token}"},
            )
        if resp.status_code == 200 and (resp.json() or {}).get("success", True):
            return True, None
        subcode: int | None = None
        try:
            subcode = (resp.json() or {}).get("error", {}).get("error_subcode")
        except Exception:  # noqa: BLE001 — non-JSON error body
            subcode = None
        logger.warning(
            "link_catalog_to_waba non-success waba=%s catalog=%s http=%s body=%s",
            waba_id, catalog_id, resp.status_code, resp.text[:300],
        )
        return False, subcode
    except httpx.HTTPError as exc:
        logger.warning(
            "link_catalog_to_waba request failed waba=%s catalog=%s: %s",
            waba_id, catalog_id, exc,
        )
        return False, None


async def connect_catalog_to_waba(waba_id: str, catalog_id: str, access_token: str) -> bool:
    """Connect a catalog to the WABA so it's usable for WhatsApp commerce.

    Best-effort bool wrapper over :func:`link_catalog_to_waba`. Never raises.
    """
    ok, _ = await link_catalog_to_waba(waba_id, catalog_id, access_token)
    return ok


async def disconnect_catalog_from_waba(waba_id: str, catalog_id: str, access_token: str) -> bool:
    """Unlink a catalog from the WABA — DELETE /{waba_id}/product_catalogs {catalog_id}.

    Required before linking a DIFFERENT catalog (Meta enforces one-catalog-per-WABA).
    Best-effort: returns True on success, False (logged) otherwise. Never raises.
    """
    if not (waba_id and catalog_id):
        return False
    url = f"{_graph_base()}/{waba_id}/product_catalogs"
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.request(
                "DELETE",
                url,
                params={"catalog_id": catalog_id},
                headers={"Authorization": f"Bearer {access_token}"},
            )
        if resp.status_code == 200 and (resp.json() or {}).get("success", True):
            return True
        logger.warning(
            "disconnect_catalog_from_waba non-success waba=%s catalog=%s http=%s body=%s",
            waba_id, catalog_id, resp.status_code, resp.text[:300],
        )
        return False
    except httpx.HTTPError as exc:
        logger.warning(
            "disconnect_catalog_from_waba request failed waba=%s catalog=%s: %s",
            waba_id, catalog_id, exc,
        )
        return False


async def switch_waba_catalog(waba_id: str, new_catalog_id: str, access_token: str) -> bool:
    """Make ``new_catalog_id`` the WABA's connected catalog, replacing whatever is linked.

    Meta rejects linking a second catalog (one-per-WABA), so we UNLINK the current one
    first, then LINK the new one, verifying the result. If the new link fails we roll back
    to the old catalog so the store is never left with no menu. Returns True only when the
    new catalog is confirmed attached. Never raises.
    """
    if not (waba_id and new_catalog_id):
        return False
    # None = we could not read the WABA. NOT the same as "nothing attached", and
    # acting as if it were is what broke this before.
    current = await read_waba_catalog_id(waba_id, access_token)
    if current == new_catalog_id:
        return True  # already the connected one — idempotent
    if current:
        await disconnect_catalog_from_waba(waba_id, current, access_token)

    linked, subcode = await link_catalog_to_waba(waba_id, new_catalog_id, access_token)

    # Meta says one is already attached — so something IS there even though our read
    # said otherwise (or failed). Re-read to identify it, unlink it, and try once more.
    if not linked and subcode == _ALREADY_HAS_CATALOG_SUBCODE:
        actual = await read_waba_catalog_id(waba_id, access_token)
        if actual == new_catalog_id:
            return True  # it was already ours; the first read simply lied
        if actual:
            logger.info(
                "switch_waba_catalog: WABA %s actually had %s attached — unlinking to "
                "make room for %s", waba_id, actual, new_catalog_id,
            )
            await disconnect_catalog_from_waba(waba_id, actual, access_token)
            current = actual  # so rollback below can restore the right one
            linked, subcode = await link_catalog_to_waba(
                waba_id, new_catalog_id, access_token
            )
        else:
            # Still can't identify it. Never delete a link we cannot name.
            logger.warning(
                "switch_waba_catalog: WABA %s reports an attached catalog we cannot "
                "read — refusing to unlink blindly", waba_id,
            )
            return False

    attached = await read_waba_catalog_id(waba_id, access_token)
    if linked and attached == new_catalog_id:
        return True
    # Roll back so we don't strand the store with no connected catalog.
    logger.warning(
        "switch_waba_catalog: link to %s not confirmed (attached=%s) — rolling back to %s",
        new_catalog_id, attached or "(none)", current or "(none)",
    )
    if current and attached != current:
        await connect_catalog_to_waba(waba_id, current, access_token)
    return False


async def enable_commerce_settings(phone_number_id: str, access_token: str) -> bool:
    """Turn on cart + catalog visibility for the phone number.

    WhatsApp's native "View catalog" message (and the cart) only render when the
    phone number's ``whatsapp_commerce_settings`` has ``is_cart_enabled`` and
    ``is_catalog_visible`` true. Embedded Signup leaves these UNSET, so a freshly
    connected store sends the welcome text but the catalog message then FAILS.
    Best-effort; never blocks connect.
    """
    if not phone_number_id:
        return False
    url = f"{_graph_base()}/{phone_number_id}/whatsapp_commerce_settings"
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                url,
                params={
                    "is_cart_enabled": "true",
                    "is_catalog_visible": "true",
                    "access_token": access_token,
                },
            )
        if resp.status_code == 200 and (resp.json() or {}).get("success"):
            return True
        logger.warning(
            "enable_commerce_settings non-success pid=%s http=%s body=%s",
            phone_number_id, resp.status_code, resp.text[:300],
        )
        return False
    except httpx.HTTPError as exc:
        logger.warning(
            "enable_commerce_settings request failed pid=%s: %s", phone_number_id, exc
        )
        return False


async def ensure_waba_catalog(
    waba_id: str, access_token: str, *, business_name: str = ""
) -> str:
    """Return the catalog id attached to the WABA, attaching a shared one if needed.

    During Embedded Signup a manager picks their catalog in the popup — but Meta only
    *shares* it with our app, it does NOT attach it to the WABA (so chat catalogue
    ordering wouldn't work). We finish the job here:

      1. If a catalog is already attached to the WABA, use it.
      2. Otherwise look at the WABA owner business's catalogs (the shared one shows up
         there) and ATTACH the most recent one to the WABA.

    We do NOT create catalogs — Meta forbids an app/system-user from creating one
    (only a human business admin can). Creation is the manager's one-time step in the
    popup / Commerce Manager; attach + later product sync are automated. Entirely
    best-effort: any failure yields '' and never blocks the WhatsApp connection.

    ``business_name`` is currently unused (kept for signature stability now that we no
    longer name a freshly-created catalog).
    """
    _ = business_name
    existing = await fetch_waba_catalog_id(waba_id, access_token)
    if existing:
        return existing
    business_id = await fetch_waba_owner_business(waba_id, access_token)
    if not business_id:
        return ""
    catalogs = await list_owned_catalogs(business_id, access_token)
    for catalog in catalogs:
        cid = catalog["id"]
        if await connect_catalog_to_waba(waba_id, cid, access_token):
            logger.info("attached shared catalog %s (%s) to waba %s", cid, catalog["name"], waba_id)
            return cid
    return ""


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
    *, code: str, phone_number_id: str, waba_id: str, business_name: str = "",
    existing_pin: str = "",
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
    # Activate the number on the Cloud API so it's messageable (ES often leaves it
    # PENDING). Reuse the stored pin on reconnect; otherwise mint one. Best-effort —
    # we persist the pin whenever we have one so a future reconnect matches Meta's 2FA.
    import secrets

    pin = existing_pin or "".join(secrets.choice("0123456789") for _ in range(6))
    registered = await register_phone_number(phone_number_id, token, pin)
    if registered or existing_pin:
        creds["wa_2fa_pin"] = pin
    catalog_id = await ensure_waba_catalog(waba_id, token, business_name=business_name)
    if catalog_id:
        creds["catalog_id"] = catalog_id
    # The real WhatsApp display number → becomes the restaurant's inbound routing
    # phone. Returned under a non-settings key; the router applies it to the column.
    display = await fetch_display_phone_number(phone_number_id, token)
    if display:
        creds["display_phone_number"] = display
    return creds
