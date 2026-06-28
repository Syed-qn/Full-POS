"""Read a Meta Commerce catalogue's products via the Graph API.

Used ONLY by the OPS "Sync from Meta" flow. Needs a system-user token with the
``catalog_management`` permission (``settings.wa_catalog_token``) — the WhatsApp
messaging token cannot read catalogues.

    GET /{catalog_id}/products?fields=...&limit=...&access_token=...

Follows the project's Graph conventions (version from settings, bearer token via
SecretStr, httpx.AsyncClient with a timeout). Paginates through ``paging.next``.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

import httpx

from app.config import get_settings

_FIELDS = "id,retailer_id,name,description,price,currency,availability,image_url,category"
# Hard cap so a misconfigured catalogue can't loop forever; WhatsApp shows <=30 anyway.
_MAX_PAGES = 20
_PER_PAGE = 100


class CatalogReadError(RuntimeError):
    """Raised when the Graph API rejects the catalogue read (bad token / perms / id)."""


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
    raw: dict


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
        raw=p,
    )


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
