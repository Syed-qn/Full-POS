"""Perf: Biryani 'menu' path at prod scale (608 products, shared Feasto)."""
from __future__ import annotations

import time
from decimal import Decimal

import pytest

N_PRODUCTS = 608


def _ms(t0: float) -> float:
    return (time.perf_counter() - t0) * 1000


@pytest.fixture
async def biryani_scale_menu(db_session, restaurant):
    """Biryani + Lims on shared Feasto with ~608 sendable catalog products."""
    from app.catalog.models import CatalogProduct
    from app.identity.models import Restaurant
    from app.menu.models import Dish, Menu

    lims = Restaurant(
        name="Lims Timing",
        phone="+919344471586",
        password_hash="x",
        lat=25.2,
        lng=55.27,
    )
    db_session.add(lims)
    feasto = "1528685515412822"
    restaurant.settings = {
        **(restaurant.settings or {}),
        "catalog_id": feasto,
        "catalog_ordering_enabled": True,
        "catalog_native_view": True,
        "catalog_browse_by_category": False,
    }
    lims.settings = {
        "catalog_id": feasto,
        "catalog_ordering_enabled": True,
        "catalog_native_view": True,
        "catalog_browse_by_category": False,
    }
    await db_session.flush()

    menu = Menu(restaurant_id=restaurant.id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()

    dishes = []
    for i in range(N_PRODUCTS):
        dishes.append(
            Dish(
                menu_id=menu.id,
                restaurant_id=restaurant.id,
                dish_number=i + 1,
                name=f"Dish {i + 1}",
                price_aed=Decimal("25.00"),
                category=f"Cat{i % 40}",
                is_available=True,
                whatsapp_enabled=True,
                meta_status="active",
                name_normalized=f"dish {i + 1}",
            )
        )
    db_session.add_all(dishes)
    await db_session.flush()
    products = []
    for d in dishes:
        rid = f"dish-{d.id}-{restaurant.id}"
        d.catalog_retailer_id = rid
        products.append(
            CatalogProduct(
                restaurant_id=restaurant.id,
                retailer_id=rid,
                name=d.name,
                price_aed=d.price_aed,
                currency="AED",
                availability="in stock",
                category=d.category,
                is_active=True,
                is_sendable=True,
                raw={},
            )
        )
    db_session.add_all(products)
    await db_session.commit()
    return restaurant


@pytest.mark.asyncio
async def test_biryani_menu_timing_report(db_session, biryani_scale_menu, monkeypatch, capsys):
    """Print timing breakdown for 'menu' — no LLM, deterministic path."""
    from app.catalog.tenant_scope import (
        build_tenant_catalog_gate,
        filter_tenant_catalog_products,
        is_shared_catalog,
        load_tenant_catalog_mirror,
    )
    from app.config import get_settings
    from app.conversation.engine import handle_inbound
    from app.outbox.models import OutboxMessage
    from app.outbox.worker import _deliver_one, claim_pending_outbox_ids
    from app.whatsapp.factory import get_whatsapp_provider
    from app.whatsapp.port import InboundMessage, MessageType, OutboundMessageType
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker

    restaurant = biryani_scale_menu
    monkeypatch.setattr(get_settings(), "outbox_sync_delivery", True)

    phone = "+971509990099"
    timings: dict[str, float] = {}

    # Stale backlog (simulates Render draining ALL restaurant pending on every webhook)
    backlog = 30
    for i in range(backlog):
        db_session.add(
            OutboxMessage(
                restaurant_id=restaurant.id,
                to_phone="+971500000088",
                payload={"type": str(OutboundMessageType.TEXT), "body": f"stale {i}"},
                idempotency_key=f"timing-stale-{restaurant.id}-{i}",
            )
        )
    await db_session.commit()

    t0 = time.perf_counter()
    shared = await is_shared_catalog(db_session, restaurant_id=restaurant.id)
    timings["is_shared_catalog_ms"] = _ms(t0)

    t0 = time.perf_counter()
    _cid, synced = await load_tenant_catalog_mirror(db_session, restaurant.id)
    timings["load_mirror_ms"] = _ms(t0)
    timings["mirror_count"] = len(synced)

    t0 = time.perf_counter()
    await build_tenant_catalog_gate(db_session, restaurant.id)
    timings["build_gate_ms"] = _ms(t0)

    t0 = time.perf_counter()
    await filter_tenant_catalog_products(
        db_session, restaurant_id=restaurant.id, products=synced
    )
    timings["filter_ms"] = _ms(t0)

    inbound = InboundMessage(
        wa_message_id="timing-menu-001",
        from_phone=phone,
        type=MessageType.TEXT,
        payload={"text": "menu"},
        restaurant_phone=restaurant.phone,
        timestamp=1_700_000_000,
    )

    t0 = time.perf_counter()
    await handle_inbound(db_session, inbound, restaurant_id=restaurant.id)
    timings["handle_inbound_ms"] = _ms(t0)

    from app.identity.phones import normalize_phone

    scoped_phone = normalize_phone(phone)
    t0 = time.perf_counter()
    claimed_scoped = await claim_pending_outbox_ids(
        db_session, restaurant_id=restaurant.id, to_phone=scoped_phone
    )
    await db_session.commit()
    timings["claim_scoped_ms"] = _ms(t0)
    timings["claimed_scoped"] = len(claimed_scoped)

    provider = get_whatsapp_provider()
    factory = async_sessionmaker(
        bind=db_session.bind,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    t0 = time.perf_counter()
    for oid in claimed_scoped:
        await _deliver_one(oid, provider=provider, session_factory=factory)
    timings["sync_deliver_scoped_ms"] = _ms(t0)

    rows = (
        await db_session.scalars(
            select(OutboxMessage)
            .where(
                OutboxMessage.restaurant_id == restaurant.id,
                OutboxMessage.to_phone == phone,
            )
            .order_by(OutboxMessage.id.desc())
            .limit(3)
        )
    ).all()
    turn_types = [r.payload.get("type") for r in rows]

    webhook_total = (
        timings["handle_inbound_ms"]
        + timings["claim_scoped_ms"]
        + timings["sync_deliver_scoped_ms"]
    )

    print("\n=== Biryani 'menu' timing (608 products, shared Feasto) ===")
    print(f"  shared_catalog:        {shared}")
    print(f"  is_shared_catalog:     {timings['is_shared_catalog_ms']:.1f} ms")
    print(f"  load_mirror ({timings['mirror_count']}): {timings['load_mirror_ms']:.1f} ms")
    print(f"  build_gate:            {timings['build_gate_ms']:.1f} ms")
    print(f"  filter_products:       {timings['filter_ms']:.1f} ms")
    print(f"  handle_inbound(menu):  {timings['handle_inbound_ms']:.1f} ms  (NO LLM)")
    print(f"  claim THIS phone ({timings['claimed_scoped']} msgs, {backlog} stale skipped): {timings['claim_scoped_ms']:.1f} ms")
    print(f"  sync deliver scoped:   {timings['sync_deliver_scoped_ms']:.1f} ms")
    print(f"  this turn outbox:      {turn_types}")
    print(f"  >>> WEBHOOK TOTAL:     {webhook_total:.1f} ms ({webhook_total/1000:.2f}s)")

    # Engine path must stay fast — catalog filter fix target
    assert timings["handle_inbound_ms"] < 5000, (
        f"handle_inbound too slow: {timings['handle_inbound_ms']:.0f}ms"
    )
    # Native catalog view → one CATALOG_MESSAGE, not 608-card dump
    assert "catalog_message" in turn_types