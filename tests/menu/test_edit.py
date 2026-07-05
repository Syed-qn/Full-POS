async def _upload(client, auth_headers):
    files = [("files", ("menu.jpg", b"\xff\xd8", "image/jpeg"))]
    resp = await client.post("/api/v1/menus", files=files, headers=auth_headers)
    return resp.json()


async def test_blank_menu_lets_you_add_first_dish_without_upload(client, auth_headers):
    """A fresh restaurant (no upload) can start a menu: /menus/blank returns an empty
    active menu, and dishes can be added straight to it."""
    blank = await client.post("/api/v1/menus/blank", headers=auth_headers)
    assert blank.status_code == 201
    menu = blank.json()
    assert menu["status"] == "active"
    assert menu["dishes"] == []

    added = await client.post(
        f"/api/v1/menus/{menu['id']}/dishes",
        json={"dish_number": 1, "name": "Chai", "price_aed": "3.00", "category": "Drinks"},
        headers=auth_headers,
    )
    assert added.status_code == 201

    # Idempotent: calling blank again returns the SAME active menu, not a new one.
    again = await client.post("/api/v1/menus/blank", headers=auth_headers)
    assert again.json()["id"] == menu["id"]


async def test_add_dish(client, auth_headers):
    menu = await _upload(client, auth_headers)
    resp = await client.post(
        f"/api/v1/menus/{menu['id']}/dishes",
        json={"dish_number": 301, "name": "Falooda", "price_aed": "12.00",
              "category": "Desserts"},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    assert resp.json()["dish_number"] == 301


async def test_patch_dish_price_and_name(client, auth_headers):
    menu = await _upload(client, auth_headers)
    dish = menu["dishes"][0]
    resp = await client.patch(
        f"/api/v1/menus/{menu['id']}/dishes/{dish['id']}",
        json={"price_aed": "24.00", "name": "Chicken Biryani (Large)"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["price_aed"] == "24.00"
    assert resp.json()["name"] == "Chicken Biryani (Large)"


async def test_delete_dish(client, auth_headers):
    menu = await _upload(client, auth_headers)
    dish = menu["dishes"][0]
    resp = await client.delete(
        f"/api/v1/menus/{menu['id']}/dishes/{dish['id']}", headers=auth_headers
    )
    assert resp.status_code == 204
    menu_after = (
        await client.get(f"/api/v1/menus/{menu['id']}", headers=auth_headers)
    ).json()
    assert dish["id"] not in [d["id"] for d in menu_after["dishes"]]


async def test_delete_dish_with_order_history_archives(client, auth_headers, db_session):
    """Dishes that were ordered can't be hard-deleted — they're archived off the menu."""
    from datetime import datetime, timedelta, timezone
    from decimal import Decimal

    from sqlalchemy import select

    from app.identity.models import Restaurant
    from app.menu.models import Dish
    from app.ordering.models import Customer, Order, OrderItem

    menu = await _upload(client, auth_headers)
    dish_id = menu["dishes"][0]["id"]
    rest = await db_session.scalar(
        select(Restaurant).where(Restaurant.phone == "+971501234567")
    )
    dish = await db_session.get(Dish, dish_id)
    customer = Customer(
        restaurant_id=rest.id, phone="+971509876543", name="Cust",
        usual_order_times={}, tags={}, total_orders=0, total_spend=Decimal("0.00"),
    )
    db_session.add(customer)
    await db_session.flush()
    now = datetime.now(timezone.utc)
    order = Order(
        restaurant_id=rest.id, customer_id=customer.id,
        order_number="R1-DEL1", status="confirmed",
        priority="normal", weather_delay_disclosed=False,
        delivery_fee_aed=Decimal("0.00"),
        subtotal=Decimal("22.00"), total=Decimal("22.00"),
        sla_confirmed_at=now,
        sla_deadline=now + timedelta(minutes=40),
    )
    db_session.add(order)
    await db_session.flush()
    db_session.add(OrderItem(
        order_id=order.id, dish_id=dish.id,
        dish_number=dish.dish_number or 1, dish_name=dish.name,
        price_aed=dish.price_aed or Decimal("22.00"), qty=1,
    ))
    await db_session.commit()

    resp = await client.delete(
        f"/api/v1/menus/{menu['id']}/dishes/{dish_id}", headers=auth_headers
    )
    assert resp.status_code == 204

    menu_after = (
        await client.get(f"/api/v1/menus/{menu['id']}", headers=auth_headers)
    ).json()
    assert dish_id not in [d["id"] for d in menu_after["dishes"]]

    await db_session.refresh(dish)
    assert dish.meta_status == "archived"
    assert dish.is_available is False
    assert dish.whatsapp_enabled is False


async def test_upload_dish_image_returns_servable_url(client, auth_headers):
    # 1x1 PNG.
    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00"
        b"\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    resp = await client.post(
        "/api/v1/dishes/image",
        files=[("file", ("dish.png", png, "image/png"))],
        headers=auth_headers,
    )
    assert resp.status_code == 201
    url = resp.json()["url"]
    assert "/media/dishes/" in url
    # The returned URL is publicly servable (Meta fetches it as image_link).
    served = await client.get(url[url.index("/media/") :])
    assert served.status_code == 200
    assert served.headers["content-type"] == "image/jpeg"


async def test_upload_dish_image_rejects_non_image(client, auth_headers):
    resp = await client.post(
        "/api/v1/dishes/image",
        files=[("file", ("notes.txt", b"hello", "text/plain"))],
        headers=auth_headers,
    )
    assert resp.status_code == 422


async def test_add_dish_persists_meta_fields(client, auth_headers):
    """Create a dish through the API with the Meta catalogue fields and confirm they
    round-trip (image, sale price) plus the auto-defaulted fields (condition/status)."""
    menu = await _upload(client, auth_headers)
    resp = await client.post(
        f"/api/v1/menus/{menu['id']}/dishes",
        json={
            "dish_number": 305, "name": "Kunafa", "price_aed": "15.00",
            "category": "Desserts",
            "image_url": "https://example.com/media/dishes/1/x.png",
            "sale_price_aed": "12.00",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["image_url"] == "https://example.com/media/dishes/1/x.png"
    assert body["sale_price_aed"] == "12.00"
    # Defaults applied even though the manager didn't send them.
    assert body["condition"] == "new"
    assert body["meta_status"] == "active"


async def test_add_dish_rejects_sale_price_not_positive(client, auth_headers):
    menu = await _upload(client, auth_headers)
    resp = await client.post(
        f"/api/v1/menus/{menu['id']}/dishes",
        json={"dish_number": 306, "name": "Bad", "price_aed": "10.00",
              "sale_price_aed": "0"},
        headers=auth_headers,
    )
    assert resp.status_code == 422


async def test_duplicate_dish_number_409(client, auth_headers):
    menu = await _upload(client, auth_headers)
    resp = await client.post(
        f"/api/v1/menus/{menu['id']}/dishes",
        json={"dish_number": 110, "name": "Clone", "price_aed": "9.00"},
        headers=auth_headers,
    )
    assert resp.status_code == 409


async def test_toggle_availability(client, auth_headers):
    menu = await _upload(client, auth_headers)
    await client.post(f"/api/v1/menus/{menu['id']}/activate", headers=auth_headers)
    dish = menu["dishes"][0]

    resp = await client.patch(
        f"/api/v1/dishes/{dish['id']}/availability",
        json={"is_available": False}, headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["is_available"] is False
