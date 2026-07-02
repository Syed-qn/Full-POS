"""W5 capability evals — Money & catalogue price integrity.

Five behaviours the remediation must guarantee (spec §W5; findings R-019, R-049,
R-050, R-051, F26, F41, F112, RA-3):

  (a) A catalogue basket snapshots the tapped Meta ``item_price`` onto
      ``OrderItem.price_aed`` — never the (possibly stale) ``Dish.price_aed`` (R-051).
  (b) When the tapped price drifts from the tenant catalogue price beyond a cent,
      the item is BLOCKED (not silently charged) and the customer is told (R-019).
  (c) The pre-confirmation summary shows wallet credit = ``min(balance, total)`` and
      ``COD due = total − applied`` — summary math == door cash (R-049 / RA-3).
  (d) ``modify_order`` re-applies the coupon discount and keeps the wallet hold
      consistent with the new total (F26).
  (e) The delivery ``distance_source`` is persisted, flagging the haversine
      fallback when the geo provider fails (F112).

These graduated from ``xfail(strict=True)`` to permanent regression tests once W5
landed (columns + recompute_order_total + apply_coupon + catalogue snapshot +
QuantityPolicy + distance_source).
"""
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.ordering.models import Order, OrderItem
from app.outbox.models import OutboxMessage
from app.whatsapp.port import InboundMessage, MessageType

pytestmark = pytest.mark.asyncio


def _catalog_inbound(items, *, phone="+971501110001", wa_id="wamid.w5cart") -> InboundMessage:
    return InboundMessage(
        wa_message_id=wa_id,
        from_phone=phone,
        type=MessageType.ORDER,
        payload={"catalog_id": "TEST-CAT-001", "text": None, "product_items": items},
        restaurant_phone="+97141234567",
        timestamp=1717660800,
    )


async def _latest_draft_order(db_session, restaurant_id) -> Order | None:
    return await db_session.scalar(
        select(Order)
        .where(Order.restaurant_id == restaurant_id, Order.status == "draft")
        .order_by(Order.id.desc())
    )


# ── (a) catalogue snapshots Meta item_price, not stale Dish.price_aed ──────────

async def test_catalogue_snapshots_meta_item_price(db_session, restaurant, seed_biryani_menu):
    from app.catalog.models import CatalogProduct
    from app.catalog.service import handle_catalog_order

    # Tenant catalogue price (what the customer tapped) = 25; local Dish.price_aed = 20
    # (stale). The tapped price must win.
    cp = await db_session.scalar(
        select(CatalogProduct).where(
            CatalogProduct.restaurant_id == restaurant.id,
            CatalogProduct.retailer_id == "ju9f8jfy90",
        )
    )
    cp.price_aed = Decimal("25.00")
    await db_session.flush()

    inbound = _catalog_inbound(
        [{"product_retailer_id": "ju9f8jfy90", "quantity": "1",
          "item_price": "25", "currency": "AED"}]
    )
    await handle_catalog_order(db_session, inbound, restaurant_id=restaurant.id)

    order = await _latest_draft_order(db_session, restaurant.id)
    assert order is not None
    item = await db_session.scalar(
        select(OrderItem).where(OrderItem.order_id == order.id)
    )
    assert item is not None, "biryani should be in the cart"
    assert item.price_aed == Decimal("25.00"), (
        f"expected snapshot of tapped item_price 25, got {item.price_aed}"
    )


# ── (b) price drift > 0.01 blocks the item + price-mismatch reply ──────────────

async def test_catalogue_price_drift_blocks_item(db_session, restaurant, seed_biryani_menu):
    from app.catalog.service import handle_catalog_order

    # Catalogue price is 20 (fixture); customer's tapped card claims 25 → drift 5 → block.
    inbound = _catalog_inbound(
        [{"product_retailer_id": "ju9f8jfy90", "quantity": "1",
          "item_price": "25", "currency": "AED"}]
    )
    await handle_catalog_order(db_session, inbound, restaurant_id=restaurant.id)

    order = await _latest_draft_order(db_session, restaurant.id)
    item = None
    if order is not None:
        item = await db_session.scalar(
            select(OrderItem).where(OrderItem.order_id == order.id)
        )
    assert item is None, "drifted-price item must NOT be added to the cart"

    outbounds = (
        await db_session.scalars(
            select(OutboxMessage).where(OutboxMessage.restaurant_id == restaurant.id)
        )
    ).all()
    bodies = " ".join((o.payload or {}).get("body", "") for o in outbounds).lower()
    assert "price" in bodies, "customer must be told about the price mismatch"


# ── (c) pre-confirm summary: wallet credit + COD due (R-049 / RA-3) ────────────

async def test_summary_shows_wallet_credit_and_cod_due(db_session, restaurant, seed_biryani_menu):
    from app.conversation.renderer import render_cart_state
    from app.ordering.service import add_item, create_draft_order, get_or_create_customer
    from app.wallet import service as wallet

    customer = await get_or_create_customer(
        db_session, restaurant_id=restaurant.id, phone="+971501110002"
    )
    order = await create_draft_order(
        db_session, restaurant_id=restaurant.id, customer_id=customer.id
    )
    dish = seed_biryani_menu[0]  # Chicken Biryani @ 20
    await add_item(db_session, order=order, dish=dish, qty=1)
    order.delivery_fee_aed = Decimal("5.00")
    order.total = order.subtotal + order.delivery_fee_aed  # 20 + 5 = 25
    await db_session.flush()

    # Give the customer AED 10 wallet credit (less than the total).
    await wallet.credit(
        db_session, restaurant_id=restaurant.id, customer_id=customer.id,
        amount=Decimal("10.00"), idempotency_key="w5-credit-1", created_by="test",
    )
    await db_session.flush()

    body = await render_cart_state(
        db_session, order=order, phase="awaiting_confirmation"
    )
    # Wallet credit applied = min(10, 25) = 10 ; COD due = 25 − 10 = 15.
    assert "10" in body and "wallet" in body.lower(), body
    assert "cod due" in body.lower(), body
    assert "15" in body, f"COD due should be 15, body:\n{body}"


# ── (d) modify_order preserves coupon discount + wallet hold (F26) ─────────────

async def test_modify_order_preserves_coupon_and_wallet(db_session, restaurant, seed_biryani_menu):
    from app.coupons.service import create_coupon
    from app.ordering.payments import apply_coupon
    from app.ordering.service import (
        add_item,
        create_draft_order,
        get_or_create_customer,
        modify_order,
    )

    dishes = {d.name: d for d in seed_biryani_menu}
    customer = await get_or_create_customer(
        db_session, restaurant_id=restaurant.id, phone="+971501110003"
    )
    order = await create_draft_order(
        db_session, restaurant_id=restaurant.id, customer_id=customer.id
    )
    await add_item(db_session, order=order, dish=dishes["Chicken Biryani"], qty=1)  # 20
    order.delivery_fee_aed = Decimal("5.00")
    order.total = order.subtotal + order.delivery_fee_aed  # 25
    await db_session.flush()

    coupon = await create_coupon(
        db_session, restaurant_id=restaurant.id, discount_type="fixed",
        discount_value=Decimal("10.00"), kind="multi_use", created_by="test",
    )
    await apply_coupon(db_session, order=order, coupon_code=coupon.code)
    await db_session.flush()
    # After coupon: total = 20 + 5 − 10 = 15
    assert order.coupon_discount_aed == Decimal("10.00")
    assert order.total == Decimal("15.00")

    # Modify: swap to a bigger cart (Mndhi-2 @ 50). Coupon must still apply.
    await modify_order(
        db_session, order=order, actor="customer",
        new_items=[{"dish": dishes["Mndhi - 2"], "qty": 1}],
    )
    await db_session.flush()
    # subtotal 50 + fee 5 − coupon 10 = 45; coupon discount preserved.
    assert order.coupon_discount_aed == Decimal("10.00"), "coupon discount dropped on modify"
    assert order.subtotal == Decimal("50.00")
    assert order.total == Decimal("45.00"), f"total must re-apply coupon, got {order.total}"


# ── (e) distance_source persisted on haversine fallback (F112) ─────────────────

async def test_distance_source_flags_haversine_fallback(db_session, restaurant, monkeypatch):
    from app.conversation import engine
    from app.ordering.service import create_draft_order, get_or_create_customer

    # Force the geo provider to blow up so the wrapper degrades to haversine.
    def _boom():
        raise RuntimeError("geo provider down")

    monkeypatch.setattr("app.geo.factory.get_geo_provider", _boom)

    dist, source = await engine._road_distance_km(25.2048, 55.2708, 25.20, 55.27)
    assert source == "haversine_fallback", f"expected fallback flag, got {source!r}"
    assert isinstance(dist, float)

    # And the column persists on the order.
    customer = await get_or_create_customer(
        db_session, restaurant_id=restaurant.id, phone="+971501110004"
    )
    order = await create_draft_order(
        db_session, restaurant_id=restaurant.id, customer_id=customer.id
    )
    order.distance_km = dist
    order.distance_source = source
    await db_session.flush()
    await db_session.refresh(order)
    assert order.distance_source == "haversine_fallback"
