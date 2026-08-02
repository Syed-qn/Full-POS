"""The audit log shows WHICH values changed and WHO changed them.

`before` and `after` were recorded on every row from the start and never sent to
any screen, so the log could say "manager changed dish 12" but not "from 26.00 to
18.00" — the half worth reading stayed in the database. And `actor` is a ROLE, so
every row read "Manager" on a floor that has several of them.
"""

import pytest

from app.audit.service import diff_fields


def test_only_changed_fields_appear():
    changes = diff_fields(
        {"price_aed": "26.00", "name": "Burger", "is_available": True},
        {"price_aed": "18.00", "name": "Burger", "is_available": False},
    )
    fields = {c["field"] for c in changes}
    assert fields == {"price_aed", "is_available"}
    price = next(c for c in changes if c["field"] == "price_aed")
    assert price["from"] == "26.00"
    assert price["to"] == "18.00"


def test_booleans_read_as_yes_and_no():
    changes = diff_fields({"is_available": True}, {"is_available": False})
    assert changes[0]["from"] == "yes"
    assert changes[0]["to"] == "no"


def test_a_missing_value_reads_as_empty():
    changes = diff_fields({"reason": None}, {"reason": "Wrong order"})
    assert changes[0]["from"] == "empty"
    assert changes[0]["to"] == "Wrong order"


def test_noise_and_secrets_are_never_shown():
    changes = diff_fields(
        {"updated_at": "1", "pin_hash": "aaa", "asp_api_key": "k1", "name": "A"},
        {"updated_at": "2", "pin_hash": "bbb", "asp_api_key": "k2", "name": "B"},
    )
    assert [c["field"] for c in changes] == ["name"]


def test_creates_and_deletes_are_not_reported_as_every_field_changing():
    # "all of them" is not a diff, and a create has nothing to compare against.
    assert diff_fields(None, {"name": "A", "price_aed": "10.00"}) == []
    assert diff_fields({"name": "A"}, None) == []


def test_long_values_are_truncated_for_a_table_cell():
    changes = diff_fields({"note": "x"}, {"note": "y" * 200})
    assert len(changes[0]["to"]) <= 40


def test_collections_are_summarised_not_dumped():
    changes = diff_fields({"items": [1, 2]}, {"items": [1, 2, 3]})
    assert changes[0]["to"] == "3 items"


@pytest.mark.anyio
async def test_endpoint_returns_changes_and_the_person(client, auth_headers, db_session):
    from sqlalchemy import select

    from app.audit.service import record_audit
    from app.identity.models import Restaurant
    from app.staff.models import StaffMember

    restaurant = await db_session.scalar(
        select(Restaurant).where(Restaurant.email == "owner@biryani.ae")
    )
    staff = StaffMember(
        restaurant_id=restaurant.id,
        name="Asif",
        role="manager",
        pin_hash="x",
        is_active=True,
    )
    db_session.add(staff)
    await db_session.flush()
    await record_audit(
        db_session,
        actor="manager",
        actor_staff_id=staff.id,
        restaurant_id=restaurant.id,
        entity="dish",
        entity_id="12",
        action="price_changed",
        before={"price_aed": "26.00"},
        after={"price_aed": "18.00"},
    )
    await db_session.commit()

    resp = await client.get("/api/v1/audit-log?limit=50", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    row = next(r for r in resp.json()["rows"] if r["entity_id"] == "12")

    assert row["actor_name"] == "Asif"
    assert row["actor"] == "manager"
    assert row["changes"] == [{"field": "price_aed", "from": "26.00", "to": "18.00"}]


@pytest.mark.anyio
async def test_a_system_write_has_no_person_rather_than_a_made_up_one(
    client, auth_headers, db_session
):
    from sqlalchemy import select

    from app.audit.service import record_audit
    from app.identity.models import Restaurant

    restaurant = await db_session.scalar(
        select(Restaurant).where(Restaurant.email == "owner@biryani.ae")
    )
    await record_audit(
        db_session,
        actor="system",
        restaurant_id=restaurant.id,
        entity="backup_job",
        entity_id="999",
        action="backup_completed",
    )
    await db_session.commit()

    resp = await client.get("/api/v1/audit-log?limit=50", headers=auth_headers)
    row = next(r for r in resp.json()["rows"] if r["entity_id"] == "999")
    assert row["actor_name"] is None
    assert row["changes"] == []
