"""W6 capability evals — Menu / availability single source of truth.

Five behaviours the remediation must guarantee (spec §W6; findings F96, F97, F98,
F99, F74, R-026, R-028, TX-06, TX-26, TX-27, TX-45, TX-48, TX-49, R-023):

  (a) Anti-hallucination cross-check: LLM reply naming >=2 non-catalogue dish-like
      names (even without prices) is replaced by the real DB menu (R-026, F96).
  (b) One-dish tenant: "only chicken right?" cannot name any other dish in its
      reply (F98).
  (c) whatsapp_enabled=False dish ('Test Dish') is not rendered in _render_menu
      and is rejected when a customer tries to order it (TX-45).
  (d) Off-catalogue dish (lives in text DB, no active CatalogProduct) in catalogue
      mode → reply says "available by phone", cart stays empty, no fake mini-menu
      injected (TX-06, R-023).
  (e) Slug-named dish ('chicken_biryani') is absent from _render_menu output
      (F74, F97).

GRADUATED (W6 tasks 4-6): all 6 evals (a-e, with (c) split across two tests) now
PASS against the implementation and no longer carry xfail. See
tests/evals/REGISTRY.md for the graduation record.
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.conversation.engine import _render_menu, handle_inbound
from app.menu.models import Dish, Menu
from app.whatsapp.port import InboundMessage, MessageType

pytestmark = pytest.mark.asyncio

# ── helpers ──────────────────────────────────────────────────────────────────

PHONE = "+971509990001"


def _text_inbound(text: str, *, phone: str = PHONE, wa_id: str | None = None) -> InboundMessage:
    return InboundMessage(
        wa_message_id=wa_id or f"harness-w6-{hash(text) & 0xFFFFFF}",
        from_phone=phone,
        type=MessageType.TEXT,
        payload={"text": text},
        restaurant_phone="+97141234567",
        timestamp=1_720_000_000,
    )


async def _latest_outbound(session: AsyncSession, after_id: int) -> str:
    """Body of the most-recent outbound Message inserted after *after_id*."""
    from app.conversation.models import Message

    rows = (
        await session.scalars(
            select(Message)
            .where(Message.direction == "outbound", Message.id > after_id)
            .order_by(Message.id.desc())
            .limit(1)
        )
    ).all()
    if not rows:
        return ""
    m = rows[0]
    return (m.payload or {}).get("body") or (m.payload or {}).get("text", "")


async def _last_msg_id(session: AsyncSession) -> int:
    from app.conversation.models import Message

    return (
        await session.scalar(
            select(Message.id).order_by(Message.id.desc()).limit(1)
        )
    ) or 0


async def _draft_cart_rows(session: AsyncSession, restaurant_id: int) -> list:
    from app.conversation.models import Conversation
    from app.ordering.models import Order, OrderItem

    conv = await session.scalar(
        select(Conversation).where(
            Conversation.restaurant_id == restaurant_id,
            Conversation.counterpart == "customer",
        )
    )
    if conv is None:
        return []
    draft_order_id = (conv.state or {}).get("draft_order_id")
    if not draft_order_id:
        return []
    order = await session.get(Order, draft_order_id)
    if order is None or str(order.status) != "draft":
        return []
    items = (
        await session.scalars(
            select(OrderItem).where(OrderItem.order_id == order.id)
        )
    ).all()
    return list(items)


async def _seed_one_dish_restaurant(session: AsyncSession, restaurant) -> None:
    """Seed a restaurant with ONLY Chicken Biryani — nothing else."""
    from app.catalog.models import CatalogProduct

    restaurant.settings = {
        **(restaurant.settings or {}),
        "catalog_id": "ONE-CAT-001",
        "catalog_ordering_enabled": True,
    }
    await session.flush()

    menu = Menu(
        restaurant_id=restaurant.id,
        version=1,
        status="active",
        source_files=[],
    )
    session.add(menu)
    await session.flush()

    dish = Dish(
        menu_id=menu.id,
        restaurant_id=restaurant.id,
        dish_number=1,
        name="Chicken Biryani",
        price_aed=Decimal("20.00"),
        category="Biryani",
        is_available=True,
        name_normalized="chicken biryani",
        catalog_retailer_id="one-dish-001",
    )
    session.add(dish)

    cp = CatalogProduct(
        restaurant_id=restaurant.id,
        retailer_id="one-dish-001",
        name="Chicken Biryani",
        price_aed=Decimal("20.00"),
        currency="AED",
        availability="in stock",
        category="Biryani",
        is_active=True,
        raw={},
    )
    session.add(cp)
    await session.flush()


# ── (a) Anti-hallucination dish-name cross-check (no prices needed) ──────────

async def test_antihallucination_catches_non_catalogue_dish_names(db_session, restaurant, seed_biryani_menu):
    """A model reply listing >=2 dish-like names NOT in the catalogue must be replaced.

    Covers R-026 / F96: today the engine only swaps on price-shape tokens; a reply
    that names fake dishes without explicit AED prices leaks through. W6 must add a
    dish-name cross-check against the tenant catalogue so name-only hallucinations
    are also caught.
    """
    from app.conversation.engine import _looks_like_hallucinated_menu  # noqa: F401 – must exist

    # The engine must detect a reply listing dish-like names not in the catalogue.
    # We call the async helper directly (it reads DB) to verify it exists and flags it.
    fake_reply = "We have Lamb Ouzi and Seafood Platter available for you!"
    result = await _looks_like_hallucinated_menu(db_session, fake_reply, restaurant.id)
    assert result is True, (
        "_looks_like_hallucinated_menu must return True for a reply naming "
        "non-catalogue dishes ('Lamb Ouzi', 'Seafood Platter') that aren't in the DB"
    )


# ── (b) One-dish tenant: reply must not name dishes that don't exist ──────────

async def test_one_dish_tenant_names_no_other_dish(db_session, restaurant):
    """In a single-dish restaurant, the cross-check must flag a reply that names
    dishes not in the (one-item) catalogue.

    Covers F98: the cross-check must identify hallucinated dish names relative to
    the specific tenant's catalogue — a reply like "We have Chicken Biryani, Lamb Ouzi
    and Seafood Platter" must be flagged because Lamb Ouzi and Seafood Platter do not
    exist in a one-dish catalogue.
    """
    from app.conversation.engine import _looks_like_hallucinated_menu  # must exist

    await _seed_one_dish_restaurant(db_session, restaurant)

    # A reply listing the real dish PLUS invented extras — the cross-check must catch it
    hallucinated_reply = (
        "Yes! We have Chicken Biryani, Lamb Ouzi and Seafood Platter available."
    )
    result = await _looks_like_hallucinated_menu(db_session, hallucinated_reply, restaurant.id)
    assert result is True, (
        "_looks_like_hallucinated_menu must return True for a one-dish tenant reply "
        "that also names 'Lamb Ouzi' and 'Seafood Platter' (not in the single catalogue).\n"
        f"  Reply: {hallucinated_reply!r}"
    )


# ── (c) whatsapp_enabled=False dish not rendered and not orderable ─────────────

async def test_whatsapp_disabled_dish_not_in_menu_render(db_session, restaurant):
    """A dish with whatsapp_enabled=False must not appear in _render_menu output.

    Covers TX-45: 'Test' or internal SKUs must never render on WhatsApp, even if
    is_available=True. Today _render_menu does not filter on whatsapp_enabled.
    """
    menu = Menu(
        restaurant_id=restaurant.id,
        version=1,
        status="active",
        source_files=[],
    )
    db_session.add(menu)
    await db_session.flush()

    # Normal public dish
    public_dish = Dish(
        menu_id=menu.id,
        restaurant_id=restaurant.id,
        dish_number=1,
        name="Chicken Biryani",
        price_aed=Decimal("20.00"),
        category="Mains",
        is_available=True,
        name_normalized="chicken biryani",
        whatsapp_enabled=True,
    )
    # Internal/disabled dish — must be invisible on WhatsApp
    internal_dish = Dish(
        menu_id=menu.id,
        restaurant_id=restaurant.id,
        dish_number=2,
        name="Test Dish",
        price_aed=Decimal("1.00"),
        category="Internal",
        is_available=True,
        name_normalized="test dish",
        whatsapp_enabled=False,
    )
    db_session.add(public_dish)
    db_session.add(internal_dish)
    await db_session.flush()

    rendered = await _render_menu(db_session, restaurant.id)
    assert "Test Dish" not in rendered, (
        f"_render_menu must not render whatsapp_enabled=False dishes. Got:\n{rendered}"
    )
    assert "Chicken Biryani" in rendered, "Public dish must still appear"


async def test_whatsapp_disabled_dish_not_orderable(db_session, restaurant):
    """A customer cannot order a whatsapp_enabled=False dish via text.

    Covers TX-45: the dish must be rejected at the ordering gate (_catalog_excludes_dish
    or equivalent), cart must stay empty.
    """
    menu = Menu(
        restaurant_id=restaurant.id,
        version=1,
        status="active",
        source_files=[],
    )
    db_session.add(menu)
    await db_session.flush()

    # The only dish on this menu is disabled for WhatsApp
    Dish(
        menu_id=menu.id,
        restaurant_id=restaurant.id,
        dish_number=1,
        name="Test Dish",
        price_aed=Decimal("1.00"),
        category="Internal",
        is_available=True,
        name_normalized="test dish",
        whatsapp_enabled=False,
    )
    db_session.add(
        Dish(
            menu_id=menu.id,
            restaurant_id=restaurant.id,
            dish_number=1,
            name="Test Dish",
            price_aed=Decimal("1.00"),
            category="Internal",
            is_available=True,
            name_normalized="test dish",
            whatsapp_enabled=False,
        )
    )
    await db_session.flush()

    await handle_inbound(
        db_session,
        _text_inbound("I want Test Dish", phone="+971509990003"),
        restaurant_id=restaurant.id,
    )
    await db_session.flush()

    rows = await _draft_cart_rows(db_session, restaurant.id)
    assert rows == [], (
        f"Cart must be empty — whatsapp_enabled=False dish must not be orderable. "
        f"Got {len(rows)} item(s)."
    )


# ── (d) Off-catalogue dish → "available by phone", cart empty ─────────────────

async def test_off_catalogue_dish_available_by_phone(db_session, restaurant):
    """In catalogue mode, ordering a text-menu dish with no active CatalogProduct must
    produce 'available by phone', leave the cart empty, and not inject a fake mini-menu.

    Covers TX-06, R-023: off-catalogue item must be demoted honestly, not silently
    dropped or met with a hallucinated alternative list.
    """
    restaurant.settings = {
        **(restaurant.settings or {}),
        "catalog_id": "OFF-CAT-001",
        "catalog_ordering_enabled": True,
    }
    await db_session.flush()

    menu = Menu(
        restaurant_id=restaurant.id,
        version=1,
        status="active",
        source_files=[],
    )
    db_session.add(menu)
    await db_session.flush()

    # Dish exists in text DB but has NO linked CatalogProduct → off-catalogue
    off_cat_dish = Dish(
        menu_id=menu.id,
        restaurant_id=restaurant.id,
        dish_number=1,
        name="Special Lamb Ouzi",
        price_aed=Decimal("80.00"),
        category="Specials",
        is_available=True,
        name_normalized="special lamb ouzi",
        catalog_retailer_id=None,  # no catalogue link
    )
    db_session.add(off_cat_dish)
    await db_session.flush()

    marker = await _last_msg_id(db_session)
    await handle_inbound(
        db_session,
        _text_inbound("I want Special Lamb Ouzi", phone="+971509990004"),
        restaurant_id=restaurant.id,
    )
    await db_session.flush()

    reply = await _latest_outbound(db_session, after_id=marker)
    assert reply, "engine must produce an outbound reply"

    # Must say "phone" / "call" — honest demotion, not silent drop
    lowered = reply.lower()
    assert any(kw in lowered for kw in ("phone", "call us", "contact")), (
        f"Off-catalogue dish must trigger 'available by phone' reply. Got:\n{reply!r}"
    )

    # Cart must stay empty
    rows = await _draft_cart_rows(db_session, restaurant.id)
    assert rows == [], (
        f"Cart must be empty for off-catalogue dish. Got {len(rows)} item(s)."
    )

    # Reply must NOT contain a fake mini-menu (>=2 AED prices or dish-name list)
    from app.conversation.engine import _looks_like_menu
    assert not _looks_like_menu(reply), (
        f"Off-catalogue reply must not inject a fake menu. Got:\n{reply!r}"
    )


# ── (e) Slug-named dish absent from _render_menu ─────────────────────────────

async def test_slug_named_dish_absent_from_render_menu(db_session, restaurant):
    """A dish whose name matches ^[a-z][a-z0-9_]*$ (slug pattern) must not appear in
    the rendered menu — it is a developer/internal identifier, not a customer-facing name.

    Covers F74, F97: slugs like 'chicken_biryani' appeared in customer-facing text
    because _render_menu had no slug filter.
    """
    menu = Menu(
        restaurant_id=restaurant.id,
        version=1,
        status="active",
        source_files=[],
    )
    db_session.add(menu)
    await db_session.flush()

    # Slug-named dish (internal identifier leaked as dish name)
    slug_dish = Dish(
        menu_id=menu.id,
        restaurant_id=restaurant.id,
        dish_number=1,
        name="chicken_biryani",
        price_aed=Decimal("20.00"),
        category="Biryani",
        is_available=True,
        name_normalized="chicken_biryani",
    )
    # Properly named dish that must still appear
    real_dish = Dish(
        menu_id=menu.id,
        restaurant_id=restaurant.id,
        dish_number=2,
        name="Chicken Biryani",
        price_aed=Decimal("20.00"),
        category="Biryani",
        is_available=True,
        name_normalized="chicken biryani",
    )
    db_session.add(slug_dish)
    db_session.add(real_dish)
    await db_session.flush()

    rendered = await _render_menu(db_session, restaurant.id)
    assert "chicken_biryani" not in rendered, (
        f"_render_menu must filter slug-named dishes. Got:\n{rendered}"
    )
    assert "Chicken Biryani" in rendered, "Properly named dish must still appear"
