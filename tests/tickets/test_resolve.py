import pytest
from sqlalchemy import select




async def test_create_replacement_order_clones_and_resolves(db_session, seed_restaurant_customer):
    from decimal import Decimal
    from app.menu.models import Dish, Menu
    from app.ordering.models import Order, OrderItem
    from app.tickets import service as t

    rid, cid = seed_restaurant_customer
    menu = Menu(restaurant_id=rid, version=1, status="active", source_files=[])
    db_session.add(menu); await db_session.flush()
    dish = Dish(menu_id=menu.id, restaurant_id=rid, dish_number=1, name="Biryani",
                price_aed=Decimal("30.00"), category="Rice", is_available=True,
                name_normalized="biryani")
    db_session.add(dish); await db_session.flush()
    orig = Order(restaurant_id=rid, customer_id=cid, order_number="O-1", status="delivered",
                 subtotal=Decimal("30.00"), total=Decimal("30.00"))
    db_session.add(orig); await db_session.flush()
    db_session.add(OrderItem(order_id=orig.id, dish_id=dish.id, dish_number=1,
                             dish_name="Biryani", price_aed=Decimal("30.00"), qty=2))
    await db_session.flush()

    tk = await t.create_ticket(db_session, restaurant_id=rid, customer_id=cid,
                               order_id=orig.id, source_message="cold")
    tk = await t.create_replacement_order(db_session, restaurant_id=rid, ticket_id=tk.id,
                                          note="remaking free", created_by="mgr:1")
    assert tk.status == "resolved"
    assert tk.resolution_action == "replacement"
    rep = await db_session.get(Order, tk.replacement_order_id)
    assert rep is not None
    assert rep.total == Decimal("0.00")          # free
    assert rep.status == "confirmed"             # entered the kitchen/dispatch pipeline
    items = (await db_session.scalars(select(OrderItem).where(OrderItem.order_id == rep.id))).all()
    assert sum(i.qty for i in items) == 2        # cloned items


async def test_create_replacement_requires_order(db_session, seed_restaurant_customer):
    from app.tickets import service as t
    from app.tickets.service import TicketError
    rid, cid = seed_restaurant_customer
    tk = await t.create_ticket(db_session, restaurant_id=rid, customer_id=cid,
                               order_id=None, source_message="cold")
    with pytest.raises(TicketError):
        await t.create_replacement_order(db_session, restaurant_id=rid, ticket_id=tk.id,
                                         note="x", created_by="mgr:1")