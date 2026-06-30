"""Read a Meta Commerce catalogue's products via the Graph API.

Used ONLY by the OPS "Sync from Meta" flow. Needs a system-user token with the
``catalog_management`` permission (``settings.wa_catalog_token``) — the WhatsApp
messaging token cannot read catalogues.

    GET /{catalog_id}/products?fields=...&limit=...&access_token=...

Follows the project's Graph conventions (version from settings, bearer token via
SecretStr, httpx.AsyncClient with a timeout). Paginates through ``paging.next``.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

_FIELDS = (
    "id,retailer_id,name,description,price,currency,availability,image_url,category,"
    # image_fetch_status / review_status tell us whether Meta has finished processing
    # the product (image fetched onto Meta's CDN + approved). A product is only sendable
    # in a WhatsApp product_list once that is done — until then we keep it "in review".
    "image_fetch_status,review_status"
)
# Hard cap so a misconfigured catalogue can't loop forever; WhatsApp shows <=30 anyway.
_MAX_PAGES = 20
_PER_PAGE = 100
_BATCH_POLL_INTERVAL_S = 2.0
_BATCH_POLL_MAX_ATTEMPTS = 15


class CatalogReadError(RuntimeError):
    """Raised when the Graph API rejects the catalogue read (bad token / perms / id)."""


class CatalogWriteError(RuntimeError):
    """Raised when pushing products to Meta fails."""


@dataclass
class MetaProduct:
    retailer_id: str
    meta_product_id: str | None
    name: str
    price_aed: Decimal | None
    currency: str | None
    availability: str | None
    image_url: str | None
    category: str | None
    # Meta processing state: image_fetch_status (e.g. FETCHED / OUTDATED / FETCH_FAILED /
    # DIRECT_UPLOAD) and review_status (approved / pending / rejected / outdated).
    # Defaulted so callers that predate these fields keep working.
    image_fetch_status: str | None = None
    review_status: str | None = None
    raw: dict = field(default_factory=dict)


def format_meta_price(price_aed: Decimal, *, currency: str = "AED") -> str:
    """Meta price format: number + space + ISO 4217 code (e.g. ``22.00 AED``)."""
    return f"{price_aed:.2f} {currency}"


def _parse_price(raw_price, currency: str | None) -> Decimal | None:
    """Meta returns price as a string like 'AED30.00' (or a number). Strip any
    non-numeric prefix (currency code/symbol) and parse to a Decimal."""
    if raw_price is None:
        return None
    s = str(raw_price)
    digits = "".join(ch for ch in s if ch.isdigit() or ch in ".,").replace(",", "")
    if not digits:
        return None
    try:
        return Decimal(digits)
    except InvalidOperation:
        return None


def _to_product(p: dict) -> MetaProduct:
    currency = p.get("currency")
    return MetaProduct(
        retailer_id=str(p.get("retailer_id") or ""),
        meta_product_id=str(p["id"]) if p.get("id") else None,
        name=str(p.get("name") or "Item"),
        price_aed=_parse_price(p.get("price"), currency),
        currency=currency,
        availability=p.get("availability"),
        image_url=p.get("image_url"),
        category=p.get("category"),
        image_fetch_status=p.get("image_fetch_status"),
        review_status=p.get("review_status"),
        raw=p,
    )


# A product image is on Meta's CDN (sendable) when fetched or uploaded directly.
_IMAGE_READY = {"fetched", "direct_upload"}
# Anything else (in_progress, outdated, partial_fetch, fetch_failed, no_status, "") means
# Meta hasn't finished processing the image yet → not sendable in a product_list.
# Review states where Meta has NOT cleared the product for WhatsApp yet. "pending" is the
# Commerce-Manager "In review" state: the image may already be fetched, but the product is
# still awaiting approval and CANNOT be sent — so it stays "in review" for us too.
_REVIEW_BLOCKED = {"pending", "rejected", "outdated"}


def is_product_sendable(product: "MetaProduct") -> bool:
    """True when WhatsApp can include this product in an interactive product_list.

    Meta only serves a product card once (a) it has FETCHED the image onto its own CDN AND
    (b) the product has cleared review (not pending/rejected/outdated). Until BOTH hold, a
    product_list that contains it fails entirely (#131009 "None of the products provided
    could be sent"), so we treat it as still "in review" and exclude it.

    Falls back to inspecting the image_url host (``fbcdn.net`` == processed) when Meta
    omits ``image_fetch_status`` (older catalogues / partial field sets).
    """
    fetch = (product.image_fetch_status or "").strip().lower()
    review = (product.review_status or "").strip().lower()
    # Awaiting approval / rejected / needs re-review → keep it "in review".
    if review in _REVIEW_BLOCKED:
        return False
    if fetch:
        return fetch in _IMAGE_READY
    # No explicit status — infer from where the image is hosted.
    return "fbcdn.net" in (product.image_url or "")


def _dish_retailer_id(dish_id: int, dish_number: int | None) -> str:
    """Stable Content ID for a dish pushed to Meta."""
    num = dish_number if dish_number is not None else dish_id
    return f"dish-{dish_id}-{num}"


def build_catalog_item_data(
    *,
    name: str,
    description: str | None,
    price_aed: Decimal,
    category: str | None,
    is_available: bool,
    restaurant_name: str,
    product_link: str,
    image_link: str,
    sale_price_aed: Decimal | None = None,
    fb_product_category: str | None = None,
    condition: str | None = None,
    meta_status: str | None = None,
    brand: str | None = None,
) -> dict:
    """Build items_batch ``data`` with Meta Commerce fields.

    See https://developers.facebook.com/docs/commerce-platform/catalog/fields —
    CREATE requires title, description, availability, condition, price, link,
    image_link, and brand. The remaining args mirror the optional fields on Meta's
    "Add product" form and are emitted only when set:
      * ``sale_price_aed``      → ``sale_price`` (struck-through price in Meta)
      * ``fb_product_category`` → ``category`` (Facebook taxonomy); the internal
        menu ``category`` is always sent as ``product_type``.
      * ``condition``           → ``condition`` (defaults "new")
      * ``meta_status``         → ``visibility`` ("active"→published, else staging)
      * ``brand``               → ``brand`` override (defaults to restaurant name)
    """
    title = (name or "Item")[:200]
    desc = (description or title)[:5000]
    internal_category = (category or "Menu")[:100]
    fb_category = (fb_product_category or "").strip() or internal_category
    data = {
        "title": title,
        "description": desc,
        "availability": "in stock" if is_available else "out of stock",
        "condition": (condition or "new").strip().lower() or "new",
        "price": format_meta_price(price_aed),
        "link": product_link,
        "image_link": image_link,
        "brand": ((brand or "").strip() or restaurant_name or "Restaurant")[:100],
        # Facebook product category vs the restaurant's own menu section.
        "category": fb_category[:100],
        "product_type": internal_category,
        # active → published (live), archived → staging (hidden from shoppers).
        "visibility": "published" if (meta_status or "active") == "active" else "staging",
    }
    if sale_price_aed is not None:
        data["sale_price"] = format_meta_price(sale_price_aed)
    return data


def _collect_batch_errors(data: dict) -> list[str]:
    """Surface per-item validation errors from an items_batch response."""
    errors: list[str] = []
    for status in data.get("validation_status") or []:
        rid = status.get("retailer_id") or "?"
        for err in status.get("errors") or []:
            msg = err.get("message") or "unknown error"
            errors.append(f"{rid}: {msg}")
    return errors


async def fetch_catalog_products(catalog_id: str) -> list[MetaProduct]:
    """Read every product in ``catalog_id`` from Meta. Raises CatalogReadError on a
    Graph error (so the caller can surface a clear message). Returns [] for an empty
    catalogue."""
    settings = get_settings()
    token = settings.wa_catalog_token.get_secret_value()
    if not token:
        raise CatalogReadError(
            "Catalogue sync is not configured (APP_WA_CATALOG_TOKEN is empty)."
        )
    if not catalog_id:
        raise CatalogReadError("This restaurant has no catalog_id set.")

    base = f"https://graph.facebook.com/{settings.graph_api_version}"
    url: str | None = f"{base}/{catalog_id}/products"
    params: dict | None = {"fields": _FIELDS, "limit": _PER_PAGE, "access_token": token}

    products: list[MetaProduct] = []
    async with httpx.AsyncClient(timeout=30.0) as client:
        pages = 0
        while url and pages < _MAX_PAGES:
            resp = await client.get(url, params=params)
            params = None  # paging 'next' is a full URL with its own query string
            data = resp.json()
            if resp.status_code >= 400 or "error" in data:
                err = (data.get("error") or {}).get("message", f"HTTP {resp.status_code}")
                raise CatalogReadError(f"Meta catalogue read failed: {err}")
            for p in data.get("data", []):
                mp = _to_product(p)
                if mp.retailer_id:
                    products.append(mp)
            url = (data.get("paging") or {}).get("next")
            pages += 1
    return products


async def check_batch_request_status(catalog_id: str, handle: str) -> dict:
    """Poll Meta for async items_batch ingestion status."""
    settings = get_settings()
    token = settings.wa_catalog_token.get_secret_value()
    base = f"https://graph.facebook.com/{settings.graph_api_version}"
    url = f"{base}/{catalog_id}/check_batch_request_status"
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            url,
            params={"access_token": token, "handle": handle},
        )
        data = resp.json()
        if resp.status_code >= 400 or "error" in data:
            err = (data.get("error") or {}).get("message", f"HTTP {resp.status_code}")
            raise CatalogWriteError(f"Meta batch status check failed: {err}")
        return data


async def wait_for_batch_handles(catalog_id: str, handles: list[str]) -> None:
    """Wait until Meta finishes ingesting items_batch uploads (best-effort)."""
    if not handles:
        return
    for attempt in range(_BATCH_POLL_MAX_ATTEMPTS):
        pending = False
        for handle in handles:
            status = await check_batch_request_status(catalog_id, handle)
            state = (status.get("status") or "").lower()
            if state in {"", "in_progress", "started"}:
                pending = True
                continue
            if state == "finished":
                for err in status.get("errors") or []:
                    msg = err.get("message") or str(err)
                    raise CatalogWriteError(f"Meta batch ingest failed: {msg}")
            elif state not in {"finished"}:
                logger.warning("unexpected Meta batch status %r for handle %s", state, handle)
        if not pending:
            return
        await asyncio.sleep(_BATCH_POLL_INTERVAL_S)
    logger.warning(
        "Meta batch handles still pending after %d attempts: %s",
        _BATCH_POLL_MAX_ATTEMPTS,
        handles,
    )


async def push_products_batch(
    catalog_id: str,
    requests: list[dict],
    *,
    wait_for_ingest: bool = True,
) -> dict:
    """Push CREATE/UPDATE/DELETE batch to Meta ``/{catalog_id}/items_batch``.

    Each request: ``{"method": "CREATE"|"UPDATE"|"DELETE", "retailer_id": "...", "data": {...}}``
    """
    if not requests:
        return {"handles": [], "validation_status": []}
    # Meta rejects the ENTIRE batch if any retailer_id repeats. Dedupe defensively at
    # this single chokepoint (last occurrence wins) so no caller can ever trigger
    # "Duplicate retailer_id in batch api call", regardless of upstream data.
    deduped: dict[str, dict] = {}
    for r in requests:
        deduped[str(r.get("retailer_id") or "")] = r
    if len(deduped) < len(requests):
        logger.warning(
            "items_batch: dropped %d duplicate retailer_id request(s) before push",
            len(requests) - len(deduped),
        )
    requests = list(deduped.values())
    settings = get_settings()
    token = settings.wa_catalog_token.get_secret_value()
    if not token:
        raise CatalogWriteError(
            "Catalogue push is not configured (APP_WA_CATALOG_TOKEN is empty)."
        )
    if not catalog_id:
        raise CatalogWriteError("This restaurant has no catalog_id set.")

    base = f"https://graph.facebook.com/{settings.graph_api_version}"
    url = f"{base}/{catalog_id}/items_batch"
    # Meta's items_batch wants the retailer/Content ID as ``data.id`` — NOT a top-level
    # ``retailer_id`` (which it rejects with "Can not find required field id"). Internally
    # we key on top-level retailer_id (dedup above, "_"-prefixed UI metadata), so build
    # the wire payload here: move retailer_id into data.id and drop the internal keys.
    wire = []
    for r in requests:
        rid = str(r.get("retailer_id") or "")
        data = dict(r.get("data") or {})
        if rid:
            data["id"] = rid
        wire.append({"method": r.get("method", "UPDATE"), "data": data})
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            url,
            params={"access_token": token},
            json={"allow_upsert": True, "item_type": "PRODUCT_ITEM", "requests": wire},
        )
        data = resp.json()
        if resp.status_code >= 400 or "error" in data:
            err = (data.get("error") or {}).get("message", f"HTTP {resp.status_code}")
            raise CatalogWriteError(f"Meta catalogue push failed: {err}")
        validation_errors = _collect_batch_errors(data)
        if validation_errors:
            preview = "; ".join(validation_errors[:5])
            extra = f" (+{len(validation_errors) - 5} more)" if len(validation_errors) > 5 else ""
            # Diagnostic: surface exactly what we sent so a "Duplicate retailer_id"
            # can be traced (our batch is deduped, so a dupe here means Meta's catalog
            # already holds two products with that retailer_id).
            sent = [str((r.get("data") or {}).get("id") or "") for r in wire]
            dupes = sorted({rid for rid in sent if sent.count(rid) > 1})
            diag = f" [sent rids: {sent}; in-batch dupes: {dupes or 'none'}]"
            logger.error("items_batch rejected: %s%s", validation_errors, diag)
            raise CatalogWriteError(
                f"Meta rejected {len(validation_errors)} item(s): {preview}{extra}{diag}"
            )
        handles = data.get("handles") or []
        if wait_for_ingest and handles:
            await wait_for_batch_handles(catalog_id, handles)
        return data