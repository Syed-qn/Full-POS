"""E-08 OKF retrieval cap + E-20 provenance cite tags."""
import re
from decimal import Decimal

from sqlalchemy import select

from app.menu.models import Dish, Menu
from app.okf import producer, retrieval
from app.okf.models import OkfDoc
from app.ordering.models import Customer, Order


def _make_doc(**kwargs) -> OkfDoc:
    defaults = {
        "id": 1,
        "restaurant_id": 1,
        "kind": "policy",
        "slug": "policy",
        "entity_id": None,
        "title": "Test policy",
        "body": "Short grounded fact.",
        "frontmatter": {},
        "search_text": "test policy",
    }
    defaults.update(kwargs)
    return OkfDoc(**defaults)


def test_grounding_block_header_cite_instruction():
    block = retrieval.grounding_block([_make_doc()])
    assert "Cite only [okf:…]" in block
    assert "defer to team phone" in block
    assert "NEVER invent" in block


def test_grounding_block_cite_uses_entity_id():
    doc = _make_doc(kind="dish", entity_id=42, id=99, title="Chicken Biryani", body="AED 22")
    block = retrieval.grounding_block([doc])
    assert "[okf:dish:42]" in block
    assert "[okf:dish:99]" not in block


def test_grounding_block_cite_falls_back_to_doc_id():
    doc = _make_doc(kind="policy", entity_id=None, id=7, title="Delivery policy")
    block = retrieval.grounding_block([doc])
    assert "[okf:policy:7]" in block


def test_grounding_block_truncates_long_body():
    doc = _make_doc(body="word " * 80)
    block = retrieval.grounding_block([doc])
    assert "…" in block
    assert len(doc.body) > 200
    _, _, body = block.partition("\n\n[okf:")
    _, _, body = body.partition("\n")
    assert len(body.strip()) <= 200


def test_grounding_block_caps_at_four_docs():
    docs = [
        _make_doc(id=i, kind="dish", entity_id=i, title=f"Dish {i}", body=f"fact {i}")
        for i in range(10)
    ]
    block = retrieval.grounding_block(docs)
    cites = re.findall(r"\[okf:(?:policy|order|customer|restaurant|dish):\d+\]", block)
    assert len(cites) == 4


def test_grounding_block_total_char_budget():
    docs = [
        _make_doc(id=i, kind="dish", entity_id=i, title=f"Dish number {i}", body="detail " * 60)
        for i in range(4)
    ]
    block = retrieval.grounding_block(docs)
    assert len(block) <= retrieval._MAX_GROUNDING_CHARS


async def test_retrieve_max_docs_default_is_four(db_session):
    from tests.okf.test_okf import _resto

    r = await _resto(db_session)
    await producer.refresh_menu_and_policy(db_session, restaurant_id=r.id)
    menu = (await db_session.scalars(select(Menu).where(Menu.restaurant_id == r.id))).first()
    for i in range(2, 7):
        db_session.add(
            Dish(
                menu_id=menu.id,
                restaurant_id=r.id,
                dish_number=i,
                name=f"Extra Dish {i}",
                price_aed=Decimal("10"),
                category="Rice",
                is_available=True,
                name_normalized=f"extra dish {i}",
                description=f"unique searchable keyword alpha{i}beta",
            )
        )
    await db_session.flush()
    await producer.refresh_menu_and_policy(db_session, restaurant_id=r.id)

    docs = await retrieval.retrieve(
        db_session,
        restaurant_id=r.id,
        query="alpha3beta alpha4beta alpha5beta alpha6beta",
    )
    assert len(docs) <= 4


async def test_retrieve_priority_pins_before_lexical(db_session):
    from tests.okf.test_okf import _resto

    r = await _resto(db_session)
    await producer.refresh_menu_and_policy(db_session, restaurant_id=r.id)
    dish_doc = (
        await db_session.scalars(
            select(OkfDoc).where(OkfDoc.restaurant_id == r.id, OkfDoc.kind == "dish")
        )
    ).first()
    c = Customer(
        restaurant_id=r.id,
        phone="+971500500010",
        name="Priya",
        loyalty_tier="silver",
        total_orders=2,
        total_spend=Decimal("50"),
    )
    db_session.add(c)
    await db_session.flush()
    o = Order(
        restaurant_id=r.id,
        customer_id=c.id,
        order_number="R1-9010",
        status="confirmed",
        subtotal=Decimal("22"),
        total=Decimal("22"),
    )
    db_session.add(o)
    await db_session.flush()
    await producer.refresh_customer(db_session, restaurant_id=r.id, customer_id=c.id)
    await producer.refresh_order(db_session, restaurant_id=r.id, order_id=o.id)

    docs = await retrieval.retrieve(
        db_session,
        restaurant_id=r.id,
        query="halal chicken delivery fee",
        customer_id=c.id,
        order_id=o.id,
        dish_ids=[dish_doc.entity_id],
        max_docs=4,
    )
    assert len(docs) == 4
    kinds = [d.kind for d in docs]
    assert kinds == ["policy", "order", "customer", "restaurant"]


async def test_retrieve_respects_custom_max_docs(db_session):
    from tests.okf.test_okf import _resto

    r = await _resto(db_session)
    await producer.refresh_menu_and_policy(db_session, restaurant_id=r.id)
    docs = await retrieval.retrieve(db_session, restaurant_id=r.id, query="", max_docs=2)
    assert len(docs) == 2
    kinds = [d.kind for d in docs]
    assert kinds == ["policy", "restaurant"]