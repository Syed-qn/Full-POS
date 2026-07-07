import pytest

from app.identity.models import Restaurant
from app.tables.models import DiningTable
from app.tables.service import TableNotFoundError, update_table_position


@pytest.mark.anyio
async def test_update_table_position(db_session, restaurant):
    table = DiningTable(restaurant_id=restaurant.id, label="P1", seats=2)
    db_session.add(table)
    await db_session.flush()
    await db_session.commit()

    updated = await update_table_position(
        db_session, restaurant_id=restaurant.id, table_id=table.id, pos_x=12.5, pos_y=34.0,
    )
    await db_session.commit()
    await db_session.refresh(updated)

    assert updated.pos_x == 12.5
    assert updated.pos_y == 34.0


@pytest.mark.anyio
async def test_update_table_position_rejects_other_tenant(db_session, restaurant):
    other = Restaurant(
        name="Other Restaurant",
        phone="+97141234599",
        password_hash="x",
        lat=25.2048,
        lng=55.2708,
    )
    db_session.add(other)
    await db_session.flush()

    table = DiningTable(restaurant_id=restaurant.id, label="P2", seats=2)
    db_session.add(table)
    await db_session.flush()
    await db_session.commit()

    with pytest.raises(TableNotFoundError):
        await update_table_position(
            db_session, restaurant_id=other.id, table_id=table.id, pos_x=1.0, pos_y=1.0,
        )
