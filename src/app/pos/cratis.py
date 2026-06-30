"""Cratis POS adapter.

    GET {base_url}?arg1=menu&account={account}&location={location}

Returns ``text/plain`` JSON ``{"products": [...], "categories": [...]}``. We normalize
into :class:`PosMenu`. Prices are parsed to Decimal; AED is assumed (hard-coded for now).
"""
from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation

import httpx

from app.config import get_settings
from app.pos.port import PosCategory, PosMenu, PosProduct, PosProvider

logger = logging.getLogger(__name__)


class PosFetchError(RuntimeError):
    """Raised when the POS endpoint is unreachable or returns an unusable payload."""


def _to_decimal(value) -> Decimal | None:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _int(value, default: int = 1) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def parse_cratis_menu(data: dict) -> PosMenu:
    """Pure parse of the Cratis JSON body into a normalized PosMenu (no I/O)."""
    categories = [
        PosCategory(pos_category_id=str(c.get("posCategoryId") or ""), name=str(c.get("name") or "").strip())
        for c in (data.get("categories") or [])
        if c.get("posCategoryId")
    ]
    products: list[PosProduct] = []
    for p in data.get("products") or []:
        pid = str(p.get("posProductId") or "").strip()
        if not pid:
            continue
        price = _to_decimal(p.get("price"))
        if price is None:
            continue
        # posCategoryIds is a single id string here (no commas observed); take the first.
        cat_raw = str(p.get("posCategoryIds") or "").split(",")[0].strip() or None
        name_tr = p.get("nameTranslations") or {}
        products.append(
            PosProduct(
                pos_product_id=pid,
                name=str(p.get("name") or "Item").strip(),
                price=price,
                category_id=cat_raw,
                description=(str(p.get("description") or "").strip() or None),
                name_ar=(str(name_tr.get("ar") or "").strip() or None),
                plu=(str(p.get("plu") or "").strip() or None),
                product_type=_int(p.get("productType"), 1),
            )
        )
    return PosMenu(products=products, categories=categories)


class CratisPosAdapter(PosProvider):
    async def fetch_menu(
        self, *, account: str, location: str, base_url: str | None = None
    ) -> PosMenu:
        base = (base_url or get_settings().pos_base_url or "").strip()
        if not base:
            raise PosFetchError("POS base URL is not configured.")
        params = {"arg1": "menu", "account": account, "location": location}
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.get(base, params=params)
        except httpx.HTTPError as exc:
            raise PosFetchError(f"POS request failed: {exc}") from exc
        if resp.status_code >= 400:
            raise PosFetchError(f"POS returned HTTP {resp.status_code}")
        try:
            # Endpoint sends text/plain; parse the body as JSON explicitly.
            data = resp.json()
        except ValueError as exc:
            raise PosFetchError(f"POS returned non-JSON body: {exc}") from exc
        if not isinstance(data, dict):
            raise PosFetchError("POS payload is not an object")
        menu = parse_cratis_menu(data)
        logger.info(
            "fetched POS menu account=%s location=%s: %d products, %d categories",
            account, location, len(menu.products), len(menu.categories),
        )
        return menu
