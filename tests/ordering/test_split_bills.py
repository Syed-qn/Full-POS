"""Several separate bills on ONE table, and the table frees only on the last.

Two parties can share a table: one is eating, a second sits down, and each pays
for their own food. The data model always allowed it — ``Order.table_id`` has no
uniqueness constraint — but two places actively prevented it:

* ``create_pos_order`` MERGED a second dine-in order into the table's open tab
  ("Prevent split tabs"), on purpose, to stop a stale POS screen opening a
  duplicate order the floor could not surface.
* ``settle_on_premise_if_paid`` freed the table on ANY settle, so the first
  party paying made the second party's open bill vanish from the floor.

These tests pin the split as an EXPLICIT act (``force_new_bill``) so the
accidental-duplicate guard keeps working by default, and pin the table to stay
occupied until the last bill on it is settled.
"""

from decimal import Decimal

import pytest
from sqlalchemy import select


async def _restaurant(db_session):
    from app.identity.models import Restaurant

    return await db_session.scalar(
        select(Restaurant).where(Restaurant.email == "owner@biryani.ae")
    )


async def _table_and_dish(db_session, *, label: str, dish_number: int, dish_name: str):
    """A free table plus one available dish on the restaurant's active menu."""
    from app.menu.models import Dish, Menu
    from app.tables.models import DiningTable

    restaurant = await _restaurant(db_session)
    table = DiningTable(
        restaurant_id=restaurant.id,
        label=label,
        seats=4,
        status="available",
        pos_x=1.0,
        pos_y=1.0,
    )
    menu = await db_session.scalar(
        select(Menu).where(
            Menu.restaurant_id == restaurant.id, Menu.status == "active"
        )
    )
    if menu is None:
        menu = Menu(
            restaurant_id=restaurant.id, version=1, status="active", source_files=[]
        )
        db_session.add(menu)
    db_session.add(table)
    await db_session.flush()
    dish = Dish(
        menu_id=menu.id,
        restaurant_id=restaurant.id,
        dish_number=dish_number,
        name=dish_name,
        price_aed=Decimal("20.00"),
        category="Grills",
        is_available=True,
        name_normalized=dish_name.lower(),
    )
    db_session.add(dish)
    await db_session.commit()
    return restaurant, table, dish


async def _open_bill(client, headers, *, table_id, dish_id, phone, split=False, label=None):
    body = {
        "order_type": "dine_in",
        "table_id": table_id,
        "customer_phone": phone,
        "items": [{"dish_id": dish_id, "qty": 1}],
    }
    if split:
        body["force_new_bill"] = True
    if label is not None:
        body["guest_label"] = label
    resp = await client.post("/api/v1/orders/pos", json=body, headers=headers)
    assert resp.status_code in (200, 201), resp.text
    return resp.json()


@pytest.mark.anyio
async def test_split_opens_a_second_bill_on_the_same_table(
    client, auth_headers, db_session
):
    """The whole point: two open orders, one table, separate totals."""
    _r, table, dish = await _table_and_dish(
        db_session, label="S1", dish_number=901, dish_name="SplitKebab"
    )

    first = await _open_bill(
        client, auth_headers, table_id=table.id, dish_id=dish.id, phone="+971500000801"
    )
    second = await _open_bill(
        client,
        auth_headers,
        table_id=table.id,
        dish_id=dish.id,
        phone="+971500000802",
        split=True,
    )

    assert second["id"] != first["id"], "force_new_bill must not merge into the open tab"
    # Each bill carries only its own food — the second is not a copy of the first.
    assert Decimal(str(second["total_aed"])) == Decimal("20.00")
    assert Decimal(str(first["total_aed"])) == Decimal("20.00")


@pytest.mark.anyio
async def test_a_plain_second_round_still_merges(client, auth_headers, db_session):
    """Regression on the guard this feature makes opt-in.

    WITHOUT force_new_bill, a second create on an occupied table must still fold
    into the open tab. That guard exists because a POS screen holds a stale table
    snapshot: if the waiter opened the table and the cashier then rang a round,
    an accidental second order would hide one party's bill. Splitting has to be
    something a human ASKED for, never a race.
    """
    _r, table, dish = await _table_and_dish(
        db_session, label="S2", dish_number=902, dish_name="MergeKebab"
    )

    first = await _open_bill(
        client, auth_headers, table_id=table.id, dish_id=dish.id, phone="+971500000803"
    )
    same = await _open_bill(
        client, auth_headers, table_id=table.id, dish_id=dish.id, phone="+971500000804"
    )

    assert same["id"] == first["id"]
    assert Decimal(str(same["total_aed"])) == Decimal("40.00")


@pytest.mark.anyio
async def test_floor_lists_every_open_bill_on_the_table(
    client, auth_headers, db_session
):
    """The floor must show BOTH bills.

    The listing used to keep only the newest open order per table (setdefault on
    a created_at-desc scan), so a split table showed one bill and silently hid
    the other — the cashier would collect once and think the table was done.
    """
    _r, table, dish = await _table_and_dish(
        db_session, label="S3", dish_number=903, dish_name="ListKebab"
    )

    first = await _open_bill(
        client, auth_headers, table_id=table.id, dish_id=dish.id, phone="+971500000805"
    )
    second = await _open_bill(
        client,
        auth_headers,
        table_id=table.id,
        dish_id=dish.id,
        phone="+971500000806",
        split=True,
        label="Guest 2",
    )

    listing = await client.get("/api/v1/tables", headers=auth_headers)
    row = next(t for t in listing.json() if t["id"] == table.id)

    assert row["bill_count"] == 2
    ids = {b["order_id"] for b in row["bills"]}
    assert ids == {first["id"], second["id"]}
    # OLDEST FIRST. The floor numbers bills by position, so index 0 has to be the
    # party that sat down first or "Bill 1" names the newest arrival. The scan that
    # builds this runs newest-first (order_id needs the newest), so the order here
    # is a deliberate flip and worth pinning.
    assert [b["order_id"] for b in row["bills"]] == [first["id"], second["id"]]
    # order_id stays the newest single bill so every existing reader (KDS, Live
    # Ops, the e2e specs) keeps working unchanged.
    assert row["order_id"] in ids
    labels = {b["guest_label"] for b in row["bills"]}
    assert "Guest 2" in labels, "a split bill must be tellable apart from the first"


@pytest.mark.anyio
async def test_settling_one_bill_leaves_the_table_occupied(
    client, auth_headers, db_session
):
    """The rule the user asked for, and the one thing that was actually broken."""
    from app.ordering.service import settle_on_premise_if_paid
    from app.payments.models import PaymentTransaction

    restaurant, table, dish = await _table_and_dish(
        db_session, label="S4", dish_number=904, dish_name="PayKebab"
    )

    first = await _open_bill(
        client, auth_headers, table_id=table.id, dish_id=dish.id, phone="+971500000807"
    )
    second = await _open_bill(
        client,
        auth_headers,
        table_id=table.id,
        dish_id=dish.id,
        phone="+971500000808",
        split=True,
    )

    db_session.add(
        PaymentTransaction(
            restaurant_id=restaurant.id,
            order_id=first["id"],
            tender_type="cash",
            amount_aed=Decimal("20.00"),
            status="succeeded",
        )
    )
    await db_session.flush()
    await settle_on_premise_if_paid(
        db_session, order_id=first["id"], restaurant_id=restaurant.id
    )
    await db_session.commit()

    await db_session.refresh(table)
    assert table.status != "available", "the second party is still eating"

    listing = await client.get("/api/v1/tables", headers=auth_headers)
    row = next(t for t in listing.json() if t["id"] == table.id)
    assert row["status"] == "ordered"
    assert row["bill_count"] == 1
    assert row["bills"][0]["order_id"] == second["id"]


@pytest.mark.anyio
async def test_settling_the_last_bill_frees_the_table(
    client, auth_headers, db_session
):
    from app.ordering.service import settle_on_premise_if_paid
    from app.payments.models import PaymentTransaction

    restaurant, table, dish = await _table_and_dish(
        db_session, label="S5", dish_number=905, dish_name="LastKebab"
    )

    first = await _open_bill(
        client, auth_headers, table_id=table.id, dish_id=dish.id, phone="+971500000809"
    )
    second = await _open_bill(
        client,
        auth_headers,
        table_id=table.id,
        dish_id=dish.id,
        phone="+971500000810",
        split=True,
    )

    for oid in (first["id"], second["id"]):
        db_session.add(
            PaymentTransaction(
                restaurant_id=restaurant.id,
                order_id=oid,
                tender_type="cash",
                amount_aed=Decimal("20.00"),
                status="succeeded",
            )
        )
        await db_session.flush()
        await settle_on_premise_if_paid(
            db_session, order_id=oid, restaurant_id=restaurant.id
        )
    await db_session.commit()

    await db_session.refresh(table)
    assert table.status == "available"

    listing = await client.get("/api/v1/tables", headers=auth_headers)
    row = next(t for t in listing.json() if t["id"] == table.id)
    assert row["status"] == "available"
    assert row["bill_count"] == 0
    assert row["bills"] == []


@pytest.mark.anyio
async def test_a_split_bill_does_not_reset_the_table_status(
    client, auth_headers, db_session
):
    """Opening a second bill must not rewrite the table.

    Order creation clears "needs_bill" to "ordered" because a NEW sitting means
    new guests. On a split that reasoning does not hold: the first party may
    already have asked for their bill, and a second party sitting down must not
    cancel that request out from under the cashier.
    """
    _r, table, dish = await _table_and_dish(
        db_session, label="S6", dish_number=906, dish_name="KeepKebab"
    )

    await _open_bill(
        client, auth_headers, table_id=table.id, dish_id=dish.id, phone="+971500000811"
    )
    table.status = "needs_bill"
    await db_session.commit()

    await _open_bill(
        client,
        auth_headers,
        table_id=table.id,
        dish_id=dish.id,
        phone="+971500000812",
        split=True,
    )

    await db_session.refresh(table)
    assert table.status == "needs_bill", "a split must not clear the other party's bill request"
