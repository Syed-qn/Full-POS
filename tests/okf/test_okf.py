"""OKF producer + lexical retrieval."""
import copy
from decimal import Decimal

from sqlalchemy import select

from app.identity.models import DEFAULT_SETTINGS, Restaurant
from app.menu.models import Dish, Menu
from app.okf import producer, retrieval
from app.okf.models import OkfDoc
from app.ordering.models import Customer, Order


async def _resto(db_session):
    s = copy.deepcopy(DEFAULT_SETTINGS)
    r = Restaurant(name="OKF Biryani", phone="+97140000500", password_hash="x", lat=25.2, lng=55.2, settings=s)
    db_session.add(r)
    await db_session.flush()
    menu = Menu(restaurant_id=r.id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    db_session.add(Dish(menu_id=menu.id, restaurant_id=r.id, dish_number=110, name="Chicken Biryani",
                        price_aed=Decimal("22.00"), category="Rice", is_available=True,
                        name_normalized="chicken biryani", description="Fragrant basmati, halal chicken, mild spice."))
    await db_session.flush()
    return r


async def test_refresh_menu_and_policy_creates_docs(db_session):
    r = await _resto(db_session)
    n = await producer.refresh_menu_and_policy(db_session, restaurant_id=r.id)
    assert n >= 3  # restaurant + policy + 1 dish
    kinds = {d.kind for d in (await db_session.scalars(select(OkfDoc).where(OkfDoc.restaurant_id == r.id))).all()}
    assert {"restaurant", "policy", "dish"} <= kinds


async def test_refresh_is_idempotent(db_session):
    r = await _resto(db_session)
    await producer.refresh_menu_and_policy(db_session, restaurant_id=r.id)
    await producer.refresh_menu_and_policy(db_session, restaurant_id=r.id)
    docs = (await db_session.scalars(select(OkfDoc).where(OkfDoc.restaurant_id == r.id, OkfDoc.kind == "dish"))).all()
    assert len(docs) == 1  # upsert, no duplicate


async def test_retrieval_finds_policy_and_dish(db_session):
    r = await _resto(db_session)
    await producer.refresh_menu_and_policy(db_session, restaurant_id=r.id)
    # halal question -> should surface the dish doc (mentions halal)
    docs = await retrieval.retrieve(db_session, restaurant_id=r.id, query="is the chicken halal")
    titles = " ".join(d.title.lower() for d in docs)
    bodies = " ".join(d.body.lower() for d in docs)
    assert "halal" in bodies  # grounded fact present
    # policy is always pinned
    assert any(d.kind == "policy" for d in docs)


async def test_retrieval_grounding_block(db_session):
    r = await _resto(db_session)
    await producer.refresh_menu_and_policy(db_session, restaurant_id=r.id)
    docs = await retrieval.retrieve(db_session, restaurant_id=r.id, query="delivery fee")
    block = retrieval.grounding_block(docs)
    assert "GROUNDED KNOWLEDGE" in block and "NEVER invent" in block


async def test_customer_doc_grounds_wallet_and_tier(db_session):
    r = await _resto(db_session)
    c = Customer(restaurant_id=r.id, phone="+971500500001", name="Sara", loyalty_tier="gold",
                 total_orders=4, total_spend=Decimal("200.00"))
    db_session.add(c)
    await db_session.flush()
    n = await producer.refresh_customer(db_session, restaurant_id=r.id, customer_id=c.id)
    assert n == 1
    docs = await retrieval.retrieve(db_session, restaurant_id=r.id, query="my loyalty tier", customer_id=c.id)
    body = " ".join(d.body.lower() for d in docs)
    assert "gold" in body  # customer profile pinned + grounded


async def test_order_doc(db_session):
    r = await _resto(db_session)
    c = Customer(restaurant_id=r.id, phone="+971500500002", name="X", total_orders=1, total_spend=Decimal("22"))
    db_session.add(c)
    await db_session.flush()
    o = Order(restaurant_id=r.id, customer_id=c.id, order_number="R1-9001", status="preparing",
              subtotal=Decimal("22.00"), total=Decimal("22.00"))
    db_session.add(o)
    await db_session.flush()
    n = await producer.refresh_order(db_session, restaurant_id=r.id, order_id=o.id)
    assert n == 1
    doc = await db_session.scalar(select(OkfDoc).where(OkfDoc.kind == "order", OkfDoc.entity_id == o.id))
    assert "preparing" in doc.body.lower()


async def test_retrieval_multilingual_pins_dish_by_entity(db_session):
    """A non-English (Telugu) question can't lexically match English docs, but the
    cart's dish is pinned by entity_id → still grounded."""
    r = await _resto(db_session)
    await producer.refresh_menu_and_policy(db_session, restaurant_id=r.id)
    dish = (await db_session.scalars(select(OkfDoc).where(OkfDoc.restaurant_id == r.id, OkfDoc.kind == "dish"))).first()
    # Telugu text, zero English trigram overlap.
    docs = await retrieval.retrieve(
        db_session, restaurant_id=r.id, query="ఇది హలాల్ నా?",
        dish_ids=[dish.entity_id],
    )
    assert any(d.kind == "dish" for d in docs)  # pinned despite no lexical match
    assert any(d.kind == "policy" for d in docs)


async def test_retrieval_is_tenant_isolated(db_session):
    """Restaurant A never retrieves Restaurant B's OKF docs."""
    ra = await _resto(db_session)
    await producer.refresh_menu_and_policy(db_session, restaurant_id=ra.id)
    rb = Restaurant(name="Other Resto", phone="+97140000599", password_hash="x", lat=25.0, lng=55.0)
    db_session.add(rb)
    await db_session.flush()
    from app.menu.models import Dish, Menu
    mb = Menu(restaurant_id=rb.id, version=1, status="active", source_files=[])
    db_session.add(mb)
    await db_session.flush()
    db_session.add(Dish(menu_id=mb.id, restaurant_id=rb.id, dish_number=1, name="Secret Dish",
                        price_aed=Decimal("99"), category="X", is_available=True, name_normalized="secret dish"))
    await db_session.flush()
    await producer.refresh_menu_and_policy(db_session, restaurant_id=rb.id)

    docs = await retrieval.retrieve(db_session, restaurant_id=ra.id, query="secret dish")
    assert all(d.restaurant_id == ra.id for d in docs)
    assert not any("secret" in d.body.lower() for d in docs)
