"""OPS 'Sync from Meta': pull catalogue products → local mirror, and inject them in chat.

Meta is mocked (no network) — meta_client.fetch_catalog_products is monkeypatched.
"""
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.catalog import sync_service
from app.catalog.meta_client import CatalogReadError, MetaProduct
from app.catalog.models import CatalogProduct
from app.catalog.sync_service import sync_catalog_from_meta
from app.outbox.models import OutboxMessage


def _mp(retailer_id, name, price, cat=None):
    return MetaProduct(
        retailer_id=retailer_id, meta_product_id=f"meta-{retailer_id}", name=name,
        price_aed=Decimal(str(price)), currency="AED", availability="in stock",
        image_url=None, category=cat, raw={"retailer_id": retailer_id},
    )


def _patch_meta(monkeypatch, products):
    async def _fake(catalog_id):  # noqa: ARG001
        return products
    monkeypatch.setattr(sync_service, "fetch_catalog_products", _fake)


async def test_sync_upserts_and_deactivates(db_session, restaurant, monkeypatch):
    restaurant.settings = {**restaurant.settings, "catalog_id": "CAT1",
                           "catalog_ordering_enabled": True}
    await db_session.commit()

    # First sync: two products added.
    _patch_meta(monkeypatch, [_mp("r1", "Biryani", 30, "Rice"), _mp("r2", "Mint", 12, "Drinks")])
    res = await sync_catalog_from_meta(db_session, restaurant_id=restaurant.id)
    await db_session.commit()
    assert (res.added, res.updated, res.deactivated, res.total_active) == (2, 0, 0, 2)
    rows = (await db_session.scalars(
        select(CatalogProduct).where(CatalogProduct.restaurant_id == restaurant.id)
    )).all()
    assert {r.retailer_id for r in rows} == {"r1", "r2"}
    assert {r.name for r in rows} == {"Biryani", "Mint"}
    assert next(r for r in rows if r.retailer_id == "r1").price_aed == Decimal("30.00")

    # Second sync: r2 gone from Meta, r1 price changed → r1 updated, r2 deactivated.
    _patch_meta(monkeypatch, [_mp("r1", "Biryani", 28, "Rice")])
    res2 = await sync_catalog_from_meta(db_session, restaurant_id=restaurant.id)
    await db_session.commit()
    assert (res2.added, res2.updated, res2.deactivated) == (0, 1, 1)
    r1 = await db_session.scalar(
        select(CatalogProduct).where(CatalogProduct.retailer_id == "r1")
    )
    r2 = await db_session.scalar(
        select(CatalogProduct).where(CatalogProduct.retailer_id == "r2")
    )
    assert r1.price_aed == Decimal("28.00") and r1.is_active is True
    assert r2.is_active is False  # vanished from Meta → deactivated, not deleted


async def test_sync_requires_catalog_id(db_session, restaurant, monkeypatch):
    _patch_meta(monkeypatch, [])
    with pytest.raises(CatalogReadError, match="Catalog ID"):
        await sync_catalog_from_meta(db_session, restaurant_id=restaurant.id)


async def test_send_catalog_uses_synced_products(db_session, restaurant):
    """With synced products present, the chat catalogue is built from THEM (Meta source
    of truth) — not from dish↔retailer_id links."""
    from app.catalog.service import send_catalog

    restaurant.settings = {**restaurant.settings, "catalog_id": "CAT1",
                           "catalog_ordering_enabled": True}
    db_session.add(CatalogProduct(
        restaurant_id=restaurant.id, retailer_id="r1", name="Biryani",
        price_aed=Decimal("30.00"), currency="AED", availability="in stock",
        category="Rice", is_active=True, raw={},
    ))
    db_session.add(CatalogProduct(
        restaurant_id=restaurant.id, retailer_id="r2", name="Mint",
        price_aed=Decimal("12.00"), currency="AED", availability="in stock",
        category="Drinks", is_active=False, raw={},  # inactive → excluded
    ))
    await db_session.commit()

    sent = await send_catalog(db_session, restaurant_id=restaurant.id, to_phone="+971501110001")
    await db_session.commit()
    assert sent is True
    msg = (await db_session.scalars(
        select(OutboxMessage).where(OutboxMessage.to_phone == "+971501110001")
    )).one()
    retailer_ids = {
        it["product_retailer_id"]
        for s in msg.payload["sections"] for it in s["product_items"]
    }
    assert retailer_ids == {"r1"}  # only the ACTIVE synced product


async def test_sync_endpoint_and_list(client, db_session, monkeypatch, auth_headers):
    """POST /catalog/sync pulls + returns products; GET /catalog/products lists them."""
    from app.identity.models import Restaurant

    # auth_headers signs up its OWN restaurant — configure THAT one.
    rest = await db_session.scalar(
        select(Restaurant).where(Restaurant.phone == "+971501234567")
    )
    rest.settings = {**(rest.settings or {}), "catalog_id": "CAT1",
                     "catalog_ordering_enabled": True}
    await db_session.commit()
    _patch_meta(monkeypatch, [_mp("r1", "Biryani", 30, "Rice")])

    r = await client.post("/api/v1/catalog/sync", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["added"] == 1 and body["total_active"] == 1
    assert body["products"][0]["retailer_id"] == "r1"

    lst = await client.get("/api/v1/catalog/products", headers=auth_headers)
    assert lst.status_code == 200
    assert [p["retailer_id"] for p in lst.json()] == ["r1"]
