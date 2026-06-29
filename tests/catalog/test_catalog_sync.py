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


async def test_sync_links_and_creates_orderable_dishes(db_session, restaurant, monkeypatch):
    """Sync must make every product ORDERABLE: link a same-named unlinked dish, and
    auto-create a dish for a product that has none. Fixes 'Lemon Mint is in the catalogue
    but the bot says we don't have it' (the dish wasn't linked to the product)."""
    from app.menu.models import Dish, Menu

    restaurant.settings = {**restaurant.settings, "catalog_id": "CAT1",
                           "catalog_ordering_enabled": True}
    menu = Menu(restaurant_id=restaurant.id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    # An existing text dish "Lemon Mint" that is NOT linked to any catalogue product.
    db_session.add(Dish(
        menu_id=menu.id, restaurant_id=restaurant.id, dish_number=2, name="Lemon Mint",
        price_aed=Decimal("12.00"), category="Drinks", is_available=True,
        name_normalized="lemon mint", catalog_retailer_id=None,
    ))
    await db_session.commit()

    # Meta has Lemon Mint (matches the dish) + a brand-new product with no dish.
    _patch_meta(monkeypatch, [
        _mp("lm1", "Lemon Mint", 12, "Drinks"),
        _mp("ns9", "New Soup", 10, "Soups"),
    ])
    res = await sync_catalog_from_meta(db_session, restaurant_id=restaurant.id)
    await db_session.commit()

    assert res.linked == 1 and res.created == 1
    # The existing Lemon Mint dish is now linked to the catalogue product.
    mint = await db_session.scalar(
        select(Dish).where(Dish.restaurant_id == restaurant.id, Dish.name == "Lemon Mint")
    )
    assert mint.catalog_retailer_id == "lm1"
    # A dish was auto-created for the product that had none, linked + orderable.
    soup = await db_session.scalar(
        select(Dish).where(Dish.restaurant_id == restaurant.id, Dish.catalog_retailer_id == "ns9")
    )
    assert soup is not None and soup.name == "New Soup" and soup.is_available is True
    assert soup.price_aed == Decimal("10.00")

    # Re-sync is idempotent: already linked → no new links/creates.
    _patch_meta(monkeypatch, [_mp("lm1", "Lemon Mint", 12, "Drinks"), _mp("ns9", "New Soup", 10, "Soups")])
    res2 = await sync_catalog_from_meta(db_session, restaurant_id=restaurant.id)
    await db_session.commit()
    assert res2.linked == 0 and res2.created == 0


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


async def test_push_dishes_includes_required_meta_fields(db_session, restaurant, monkeypatch):
    """Push must send link, image_link, brand, condition — Meta rejects CREATE without them."""
    from app.catalog.meta_client import build_catalog_item_data, format_meta_price
    from app.catalog.sync_service import push_dishes_to_meta
    from app.menu.models import Dish, Menu

    restaurant.settings = {**restaurant.settings, "catalog_id": "CAT1"}
    menu = Menu(restaurant_id=restaurant.id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    db_session.add(Dish(
        menu_id=menu.id, restaurant_id=restaurant.id, dish_number=1, name="Biryani",
        price_aed=Decimal("30.00"), category="Rice", is_available=True,
        name_normalized="biryani",
    ))
    await db_session.commit()

    captured: list[dict] = []

    async def _fake_batch(catalog_id, requests, *, wait_for_ingest=True):  # noqa: ARG001
        captured.extend(requests)
        return {"handles": [], "validation_status": []}

    monkeypatch.setattr(sync_service, "push_products_batch", _fake_batch)

    res = await push_dishes_to_meta(db_session, restaurant_id=restaurant.id)
    await db_session.commit()
    assert res.pushed == 1
    assert len(captured) == 1
    data = captured[0]["data"]
    assert data["condition"] == "new"
    assert data["brand"] == restaurant.name
    assert data["link"].startswith("http")
    assert data["image_link"].startswith("http")
    assert data["price"] == format_meta_price(Decimal("30.00"))
    assert build_catalog_item_data(
        name="X", description=None, price_aed=Decimal("1"), category="C",
        is_available=True, restaurant_name="R", product_link="http://x", image_link="http://i",
    )["title"] == "X"


async def test_push_mirrors_local_catalog_without_meta_pull(db_session, restaurant, monkeypatch):
    from app.catalog.models import CatalogProduct
    from app.catalog.sync_service import push_dishes_to_meta
    from app.menu.models import Dish, Menu

    restaurant.settings = {**restaurant.settings, "catalog_id": "CAT1"}
    menu = Menu(restaurant_id=restaurant.id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    db_session.add(Dish(
        menu_id=menu.id, restaurant_id=restaurant.id, dish_number=2, name="Mint",
        price_aed=Decimal("12.00"), category="Drinks", is_available=True,
        name_normalized="mint",
    ))
    await db_session.commit()

    async def _fake_batch(catalog_id, requests, *, wait_for_ingest=True):  # noqa: ARG001
        return {"handles": [], "validation_status": []}

    monkeypatch.setattr(sync_service, "push_products_batch", _fake_batch)

    await push_dishes_to_meta(db_session, restaurant_id=restaurant.id)
    await db_session.commit()
    row = await db_session.scalar(
        select(CatalogProduct).where(CatalogProduct.restaurant_id == restaurant.id)
    )
    assert row is not None
    assert row.name == "Mint"
    assert row.price_aed == Decimal("12.00")
    assert row.is_active is True


async def test_push_raises_on_meta_validation_errors(db_session, restaurant, monkeypatch):
    from app.catalog.meta_client import CatalogWriteError
    from app.catalog.sync_service import push_dishes_to_meta
    from app.menu.models import Dish, Menu

    restaurant.settings = {**restaurant.settings, "catalog_id": "CAT1"}
    menu = Menu(restaurant_id=restaurant.id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    db_session.add(Dish(
        menu_id=menu.id, restaurant_id=restaurant.id, name="Soup",
        price_aed=Decimal("10.00"), is_available=True, name_normalized="soup",
    ))
    await db_session.commit()

    async def _bad_batch(catalog_id, requests, *, wait_for_ingest=True):  # noqa: ARG001
        raise CatalogWriteError("Meta rejected 1 item(s): rid: missing image_link")

    monkeypatch.setattr(sync_service, "push_products_batch", _bad_batch)

    with pytest.raises(CatalogWriteError, match="image_link"):
        await push_dishes_to_meta(db_session, restaurant_id=restaurant.id)


async def test_sync_full_bidirectional_pushes_then_repulls(db_session, restaurant, monkeypatch):
    from app.catalog.sync_service import sync_full_bidirectional
    from app.menu.models import Dish, Menu

    restaurant.settings = {**restaurant.settings, "catalog_id": "CAT1"}
    menu = Menu(restaurant_id=restaurant.id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    db_session.add(Dish(
        menu_id=menu.id, restaurant_id=restaurant.id, dish_number=1, name="Biryani",
        price_aed=Decimal("30.00"), category="Rice", is_available=True,
        name_normalized="biryani",
    ))
    db_session.add(Dish(
        menu_id=menu.id, restaurant_id=restaurant.id, dish_number=2, name="Mint",
        price_aed=Decimal("12.00"), category="Drinks", is_available=True,
        name_normalized="mint",
    ))
    await db_session.commit()

    pull_calls = 0
    mint_rid: list[str] = []

    async def _fake_pull(catalog_id):  # noqa: ARG001
        nonlocal pull_calls
        pull_calls += 1
        if pull_calls == 1:
            return [_mp("r1", "Biryani", 30, "Rice")]
        rid = mint_rid[0] if mint_rid else "mint-rid"
        return [_mp("r1", "Biryani", 30, "Rice"), _mp(rid, "Mint", 12, "Drinks")]

    async def _fake_batch(catalog_id, requests, *, wait_for_ingest=True):  # noqa: ARG001
        for req in requests:
            if req.get("data", {}).get("title") == "Mint":
                mint_rid.append(req["retailer_id"])
        return {"handles": ["h1"], "validation_status": []}

    from app.catalog import meta_client

    monkeypatch.setattr(sync_service, "fetch_catalog_products", _fake_pull)
    monkeypatch.setattr(sync_service, "push_products_batch", _fake_batch)
    monkeypatch.setattr(meta_client, "wait_for_batch_handles", lambda *a, **k: None)

    res = await sync_full_bidirectional(db_session, restaurant_id=restaurant.id)
    await db_session.commit()
    assert pull_calls == 2
    assert res.pushed == 1  # Mint is new; Biryani already linked on first pull → UPDATE
    assert res.push_updated == 1
    rows = (await db_session.scalars(
        select(CatalogProduct).where(CatalogProduct.restaurant_id == restaurant.id)
    )).all()
    assert len(rows) == 2


async def test_is_catalog_fully_synced_requires_all_dishes_linked(db_session, restaurant):
    from app.catalog.models import CatalogProduct
    from app.catalog.sync_service import is_catalog_fully_synced
    from app.menu.models import Dish, Menu

    restaurant.settings = {**restaurant.settings, "catalog_id": "CAT1"}
    menu = Menu(restaurant_id=restaurant.id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    linked = Dish(
        menu_id=menu.id, restaurant_id=restaurant.id, name="Biryani",
        price_aed=Decimal("30.00"), is_available=True, name_normalized="biryani",
        catalog_retailer_id="r1",
    )
    solo = Dish(
        menu_id=menu.id, restaurant_id=restaurant.id, name="Mint",
        price_aed=Decimal("12.00"), is_available=True, name_normalized="mint",
    )
    db_session.add_all([linked, solo])
    db_session.add(CatalogProduct(
        restaurant_id=restaurant.id, retailer_id="r1", name="Biryani",
        price_aed=Decimal("30.00"), is_active=True, raw={},
    ))
    await db_session.commit()
    assert await is_catalog_fully_synced(db_session, restaurant_id=restaurant.id) is False

    solo.catalog_retailer_id = "r2"
    db_session.add(CatalogProduct(
        restaurant_id=restaurant.id, retailer_id="r2", name="Mint",
        price_aed=Decimal("12.00"), is_active=True, raw={},
    ))
    await db_session.commit()
    assert await is_catalog_fully_synced(db_session, restaurant_id=restaurant.id) is True


async def test_auto_publish_noop_without_catalog_id(db_session, restaurant):
    """Auto-publish (run on menu activation) must silently no-op when the restaurant
    hasn't connected a Meta catalogue — activation must never depend on Meta."""
    restaurant.settings = {k: v for k, v in (restaurant.settings or {}).items() if k != "catalog_id"}
    await db_session.commit()
    res = await sync_service.auto_publish_to_meta(db_session, restaurant_id=restaurant.id)
    assert (res.pushed, res.push_updated, res.added, res.updated) == (0, 0, 0, 0)


async def test_unpublish_sends_delete_and_drops_mirror(db_session, restaurant, monkeypatch):
    """Deleting a dish removes its product from Meta (DELETE batch) and the local mirror."""
    restaurant.settings = {**restaurant.settings, "catalog_id": "CAT1"}
    db_session.add(CatalogProduct(
        restaurant_id=restaurant.id, retailer_id="r9", name="Gone",
        price_aed=Decimal("5.00"), is_active=True, raw={},
    ))
    await db_session.commit()

    sent: list[dict] = []
    async def _fake_batch(catalog_id, requests, **kw):  # noqa: ARG001
        sent.extend(requests)
        return {"handles": []}
    monkeypatch.setattr(sync_service, "push_products_batch", _fake_batch)

    ok = await sync_service.unpublish_from_meta(db_session, restaurant_id=restaurant.id, retailer_id="r9")
    await db_session.commit()
    assert ok is True
    assert sent == [{"method": "DELETE", "retailer_id": "r9", "data": {}}]
    assert await db_session.scalar(
        select(CatalogProduct).where(CatalogProduct.retailer_id == "r9")
    ) is None


async def test_unpublish_noop_without_catalog_id(db_session, restaurant):
    restaurant.settings = {k: v for k, v in (restaurant.settings or {}).items() if k != "catalog_id"}
    await db_session.commit()
    ok = await sync_service.unpublish_from_meta(db_session, restaurant_id=restaurant.id, retailer_id="rX")
    assert ok is False


async def test_push_dedupes_duplicate_retailer_id(db_session, restaurant, monkeypatch):
    """Two dishes sharing a catalog_retailer_id must NOT produce a duplicate in the
    Meta batch (Meta rejects the whole call). Push the first, unlink the duplicate."""
    from app.catalog.sync_service import push_dishes_to_meta
    from app.menu.models import Dish, Menu

    restaurant.settings = {**restaurant.settings, "catalog_id": "CAT1"}
    menu = Menu(restaurant_id=restaurant.id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    d1 = Dish(menu_id=menu.id, restaurant_id=restaurant.id, dish_number=1, name="Biryani",
              price_aed=Decimal("30.00"), category="Rice", is_available=True,
              name_normalized="biryani", catalog_retailer_id="dup1")
    d2 = Dish(menu_id=menu.id, restaurant_id=restaurant.id, dish_number=2, name="Biryani Special",
              price_aed=Decimal("35.00"), category="Rice", is_available=True,
              name_normalized="biryani special", catalog_retailer_id="dup1")
    db_session.add_all([d1, d2])
    await db_session.commit()

    captured: list[dict] = []
    async def _fake_batch(catalog_id, requests, *, wait_for_ingest=True):  # noqa: ARG001
        captured.extend(requests)
        return {"handles": [], "validation_status": []}
    monkeypatch.setattr(sync_service, "push_products_batch", _fake_batch)

    await push_dishes_to_meta(db_session, restaurant_id=restaurant.id)
    await db_session.commit()
    rids = [r["retailer_id"] for r in captured]
    assert rids.count("dup1") == 1  # no duplicate in the batch
    # The duplicate dish was unlinked so it gets its own id next push.
    await db_session.refresh(d2)
    assert d2.catalog_retailer_id is None
