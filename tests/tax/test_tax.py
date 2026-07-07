from decimal import Decimal

import pytest

from app.ordering.tax import apply_vat, build_tax_invoice


@pytest.mark.anyio
async def test_apply_vat_computes_and_snapshots_amount():
    from app.ordering.models import Order

    order = Order(subtotal=Decimal("100.00"), total=Decimal("105.00"))
    apply_vat(order, vat_rate=Decimal("0.0500"))
    assert order.vat_rate == Decimal("0.0500")
    assert order.vat_amount_aed == Decimal("5.00")


@pytest.mark.anyio
async def test_apply_vat_default_rate_is_five_percent():
    from app.ordering.models import Order

    order = Order(subtotal=Decimal("200.00"), total=Decimal("210.00"))
    apply_vat(order)
    assert order.vat_amount_aed == Decimal("10.00")


@pytest.mark.anyio
async def test_build_tax_invoice_shape(db_session, restaurant):
    from decimal import Decimal as D

    from app.menu.models import Dish, Menu
    from app.ordering.models import Customer, Order, OrderItem

    restaurant.settings = {**restaurant.settings, "trn": "100123456700003"}
    cust = Customer(restaurant_id=restaurant.id, phone="+971500000022", name="Invoice Test")
    db_session.add(cust)
    menu = Menu(restaurant_id=restaurant.id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    dish = Dish(
        menu_id=menu.id, restaurant_id=restaurant.id, dish_number=1, name="Kebab",
        price_aed=D("100.00"), is_available=True, name_normalized="kebab",
    )
    db_session.add(dish)
    await db_session.flush()
    order = Order(
        restaurant_id=restaurant.id, customer_id=cust.id, order_number="INV-0001",
        status="confirmed", subtotal=D("100.00"), delivery_fee_aed=D("5.00"),
        total=D("105.00"), vat_rate=D("0.0500"), vat_amount_aed=D("5.00"),
    )
    db_session.add(order)
    await db_session.flush()
    db_session.add(OrderItem(
        order_id=order.id, dish_id=dish.id, dish_number=1, dish_name="Kebab",
        price_aed=D("100.00"), qty=1,
    ))
    await db_session.commit()

    invoice = await build_tax_invoice(db_session, order_id=order.id, restaurant_id=restaurant.id)
    assert invoice["trn"] == "100123456700003"
    assert invoice["invoice_number"] == "INV-0001"
    assert invoice["vat_rate"] == "0.0500"
    assert invoice["vat_amount_aed"] == "5.00"
    assert invoice["total_aed"] == "105.00"
    assert len(invoice["line_items"]) == 1
    assert invoice["line_items"][0]["dish_name"] == "Kebab"
