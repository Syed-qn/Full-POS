"""One party across several tables, ONE invoice — and every table frees together.

Twelve guests do not fit on a four-top, so they take three. That is not the same
operation as the existing order merge: ``merge_orders`` cancels the second bill
and frees the second table immediately, which is right when guests physically
MOVE to one table and wrong when they push tables together and are still sitting
at both. Joining links the tables instead:

* every joined table stays OCCUPIED while the party eats,
* a round rung up at any of them lands on the ONE invoice,
* settling that invoice frees the WHOLE group.
"""

from decimal import Decimal

import pytest
from sqlalchemy import select


async def _restaurant(db_session):
    from app.identity.models import Restaurant

    return await db_session.scalar(
        select(Restaurant).where(Restaurant.email == "owner@biryani.ae")
    )


async def _floor(db_session, *, labels: list[str], dish_number: int, dish_name: str):
    """A row of free tables plus one available dish on the active menu."""
    from app.menu.models import Dish, Menu
    from app.tables.models import DiningTable

    restaurant = await _restaurant(db_session)
    tables = []
    for i, label in enumerate(labels):
        t = DiningTable(
            restaurant_id=restaurant.id,
            label=label,
            seats=4,
            status="available",
            pos_x=float(i),
            pos_y=0.0,
        )
        db_session.add(t)
        tables.append(t)
    menu = await db_session.scalar(
        select(Menu).where(Menu.restaurant_id == restaurant.id, Menu.status == "active")
    )
    if menu is None:
        menu = Menu(
            restaurant_id=restaurant.id, version=1, status="active", source_files=[]
        )
        db_session.add(menu)
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
    return restaurant, tables, dish


async def _ring(client, headers, *, table_id, dish_id, phone, qty=1):
    resp = await client.post(
        "/api/v1/orders/pos",
        json={
            "order_type": "dine_in",
            "table_id": table_id,
            "customer_phone": phone,
            "items": [{"dish_id": dish_id, "qty": qty}],
        },
        headers=headers,
    )
    assert resp.status_code in (200, 201), resp.text
    return resp.json()


async def _rows(client, headers):
    listing = await client.get("/api/v1/tables", headers=headers)
    assert listing.status_code == 200, listing.text
    return {r["label"]: r for r in listing.json()}


@pytest.mark.anyio
async def test_joined_tables_all_read_occupied(client, auth_headers, db_session):
    """The core of it: nobody is offered a table a party is sitting at."""
    _r, tables, dish = await _floor(
        db_session, labels=["J1", "J2", "J3"], dish_number=911, dish_name="JoinKebab"
    )
    primary, *rest = tables

    await _ring(
        client, auth_headers, table_id=primary.id, dish_id=dish.id, phone="+971500000901"
    )
    resp = await client.post(
        f"/api/v1/tables/{primary.id}/join",
        json={"table_ids": [t.id for t in rest]},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text

    rows = await _rows(client, auth_headers)
    # Every table of the group is occupied — not just the one holding the bill.
    for label in ("J1", "J2", "J3"):
        assert rows[label]["status"] in ("ordered", "seated"), label
    # The secondaries point at the invoice, and carry none of their own.
    assert rows["J2"]["merged_into_label"] == "J1"
    assert rows["J2"]["bill_count"] == 0
    assert rows["J2"]["order_id"] is None
    # The primary says what is joined to it, so the floor can draw the group.
    assert rows["J1"]["joined_labels"] == ["J2", "J3"]


@pytest.mark.anyio
async def test_a_round_rung_at_any_joined_table_lands_on_the_one_invoice(
    client, auth_headers, db_session
):
    """SINGLE INVOICE — the whole reason for joining.

    Without resolving the table, a waiter standing at J5 would open a second bill
    and a party of twelve would end up with one bill per table.
    """
    _r, tables, dish = await _floor(
        db_session, labels=["J4", "J5"], dish_number=912, dish_name="OneBillKebab"
    )
    primary, secondary = tables

    first = await _ring(
        client, auth_headers, table_id=primary.id, dish_id=dish.id, phone="+971500000902"
    )
    await client.post(
        f"/api/v1/tables/{primary.id}/join",
        json={"table_ids": [secondary.id]},
        headers=auth_headers,
    )

    # Rung up at the SECONDARY table.
    same = await _ring(
        client, auth_headers, table_id=secondary.id, dish_id=dish.id, phone="+971500000903"
    )
    assert same["id"] == first["id"], "a joined table must not open a second invoice"
    assert Decimal(str(same["total_aed"])) == Decimal("40.00")

    rows = await _rows(client, auth_headers)
    assert rows["J4"]["bill_count"] == 1
    assert rows["J5"]["bill_count"] == 0


@pytest.mark.anyio
async def test_joining_a_table_that_already_has_a_bill_folds_it_in(
    client, auth_headers, db_session
):
    """Two tables that each started their own tab, then decided to sit together."""
    _r, tables, dish = await _floor(
        db_session, labels=["J6", "J7"], dish_number=913, dish_name="FoldKebab"
    )
    primary, secondary = tables

    await _ring(
        client, auth_headers, table_id=primary.id, dish_id=dish.id, phone="+971500000904"
    )
    await _ring(
        client, auth_headers, table_id=secondary.id, dish_id=dish.id, phone="+971500000905"
    )

    resp = await client.post(
        f"/api/v1/tables/{primary.id}/join",
        json={"table_ids": [secondary.id]},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text

    rows = await _rows(client, auth_headers)
    # One invoice carrying both tables' food.
    assert rows["J6"]["bill_count"] == 1
    assert Decimal(rows["J6"]["order_total_aed"]) == Decimal("40.00")
    assert rows["J7"]["bill_count"] == 0
    assert rows["J7"]["status"] in ("ordered", "seated")


@pytest.mark.anyio
async def test_settling_the_one_invoice_frees_every_joined_table(
    client, auth_headers, db_session
):
    """The rule that makes the whole thing safe to use during service."""
    from app.ordering.service import settle_on_premise_if_paid
    from app.payments.models import PaymentTransaction
    from app.tables.models import DiningTable

    restaurant, tables, dish = await _floor(
        db_session, labels=["J8", "J9"], dish_number=914, dish_name="PayGroupKebab"
    )
    primary, secondary = tables

    order = await _ring(
        client, auth_headers, table_id=primary.id, dish_id=dish.id, phone="+971500000906"
    )
    await client.post(
        f"/api/v1/tables/{primary.id}/join",
        json={"table_ids": [secondary.id]},
        headers=auth_headers,
    )

    db_session.add(
        PaymentTransaction(
            restaurant_id=restaurant.id,
            order_id=order["id"],
            tender_type="cash",
            amount_aed=Decimal("20.00"),
            status="succeeded",
        )
    )
    await db_session.flush()
    await settle_on_premise_if_paid(
        db_session, order_id=order["id"], restaurant_id=restaurant.id
    )
    await db_session.commit()

    rows = await _rows(client, auth_headers)
    assert rows["J8"]["status"] == "available"
    assert rows["J9"]["status"] == "available", "the group frees together, not one table"
    # The link ends with the sitting: a stale one would put the NEXT party's food
    # on a stranger's invoice.
    fresh = await db_session.scalar(
        select(DiningTable).where(DiningTable.id == secondary.id)
    )
    await db_session.refresh(fresh)
    assert fresh.merged_into_table_id is None


@pytest.mark.anyio
async def test_unjoin_gives_a_table_back(client, auth_headers, db_session):
    _r, tables, dish = await _floor(
        db_session, labels=["JA", "JB"], dish_number=915, dish_name="UnjoinKebab"
    )
    primary, secondary = tables

    await _ring(
        client, auth_headers, table_id=primary.id, dish_id=dish.id, phone="+971500000907"
    )
    await client.post(
        f"/api/v1/tables/{primary.id}/join",
        json={"table_ids": [secondary.id]},
        headers=auth_headers,
    )
    resp = await client.post(
        f"/api/v1/tables/{secondary.id}/unjoin", headers=auth_headers
    )
    assert resp.status_code == 200, resp.text

    rows = await _rows(client, auth_headers)
    assert rows["JB"]["status"] == "available"
    assert rows["JB"]["merged_into_table_id"] is None
    assert rows["JA"]["joined_labels"] == []


@pytest.mark.anyio
async def test_join_refuses_to_build_a_chain(client, auth_headers, db_session):
    """One level only. A chain would make "which table holds the invoice" a
    question with more than one answer, and every reader would have to walk it."""
    _r, tables, dish = await _floor(
        db_session, labels=["JC", "JD", "JE"], dish_number=916, dish_name="ChainKebab"
    )
    a, b, c = tables

    await client.post(
        f"/api/v1/tables/{a.id}/join", json={"table_ids": [b.id]}, headers=auth_headers
    )
    # B is already a secondary — joining C to B must not stack a second level.
    resp = await client.post(
        f"/api/v1/tables/{b.id}/join", json={"table_ids": [c.id]}, headers=auth_headers
    )
    assert resp.status_code == 200, resp.text
    rows = await _rows(client, auth_headers)
    # Resolved through to A rather than refused: tapping any table of a group and
    # asking to add another is a reasonable thing for a waiter to do.
    assert rows["JE"]["merged_into_label"] == "JC"
    assert rows["JC"]["joined_labels"] == ["JD", "JE"]


@pytest.mark.anyio
async def test_joining_a_split_table_refuses_to_guess_which_bill(
    client, auth_headers, db_session
):
    """"Two bills on T01, join T02 — which bill?" has no safe default.

    T01 holds two parties. Folding T02's guests into whichever bill happens to be
    oldest would put their food on strangers' money. So the join is REFUSED until
    the caller names the bill.
    """
    _r, tables, dish = await _floor(
        db_session, labels=["JG", "JH"], dish_number=918, dish_name="AmbiguousKebab"
    )
    primary, secondary = tables

    await _ring(
        client, auth_headers, table_id=primary.id, dish_id=dish.id, phone="+971500000908"
    )
    # A second, separate bill on the SAME table (the split-bill feature).
    resp = await client.post(
        "/api/v1/orders/pos",
        json={
            "order_type": "dine_in",
            "table_id": primary.id,
            "customer_phone": "+971500000909",
            "items": [{"dish_id": dish.id, "qty": 1}],
            "force_new_bill": True,
        },
        headers=auth_headers,
    )
    assert resp.status_code in (200, 201), resp.text

    ambiguous = await client.post(
        f"/api/v1/tables/{primary.id}/join",
        json={"table_ids": [secondary.id]},
        headers=auth_headers,
    )
    assert ambiguous.status_code == 409
    assert "which one" in ambiguous.json()["detail"]


@pytest.mark.anyio
async def test_the_chosen_bill_receives_the_join_and_every_later_round(
    client, auth_headers, db_session
):
    """Pick Bill 1 and the WHOLE group lives on Bill 1 — merged food and later
    rounds alike.

    This is the bug the user's question exposed: the join folded into the OLDEST
    bill while order creation appends to the NEWEST addable tab, so a split table
    would have shown merged food on one bill and new food on the other.
    """
    _r, tables, dish = await _floor(
        db_session, labels=["JI", "JJ"], dish_number=919, dish_name="ChosenKebab"
    )
    primary, secondary = tables

    bill1 = await _ring(
        client, auth_headers, table_id=primary.id, dish_id=dish.id, phone="+971500000910"
    )
    resp = await client.post(
        "/api/v1/orders/pos",
        json={
            "order_type": "dine_in",
            "table_id": primary.id,
            "customer_phone": "+971500000911",
            "items": [{"dish_id": dish.id, "qty": 1}],
            "force_new_bill": True,
        },
        headers=auth_headers,
    )
    bill2 = resp.json()

    joined = await client.post(
        f"/api/v1/tables/{primary.id}/join",
        json={"table_ids": [secondary.id], "into_order_id": bill1["id"]},
        headers=auth_headers,
    )
    assert joined.status_code == 200, joined.text

    # A round rung up at the JOINED table must land on Bill 1, not on Bill 2 and
    # not on a third bill of its own.
    later = await _ring(
        client, auth_headers, table_id=secondary.id, dish_id=dish.id, phone="+971500000912"
    )
    assert later["id"] == bill1["id"]
    assert Decimal(str(later["total_aed"])) == Decimal("40.00")

    rows = await _rows(client, auth_headers)
    # Bill 2 — the other party at that table — is untouched, still its own bill.
    assert rows["JI"]["bill_count"] == 2
    totals = {b["order_id"]: b["total_aed"] for b in rows["JI"]["bills"]}
    assert Decimal(totals[bill1["id"]]) == Decimal("40.00")
    assert Decimal(totals[bill2["id"]]) == Decimal("20.00")


@pytest.mark.anyio
async def test_join_rejects_a_bill_that_is_not_on_the_table(
    client, auth_headers, db_session
):
    _r, tables, dish = await _floor(
        db_session, labels=["JK", "JL"], dish_number=920, dish_name="StrayKebab"
    )
    primary, secondary = tables
    await _ring(
        client, auth_headers, table_id=primary.id, dish_id=dish.id, phone="+971500000913"
    )
    resp = await client.post(
        f"/api/v1/tables/{primary.id}/join",
        json={"table_ids": [secondary.id], "into_order_id": 99999999},
        headers=auth_headers,
    )
    assert resp.status_code == 409
    assert "not an open bill" in resp.json()["detail"]


async def _split_bill(client, headers, *, table_id, dish_id, phone):
    resp = await client.post(
        "/api/v1/orders/pos",
        json={
            "order_type": "dine_in",
            "table_id": table_id,
            "customer_phone": phone,
            "items": [{"dish_id": dish_id, "qty": 1}],
            "force_new_bill": True,
        },
        headers=headers,
    )
    assert resp.status_code in (200, 201), resp.text
    return resp.json()


@pytest.mark.anyio
async def test_joining_a_table_with_two_parties_refuses_to_take_both(
    client, auth_headers, db_session
):
    """The user's case: the JOINING table has 2 bills.

    Two bills means two PARTIES sitting at that table, so "join the table" is the
    wrong unit — only one of them is moving in with the group. Folding both in
    would merge strangers' money onto a single invoice, silently.
    """
    _r, tables, dish = await _floor(
        db_session, labels=["JM", "JN"], dish_number=921, dish_name="TwoPartyKebab"
    )
    primary, secondary = tables

    await _ring(
        client, auth_headers, table_id=primary.id, dish_id=dish.id, phone="+971500000914"
    )
    await _ring(
        client, auth_headers, table_id=secondary.id, dish_id=dish.id, phone="+971500000915"
    )
    await _split_bill(
        client, auth_headers, table_id=secondary.id, dish_id=dish.id, phone="+971500000916"
    )

    resp = await client.post(
        f"/api/v1/tables/{primary.id}/join",
        json={"table_ids": [secondary.id]},
        headers=auth_headers,
    )
    assert resp.status_code == 409, resp.text
    assert "which one is joining" in resp.json()["detail"]


@pytest.mark.anyio
async def test_only_the_named_party_joins_and_the_table_stays_its_own(
    client, auth_headers, db_session
):
    """Name the bill and ONLY that party moves onto the group invoice.

    The table is deliberately NOT linked: the other party is still sitting on it,
    so it keeps its own bill and its own identity on the floor.
    """
    _r, tables, dish = await _floor(
        db_session, labels=["JO", "JP"], dish_number=922, dish_name="NamedPartyKebab"
    )
    primary, secondary = tables

    group_bill = await _ring(
        client, auth_headers, table_id=primary.id, dish_id=dish.id, phone="+971500000917"
    )
    joining = await _ring(
        client, auth_headers, table_id=secondary.id, dish_id=dish.id, phone="+971500000918"
    )
    staying = await _split_bill(
        client, auth_headers, table_id=secondary.id, dish_id=dish.id, phone="+971500000919"
    )

    resp = await client.post(
        f"/api/v1/tables/{primary.id}/join",
        json={"table_ids": [secondary.id], "from_order_ids": [joining["id"]]},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text

    rows = await _rows(client, auth_headers)
    # The joining party's food is on the group invoice.
    assert rows["JO"]["bill_count"] == 1
    assert Decimal(rows["JO"]["order_total_aed"]) == Decimal("40.00")
    assert rows["JO"]["bills"][0]["order_id"] == group_bill["id"]
    # The table is NOT swallowed: the other party keeps its bill there.
    assert rows["JP"]["merged_into_table_id"] is None
    assert rows["JP"]["bill_count"] == 1
    assert rows["JP"]["bills"][0]["order_id"] == staying["id"]
    assert Decimal(rows["JP"]["bills"][0]["total_aed"]) == Decimal("20.00")


@pytest.mark.anyio
async def test_join_needs_a_second_table(client, auth_headers, db_session):
    _r, tables, _dish = await _floor(
        db_session, labels=["JF"], dish_number=917, dish_name="SoloKebab"
    )
    resp = await client.post(
        f"/api/v1/tables/{tables[0].id}/join",
        json={"table_ids": [tables[0].id]},
        headers=auth_headers,
    )
    assert resp.status_code == 409, resp.text
