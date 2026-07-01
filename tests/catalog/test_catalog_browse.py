"""Browse-by-category: big menus (past the 30-card product_list cap) send a tappable
category picker; tapping a category sends that category's cards. Behind the
``catalog_browse_by_category`` flag, so default behaviour is unchanged."""
from decimal import Decimal

from sqlalchemy import select

from app.catalog.models import CatalogProduct
from app.catalog.service import send_catalog, send_catalog_category
from app.outbox.models import OutboxMessage
from app.whatsapp.port import InboundMessage, MessageType

PHONE = "+971501110001"


async def _seed_big_catalogue(db_session, restaurant, *, browse: bool):
    settings = {**restaurant.settings, "catalog_id": "1528685515412822",
                "catalog_ordering_enabled": True}
    if browse:
        settings["catalog_browse_by_category"] = True
    restaurant.settings = settings
    # 35 sendable products (>30) across two categories → one product_list can't hold all.
    for i in range(20):
        db_session.add(CatalogProduct(
            restaurant_id=restaurant.id, retailer_id=f"bir{i}", name=f"Biryani {i}",
            price_aed=Decimal("20.00"), currency="AED", availability="in stock",
            category="Biryani", is_active=True, raw={},
        ))
    for i in range(15):
        db_session.add(CatalogProduct(
            restaurant_id=restaurant.id, retailer_id=f"drk{i}", name=f"Drink {i}",
            price_aed=Decimal("8.00"), currency="AED", availability="in stock",
            category="Drinks", is_active=True, raw={},
        ))
    await db_session.commit()


async def _last_out(db_session):
    return (await db_session.scalars(
        select(OutboxMessage).where(OutboxMessage.to_phone == PHONE)
        .order_by(OutboxMessage.id.desc())
    )).first()


async def test_big_menu_sends_category_picker_when_enabled(db_session, restaurant):
    await _seed_big_catalogue(db_session, restaurant, browse=True)
    sent = await send_catalog(db_session, restaurant_id=restaurant.id, to_phone=PHONE)
    await db_session.commit()
    assert sent is True
    msg = await _last_out(db_session)
    assert msg.payload.get("type") == "list"  # interactive category list, not product_list
    rows = msg.payload["sections"][0]["rows"]
    titles = {r["title"] for r in rows}
    assert titles == {"Biryani", "Drinks"}
    # Biryani is the bigger category → appears first.
    assert rows[0]["title"] == "Biryani"
    assert rows[0]["id"] == "cat:Biryani"


async def test_big_menu_truncates_to_product_list_when_disabled(db_session, restaurant):
    """Flag off (default): unchanged behaviour — a single product_list (capped at 30)."""
    await _seed_big_catalogue(db_session, restaurant, browse=False)
    sent = await send_catalog(db_session, restaurant_id=restaurant.id, to_phone=PHONE)
    await db_session.commit()
    assert sent is True
    msg = await _last_out(db_session)
    assert msg.payload.get("type") == "product_list"


async def test_category_tap_sends_that_categorys_cards(db_session, restaurant):
    from app.conversation.engine import handle_inbound

    await _seed_big_catalogue(db_session, restaurant, browse=True)
    msg = InboundMessage(
        wa_message_id="wamid.cat", from_phone=PHONE, type=MessageType.LIST_REPLY,
        payload={"id": "cat:Drinks", "title": "Drinks"},
        restaurant_phone="+97141234567", timestamp=1717660800,
    )
    await handle_inbound(db_session, msg, restaurant_id=restaurant.id)
    await db_session.commit()

    out = await _last_out(db_session)
    assert out.payload.get("type") == "product_list"
    items = out.payload["sections"][0]["product_items"]
    # Only Drinks products (drk*) — never the Biryani ones.
    assert all(it["product_retailer_id"].startswith("drk") for it in items)
    assert len(items) == 15


async def _seed_many_categories(db_session, restaurant, *, n_cats: int, per_cat: int):
    restaurant.settings = {**restaurant.settings, "catalog_id": "1528685515412822",
                           "catalog_ordering_enabled": True,
                           "catalog_browse_by_category": True}
    for c in range(n_cats):
        for i in range(per_cat):
            db_session.add(CatalogProduct(
                restaurant_id=restaurant.id, retailer_id=f"c{c:02d}i{i:02d}",
                name=f"Cat{c:02d} Item {i:02d}", price_aed=Decimal("10.00"),
                currency="AED", availability="in stock",
                category=f"Cat{c:02d}", is_active=True, raw={},
            ))
    await db_session.commit()


async def test_category_list_paginates_when_many_categories(db_session, restaurant):
    from app.catalog.service import send_catalog_categories

    # 12 categories x 3 = 36 sendable (>30 → picker). 12 categories > 9 per page.
    await _seed_many_categories(db_session, restaurant, n_cats=12, per_cat=3)
    await send_catalog(db_session, restaurant_id=restaurant.id, to_phone=PHONE)
    await db_session.commit()
    page0 = await _last_out(db_session)
    rows0 = page0.payload["sections"][0]["rows"]
    assert len(rows0) == 10  # 9 categories + 1 "More categories" row
    assert rows0[-1]["id"] == "catpage:1"
    assert rows0[-1]["title"] == "More categories"

    # Tapping "More categories" loads the remaining 3 categories, no further page.
    sent = await send_catalog_categories(
        db_session, restaurant_id=restaurant.id, to_phone=PHONE, page=1
    )
    await db_session.commit()
    assert sent is True
    page1 = await _last_out(db_session)
    rows1 = page1.payload["sections"][0]["rows"]
    assert len(rows1) == 3  # the leftover categories
    assert all(not r["id"].startswith("catpage:") for r in rows1)  # no more pages


async def test_category_paginates_within_category_over_30(db_session, restaurant):
    from app.catalog.service import send_catalog_category

    # One category with 35 sendable dishes → 30 cards + a "Show more" quick-reply.
    await _seed_many_categories(db_session, restaurant, n_cats=1, per_cat=35)
    sent = await send_catalog_category(
        db_session, restaurant_id=restaurant.id, to_phone=PHONE, category="Cat00"
    )
    await db_session.commit()
    assert sent is True
    outs = (await db_session.scalars(
        select(OutboxMessage).where(OutboxMessage.to_phone == PHONE)
        .order_by(OutboxMessage.id)
    )).all()
    first, more = outs[-2], outs[-1]
    assert first.payload["type"] == "product_list"
    assert len(first.payload["sections"][0]["product_items"]) == 30
    assert more.payload["type"] == "buttons"
    assert more.payload["buttons"][0]["id"] == "catmore:30:Cat00"

    # Tapping "Show more" sends the remaining 5, no further "Show more".
    await send_catalog_category(
        db_session, restaurant_id=restaurant.id, to_phone=PHONE, category="Cat00", offset=30
    )
    await db_session.commit()
    last = await _last_out(db_session)
    assert last.payload["type"] == "product_list"  # the final 5, no trailing buttons
    assert len(last.payload["sections"][0]["product_items"]) == 5


async def test_show_more_button_tap_routes_through_engine(db_session, restaurant):
    """A "Show more" quick-reply (BUTTON_REPLY id catmore:30:Cat00) loads the next page."""
    from app.conversation.engine import handle_inbound

    await _seed_many_categories(db_session, restaurant, n_cats=1, per_cat=35)
    msg = InboundMessage(
        wa_message_id="wamid.more", from_phone=PHONE, type=MessageType.BUTTON_REPLY,
        payload={"id": "catmore:30:Cat00", "title": "Show more"},
        restaurant_phone="+97141234567", timestamp=1717660800,
    )
    await handle_inbound(db_session, msg, restaurant_id=restaurant.id)
    await db_session.commit()
    out = await _last_out(db_session)
    assert out.payload["type"] == "product_list"
    assert len(out.payload["sections"][0]["product_items"]) == 5  # the remaining 5


async def test_native_catalog_view_when_enabled(db_session, restaurant):
    """catalog_native_view ON → one "View full menu" catalog_message (the native browse),
    NOT a 30-card product_list. This is what makes all 586 reachable in a single tap."""
    restaurant.settings = {**restaurant.settings, "catalog_id": "1528685515412822",
                           "catalog_ordering_enabled": True, "catalog_native_view": True}
    for i in range(3):
        db_session.add(CatalogProduct(
            restaurant_id=restaurant.id, retailer_id=f"p{i}", name=f"Dish {i}",
            price_aed=Decimal("100.00"), currency="AED", availability="in stock",
            category=None, is_active=True, is_sendable=True, raw={},
        ))
    await db_session.commit()

    sent = await send_catalog(db_session, restaurant_id=restaurant.id, to_phone=PHONE)
    await db_session.commit()
    assert sent is True
    msg = await _last_out(db_session)
    assert msg.payload.get("type") == "catalog_message"
    # Thumbnail is a real sendable product so the button card renders.
    assert msg.payload["thumbnail_product_retailer_id"] in {"p0", "p1", "p2"}


async def test_native_view_falls_back_to_text_when_nothing_sendable(db_session, restaurant):
    """Native view still needs ≥1 sendable product for the thumbnail; if everything is in
    review it must NOT crash — it sends the text menu fallback."""
    restaurant.settings = {**restaurant.settings, "catalog_id": "1528685515412822",
                           "catalog_ordering_enabled": True, "catalog_native_view": True}
    db_session.add(CatalogProduct(
        restaurant_id=restaurant.id, retailer_id="p0", name="Dish 0",
        price_aed=Decimal("100.00"), currency="AED", availability="in stock",
        category=None, is_active=True, is_sendable=False, raw={},
    ))
    await db_session.commit()

    sent = await send_catalog(db_session, restaurant_id=restaurant.id, to_phone=PHONE)
    await db_session.commit()
    assert sent is True
    msg = await _last_out(db_session)
    assert msg.payload.get("type") == "text"


async def test_category_resolved_from_dish_when_mirror_null(db_session, restaurant):
    """PROD reality: the Meta catalogue mirror comes back with category=NULL (Meta
    doesn't echo our category), but the real category lives on the dish. The picker must
    group by the DISH category, not collapse everything into one "Menu" bucket."""
    from app.menu.models import Dish, Menu

    restaurant.settings = {**restaurant.settings, "catalog_id": "1528685515412822",
                           "catalog_ordering_enabled": True,
                           "catalog_browse_by_category": True}
    menu = Menu(restaurant_id=restaurant.id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()

    # 35 products (>30 → picker) across 3 real categories, mirror category NULL throughout.
    spec = [("APPETIZER", 15), ("SANDWICHES", 12), ("PASTA", 8)]
    n = 0
    for cat, count in spec:
        for _ in range(count):
            n += 1
            rid = f"dish-{n}"
            db_session.add(Dish(
                menu_id=menu.id, restaurant_id=restaurant.id, dish_number=n,
                name=f"Item {n}", name_normalized=f"item {n}",
                price_aed=Decimal("100.00"), category=cat, is_available=True,
                catalog_retailer_id=rid,
            ))
            db_session.add(CatalogProduct(
                restaurant_id=restaurant.id, retailer_id=rid, name=f"Item {n}",
                price_aed=Decimal("100.00"), currency="AED", availability="in stock",
                category=None, is_active=True, is_sendable=True, raw={},
            ))
    await db_session.commit()

    sent = await send_catalog(db_session, restaurant_id=restaurant.id, to_phone=PHONE)
    await db_session.commit()
    assert sent is True
    msg = await _last_out(db_session)
    assert msg.payload.get("type") == "list"  # picker, not a truncated product_list
    titles = [r["title"] for r in msg.payload["sections"][0]["rows"]]
    # Real dish categories surface, largest first — NOT a single "Menu" bucket.
    assert titles[:3] == ["APPETIZER", "SANDWICHES", "PASTA"]
    assert "Menu" not in titles

    # And tapping one returns exactly that category's dishes.
    sent2 = await send_catalog_category(
        db_session, restaurant_id=restaurant.id, to_phone=PHONE, category="PASTA"
    )
    await db_session.commit()
    assert sent2 is True
    out = await _last_out(db_session)
    assert out.payload["type"] == "product_list"
    assert len(out.payload["sections"][0]["product_items"]) == 8


async def test_category_send_filters_unsendable(db_session, restaurant):
    """A category with everything still in review sends nothing (gentle text nudge)."""
    await _seed_big_catalogue(db_session, restaurant, browse=True)
    # Mark all Drinks as not sendable (still in Meta review).
    drinks = (await db_session.scalars(
        select(CatalogProduct).where(CatalogProduct.category == "Drinks")
    )).all()
    for p in drinks:
        p.is_sendable = False
    await db_session.commit()

    sent = await send_catalog_category(
        db_session, restaurant_id=restaurant.id, to_phone=PHONE, category="Drinks"
    )
    await db_session.commit()
    assert sent is False
    out = await _last_out(db_session)
    assert out.payload.get("type") == "text"
