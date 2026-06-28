"""End-to-end: flipping catalog_ordering_enabled via the settings endpoint (what the
Menu-page toggle calls) actually changes what the WhatsApp chat injects.

Catalogue mode ON  -> greeting injects the catalogue (product_list).
Catalogue mode OFF -> greeting injects the text menu (no product_list).
"""
from decimal import Decimal

from sqlalchemy import select

from app.catalog.models import CatalogProduct
from app.conversation.engine import handle_inbound
from app.identity.models import Restaurant
from app.menu.models import Dish, Menu
from app.outbox.models import OutboxMessage
from app.whatsapp.port import InboundMessage, MessageType

_REST_PHONE = "+971501234567"  # the restaurant auth_headers signs up


def _greet(from_phone: str, wa_id: str) -> InboundMessage:
    return InboundMessage(
        wa_message_id=wa_id, from_phone=from_phone, type=MessageType.TEXT,
        payload={"text": "hi"}, restaurant_phone=_REST_PHONE, timestamp=1717660800,
    )


async def _types_to(db_session, phone: str) -> list[str]:
    outs = (await db_session.scalars(
        select(OutboxMessage).where(OutboxMessage.to_phone == phone)
    )).all()
    return [o.payload.get("type") for o in outs]


async def test_toggle_switches_chat_injection(client, db_session, auth_headers):
    rest = await db_session.scalar(select(Restaurant).where(Restaurant.phone == _REST_PHONE))

    # A synced catalogue product (so catalogue mode can send) AND a text menu/dish (so
    # text mode can send) — the ONLY difference between the two runs is the mode flag.
    db_session.add(CatalogProduct(
        restaurant_id=rest.id, retailer_id="r1", name="Biryani", price_aed=Decimal("30.00"),
        currency="AED", availability="in stock", category="Rice", is_active=True, raw={},
    ))
    menu = Menu(restaurant_id=rest.id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    db_session.add(Dish(
        menu_id=menu.id, restaurant_id=rest.id, dish_number=1, name="Chicken Biryani",
        price_aed=Decimal("20.00"), category="Rice", is_available=True,
        name_normalized="chicken biryani",
    ))
    await db_session.commit()

    # 1) Toggle ON (what the Menu-page button does) → customer A greets → catalogue.
    r1 = await client.patch(
        "/api/v1/settings", headers=auth_headers,
        json={"catalog_id": "CAT1", "catalog_ordering_enabled": True},
    )
    assert r1.status_code == 200
    await handle_inbound(db_session, _greet("+971500000001", "wamid.on"), restaurant_id=rest.id)
    await db_session.commit()
    types_a = await _types_to(db_session, "+971500000001")
    assert "product_list" in types_a  # catalogue injected
    assert not any("Here's our menu" in (o.payload.get("body") or "")
                   for o in (await db_session.scalars(
                       select(OutboxMessage).where(OutboxMessage.to_phone == "+971500000001")
                   )).all())  # NO text menu

    # 2) Toggle OFF → customer B greets → text menu, no catalogue.
    r2 = await client.patch(
        "/api/v1/settings", headers=auth_headers,
        json={"catalog_ordering_enabled": False},
    )
    assert r2.status_code == 200
    # The flag really flipped in the DB.
    await db_session.refresh(rest)
    assert rest.settings.get("catalog_ordering_enabled") is False

    await handle_inbound(db_session, _greet("+971500000002", "wamid.off"), restaurant_id=rest.id)
    await db_session.commit()
    types_b = await _types_to(db_session, "+971500000002")
    assert "product_list" not in types_b  # catalogue NOT injected
    bodies_b = [o.payload.get("body", "") for o in (await db_session.scalars(
        select(OutboxMessage).where(OutboxMessage.to_phone == "+971500000002")
    )).all()]
    assert any("Chicken Biryani" in b for b in bodies_b)  # the text menu WAS injected
