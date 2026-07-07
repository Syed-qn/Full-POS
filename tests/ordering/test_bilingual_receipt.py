from decimal import Decimal

import pytest

from app.ordering.receipt_i18n import bilingual_labels


def test_bilingual_labels_has_en_and_ar_keys():
    labels = bilingual_labels()
    assert set(labels.keys()) == {"en", "ar"}
    assert labels["en"]["title"] == "Tax Invoice"
    assert labels["ar"]["title"] == "فاتورة ضريبية"
    # Every English label key must have a corresponding Arabic translation.
    assert set(labels["en"].keys()) == set(labels["ar"].keys())


def test_bilingual_labels_covers_core_invoice_fields():
    labels = bilingual_labels()
    for key in ("title", "subtotal", "vat", "total", "trn"):
        assert key in labels["en"]
        assert key in labels["ar"]
        assert labels["ar"][key]  # non-empty translation


@pytest.mark.anyio
async def test_tax_invoice_includes_arabic_labels(client, auth_headers, db_session):
    from sqlalchemy import select

    from app.identity.models import Restaurant
    from app.menu.models import Dish, Menu
    from app.ordering.models import Customer, Order, OrderItem

    restaurant = await db_session.scalar(
        select(Restaurant).where(Restaurant.email == "owner@biryani.ae")
    )
    menu = Menu(restaurant_id=restaurant.id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    dish = Dish(
        menu_id=menu.id, restaurant_id=restaurant.id, dish_number=1, name="Kebab",
        price_aed=Decimal("20.00"), is_available=True, name_normalized="kebab",
    )
    db_session.add(dish)
    cust = Customer(restaurant_id=restaurant.id, phone="+971500000801", name="Bilingual Test")
    db_session.add(cust)
    await db_session.flush()
    order = Order(
        restaurant_id=restaurant.id, customer_id=cust.id, order_number="BL-0001",
        status="confirmed", subtotal=Decimal("20.00"), total=Decimal("20.00"),
    )
    db_session.add(order)
    await db_session.flush()
    db_session.add(OrderItem(
        order_id=order.id, dish_id=dish.id, dish_number=1, dish_name="Kebab",
        price_aed=Decimal("20.00"), qty=1,
    ))
    await db_session.commit()

    resp = await client.get(f"/api/v1/orders/{order.id}/tax-invoice", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["labels_ar"]["title"] == "فاتورة ضريبية"
    assert body["labels_ar"]["total"] == "الإجمالي"
    # Dynamic data (dish names) must NOT be translated — out of scope.
    assert body["line_items"][0]["dish_name"] == "Kebab"
