from decimal import Decimal

import pytest

from app.ordering.duplicate import duplicate_order


@pytest.mark.anyio
async def test_duplicate_order_copies_items_as_new_draft(db_session, restaurant):
    from app.menu.models import Dish, Menu
    from app.ordering.models import Customer, CustomerAddress, Order, OrderItem

    menu = Menu(restaurant_id=restaurant.id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    dish = Dish(
        menu_id=menu.id, restaurant_id=restaurant.id, dish_number=1, name="Kebab",
        price_aed=Decimal("20.00"), is_available=True, name_normalized="kebab",
    )
    db_session.add(dish)
    cust = Customer(restaurant_id=restaurant.id, phone="+971500000870", name="Repeat Test")
    db_session.add(cust)
    await db_session.flush()
    addr = CustomerAddress(customer_id=cust.id, latitude=25.2, longitude=55.3, confirmed=True)
    db_session.add(addr)
    await db_session.flush()
    original = Order(
        restaurant_id=restaurant.id, customer_id=cust.id, order_number="DUP-0001",
        status="delivered", address_id=addr.id, subtotal=Decimal("40.00"),
        delivery_fee_aed=Decimal("5.00"), total=Decimal("45.00"),
    )
    db_session.add(original)
    await db_session.flush()
    db_session.add(OrderItem(
        order_id=original.id, dish_id=dish.id, dish_number=1, dish_name="Kebab",
        price_aed=Decimal("20.00"), qty=2,
    ))
    await db_session.commit()

    new_order = await duplicate_order(db_session, restaurant_id=restaurant.id, order_id=original.id)
    await db_session.commit()

    assert new_order.id != original.id
    assert new_order.status == "draft"
    assert new_order.customer_id == original.customer_id
    assert new_order.address_id == original.address_id
    assert new_order.subtotal == Decimal("40.00")

    from sqlalchemy import select

    items = (await db_session.scalars(
        select(OrderItem).where(OrderItem.order_id == new_order.id)
    )).all()
    assert len(items) == 1
    assert items[0].dish_name == "Kebab"
    assert items[0].qty == 2
