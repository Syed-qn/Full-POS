"""Smoke test for the transcript replay driver.

Uses the same db_session / restaurant fixtures as the conversation tests.
The menu seed mirrors _seed_menu() from tests/conversation/test_engine_full_ai.py.
"""
from decimal import Decimal

import pytest

from tests.harness.replay import drive_turns


async def _seed_menu(db_session, restaurant_id):
    from app.menu.models import Dish, Menu

    menu = Menu(
        restaurant_id=restaurant_id, version=1, status="active", source_files=[]
    )
    db_session.add(menu)
    await db_session.flush()
    db_session.add(
        Dish(
            menu_id=menu.id,
            restaurant_id=restaurant_id,
            dish_number=110,
            name="Chicken Biryani",
            price_aed=Decimal("22.00"),
            category="Rice",
            is_available=True,
            name_normalized="chicken biryani",
        )
    )
    await db_session.commit()


@pytest.mark.asyncio
async def test_drive_single_text_turn(db_session, restaurant):
    """drive_turns: one text turn must produce ≥1 outbound and a cart with biryani."""
    await _seed_menu(db_session, restaurant.id)

    res = await drive_turns(
        db_session,
        restaurant_id=restaurant.id,
        phone="+971500000001",
        turns=[{"type": "text", "text": "one chicken biryani"}],
    )

    assert len(res.turns) == 1
    # at least one outbound was produced (no silent drop)
    assert res.turns[0].outbounds, "every inbound must get a reply"
    # cart reflects the order (dish name comes from the seeded menu)
    names = [r["dish_name"].lower() for r in res.final_cart()]
    assert any("biryani" in n for n in names)
