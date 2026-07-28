"""One kitchen must never see or touch another's — across restaurants OR branches.

A kitchen display is left unattended on a counter all service, so it is the
screen most likely to be reachable by someone who should not have it. Every KDS
endpoint that takes an id in the URL is therefore attacked here with a VALID
token from a different restaurant: valid auth plus someone else's id is exactly
the shape that leaks tenants, because the guard on the route only proves the
caller is signed in somewhere, not that the row is theirs.

Branches count as separate tenants for this. Two branches of one business share
an owner but not a kitchen, and a ticket appearing on the wrong branch's pass
means food cooked in the wrong building.
"""
import pytest
from decimal import Decimal


async def _restaurant(client, *, name: str, email: str) -> dict:
    """A standalone restaurant plus an owner session for it."""
    signup = await client.post(
        "/api/v1/auth/signup",
        json={"name": name, "email": email, "password": "hunter2!"},
    )
    assert signup.status_code == 201, signup.text
    login = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": "hunter2!"}
    )
    assert login.status_code == 200, login.text
    return {
        "id": signup.json()["id"],
        "headers": {"Authorization": f"Bearer {login.json()['access_token']}"},
    }


async def _station(client, headers: dict) -> int:
    resp = await client.post(
        "/api/v1/kds/stations", json={"name": "Grill"}, headers=headers
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _order_item(db_session, restaurant_id: int) -> int:
    """A kitchen ticket line belonging to ``restaurant_id``."""
    from app.menu.models import Dish, Menu
    from app.ordering.models import Customer, Order, OrderItem

    menu = Menu(restaurant_id=restaurant_id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    dish = Dish(
        menu_id=menu.id, restaurant_id=restaurant_id, dish_number=1,
        name="Biryani", price_aed=Decimal("10.00"), category="Mains",
        is_available=True, name_normalized="biryani",
    )
    db_session.add(dish)
    await db_session.flush()

    customer = Customer(restaurant_id=restaurant_id, phone=f"+9715000{restaurant_id:05d}")
    db_session.add(customer)
    await db_session.flush()

    order = Order(
        restaurant_id=restaurant_id,
        customer_id=customer.id,
        order_number=f"KDS-{restaurant_id}",
        status="preparing",
        priority="normal",
        delivery_fee_aed=Decimal("0.00"),
        subtotal=Decimal("10.00"),
        total=Decimal("10.00"),
    )
    db_session.add(order)
    await db_session.flush()

    item = OrderItem(
        order_id=order.id,
        dish_id=dish.id,
        dish_number=1,
        dish_name="Biryani",
        price_aed=Decimal("10.00"),
        qty=1,
        kitchen_status="received",
    )
    db_session.add(item)
    await db_session.flush()
    await db_session.commit()
    return item.id


@pytest.mark.anyio
async def test_another_restaurant_cannot_reach_this_kitchens_station(client):
    """Station reads and writes, attacked with a valid foreign token."""
    ours = await _restaurant(client, name="La Cafe", email="a@test.ae")
    theirs = await _restaurant(client, name="Shawarma Co", email="b@test.ae")
    station_id = await _station(client, ours["headers"])

    # Sanity: the owner can reach it, so a 404 below means "not yours", not
    # "route broken" — without this the test would pass even if the endpoint
    # 404'd for everyone.
    mine = await client.get(
        f"/api/v1/kds/stations/{station_id}/tickets", headers=ours["headers"]
    )
    assert mine.status_code == 200, mine.text

    for method, path in [
        ("get", f"/api/v1/kds/stations/{station_id}/tickets"),
        ("patch", f"/api/v1/kds/stations/{station_id}"),
        ("delete", f"/api/v1/kds/stations/{station_id}"),
    ]:
        resp = await getattr(client, method)(
            path,
            headers=theirs["headers"],
            **({"json": {"name": "Stolen"}} if method == "patch" else {}),
        )
        assert resp.status_code == 404, (method, path, resp.status_code, resp.text)

    # And the station still exists, untouched.
    still = await client.get("/api/v1/kds/stations", headers=ours["headers"])
    assert any(s["id"] == station_id for s in still.json()), still.text


@pytest.mark.anyio
async def test_another_restaurant_cannot_bump_or_edit_this_kitchens_tickets(
    client, db_session
):
    """Every item-level route. Bumping someone else's line would tell their pass
    the food is plated when it is not."""
    ours = await _restaurant(client, name="La Cafe", email="a@test.ae")
    theirs = await _restaurant(client, name="Shawarma Co", email="b@test.ae")
    item_id = await _order_item(db_session, ours["id"])

    attacks = [
        ("patch", f"/api/v1/kds/items/{item_id}/bump", None),
        ("patch", f"/api/v1/kds/items/{item_id}/start-prep", None),
        ("patch", f"/api/v1/kds/items/{item_id}/recall", None),
        ("post", f"/api/v1/kds/items/{item_id}/packaging-check", {"passed": True}),
        ("post", f"/api/v1/kds/items/{item_id}/quality-check", {"passed": True}),
        ("post", f"/api/v1/kds/items/{item_id}/missing-item", {"reason": "x"}),
    ]
    for method, path, body in attacks:
        resp = await getattr(client, method)(
            path, headers=theirs["headers"], **({"json": body} if body else {})
        )
        assert resp.status_code == 404, (method, path, resp.status_code, resp.text)

    # The line was never touched: still unbumped for its real owner.
    from app.ordering.models import OrderItem

    await db_session.refresh(await db_session.get(OrderItem, item_id))
    item = await db_session.get(OrderItem, item_id)
    assert item.kitchen_status != "ready", "a foreign token bumped this line"


@pytest.mark.anyio
async def test_one_branch_cannot_see_another_branchs_kitchen(client):
    """Branches of ONE business are still separate kitchens.

    They share an owner, so an ownership check that stopped at "same
    organization" would pass here — and a ticket would surface on the wrong
    branch's pass, meaning food cooked in the wrong building.
    """
    hq_email = "hq@biryani.ae"
    await client.post(
        "/api/v1/organizations/signup",
        json={"name": "Biryani Group", "owner_email": hq_email, "password": "hunter2!"},
    )
    login = await client.post(
        "/api/v1/organizations/login",
        json={"owner_email": hq_email, "password": "hunter2!"},
    )
    hq = {"Authorization": f"Bearer {login.json()['access_token']}"}

    branches = []
    for name in ("Deira", "Marina"):
        made = await client.post(
            "/api/v1/organizations/branches",
            json={"name": name, "lat": 25.2, "lng": 55.2},
            headers=hq,
        )
        assert made.status_code == 201, made.text
        sess = await client.post(
            f"/api/v1/organizations/branches/{made.json()['id']}/session", headers=hq
        )
        branches.append(
            {"Authorization": f"Bearer {sess.json()['access_token']}"}
        )

    deira, marina = branches
    deira_station = await _station(client, deira)

    # Marina's own board must not list Deira's kitchen...
    listed = await client.get("/api/v1/kds/stations", headers=marina)
    assert deira_station not in [s["id"] for s in listed.json()], listed.text

    # ...nor reach it by id.
    for method, path in [
        ("get", f"/api/v1/kds/stations/{deira_station}/tickets"),
        ("patch", f"/api/v1/kds/stations/{deira_station}"),
        ("delete", f"/api/v1/kds/stations/{deira_station}"),
    ]:
        resp = await getattr(client, method)(
            path, headers=marina, **({"json": {"name": "X"}} if method == "patch" else {})
        )
        assert resp.status_code == 404, (method, path, resp.status_code, resp.text)


@pytest.mark.anyio
async def test_kitchen_board_needs_a_session_at_all(client):
    """An unattended display must not serve tickets to an anonymous caller."""
    for path in ("/api/v1/kds/stations", "/api/v1/kds/ready-for-pickup"):
        resp = await client.get(path)
        assert resp.status_code == 401, (path, resp.status_code)


async def _staff_headers(client, auth_headers: dict, *, name: str, role: str, pin: str) -> dict:
    """A real staff PIN session for ``role`` at the caller's restaurant."""
    from app.identity.auth import create_access_token

    made = await client.post(
        "/api/v1/staff", json={"name": name, "role": role, "pin": pin},
        headers=auth_headers,
    )
    assert made.status_code == 201, made.text
    return {
        "Authorization": "Bearer "
        + create_access_token(
            staff_id=made.json()["id"], audience="staff", extra_claims={"role": role}
        )
    }


@pytest.mark.anyio
@pytest.mark.parametrize("role", ["cashier", "waiter"])
async def test_floor_roles_can_work_the_kitchen_board(client, auth_headers, role):
    """Cashier and waiter WORK the board.

    The frontend has always offered /kds to them; the API used to allow only
    manager and kitchen, so those two roles got a screen that loaded and then
    403'd on every call.
    """
    head = await _staff_headers(
        client, auth_headers, name=f"Floor {role}", pin="8471" if role == "cashier" else "7263",
        role=role,
    )

    stations = await client.get("/api/v1/kds/stations", headers=head)
    assert stations.status_code == 200, stations.text

    for path in (
        "/api/v1/kds/ready-for-pickup",
        "/api/v1/kds/ready-alerts",
        "/api/v1/kds/category-defaults",
        "/api/v1/kds/printer-status",
    ):
        resp = await client.get(path, headers=head)
        assert resp.status_code == 200, (role, path, resp.status_code, resp.text)


@pytest.mark.anyio
@pytest.mark.parametrize("role", ["cashier", "waiter"])
async def test_floor_roles_cannot_reconfigure_the_kitchen(client, auth_headers, role):
    """Working the board is not the same as owning its layout.

    Creating or deleting a kitchen, or rewiring which category prints where, is
    setup done once — a mis-tap sends every dish in a category to the wrong
    pass, and it would be invisible until food stopped arriving.
    """
    head = await _staff_headers(
        client, auth_headers, name=f"Cfg {role}", pin="5926" if role == "cashier" else "4708",
        role=role,
    )

    created = await client.post(
        "/api/v1/kds/stations", json={"name": "Rogue"}, headers=head
    )
    assert created.status_code == 403, (role, created.text)

    seeded = await client.post("/api/v1/kds/stations/seed-defaults", headers=head)
    assert seeded.status_code == 403, (role, seeded.text)

    # And a manager really can do what the floor role just could not, so the
    # 403s above mean "not your job", not "endpoint broken for everyone".
    ok = await client.post(
        "/api/v1/kds/stations", json={"name": "Grill"}, headers=auth_headers
    )
    assert ok.status_code == 201, ok.text
    gone = await client.delete(
        f"/api/v1/kds/stations/{ok.json()['id']}", headers=head
    )
    assert gone.status_code == 403, (role, gone.text)
