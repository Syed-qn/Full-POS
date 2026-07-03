"""fold_history_into_active_menu: pull dishes from old (superseded) menus into the active
menu so the OPS list matches what's live on WhatsApp — deduped, collision-safe, idempotent."""
from decimal import Decimal

from sqlalchemy import select

from app.menu import service
from app.menu.models import Dish, Menu
from app.ordering.matching import normalize_name


async def _menu(session, restaurant, status, version):
    m = Menu(restaurant_id=restaurant.id, version=version, status=status, source_files=[])
    session.add(m)
    await session.flush()
    return m


async def _dish(session, restaurant, menu, name, number, rid=None):
    d = Dish(
        menu_id=menu.id, restaurant_id=restaurant.id, name=name,
        name_normalized=normalize_name(name), dish_number=number,
        price_aed=Decimal("10.00"), catalog_retailer_id=rid,
    )
    session.add(d)
    await session.flush()
    return d


async def test_fold_moves_unique_superseded_dishes_and_skips_dupes(db_session, restaurant):
    active = await _menu(db_session, restaurant, "active", 2)
    await _dish(db_session, restaurant, active, "Biryani", 1)
    old = await _menu(db_session, restaurant, "superseded", 1)
    await _dish(db_session, restaurant, old, "Shawarma", 1)   # unique → folds in (renumbered off 1)
    await _dish(db_session, restaurant, old, "Biryani", 5)    # dup name → left behind
    await db_session.commit()

    folded = await service.fold_history_into_active_menu(
        db_session, restaurant_id=restaurant.id
    )
    assert folded == 1

    rows = (await db_session.scalars(select(Dish).where(Dish.menu_id == active.id))).all()
    assert sorted(d.name for d in rows) == ["Biryani", "Shawarma"]
    nums = [d.dish_number for d in rows]
    assert len(nums) == len(set(nums))  # collision-safe renumber (Shawarma != Biryani's 1)


async def test_fold_ignores_unconfirmed_draft(db_session, restaurant):
    """A pending_confirmation upload the manager hasn't reviewed must NOT be folded in —
    only old superseded menus are reconciled."""
    await _menu(db_session, restaurant, "active", 2)
    draft = await _menu(db_session, restaurant, "pending_confirmation", 3)
    await _dish(db_session, restaurant, draft, "Draft Dish", 9)
    await db_session.commit()

    folded = await service.fold_history_into_active_menu(
        db_session, restaurant_id=restaurant.id
    )
    assert folded == 0


async def test_fold_is_idempotent(db_session, restaurant):
    await _menu(db_session, restaurant, "active", 2)
    old = await _menu(db_session, restaurant, "superseded", 1)
    await _dish(db_session, restaurant, old, "Fries", 3)
    await db_session.commit()

    first = await service.fold_history_into_active_menu(db_session, restaurant_id=restaurant.id)
    second = await service.fold_history_into_active_menu(db_session, restaurant_id=restaurant.id)
    assert first == 1
    assert second == 0
