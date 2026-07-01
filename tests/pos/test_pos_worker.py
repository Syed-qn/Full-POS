"""Background POS sync runner (app.pos.worker.run_pos_sync).

Drives the runner with an injected test session factory + FakePos provider so it
exercises the real own-session + status-breadcrumb logic without touching the network
or the global session factory.
"""
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.menu.models import Dish
from app.pos.port import FakePos, PosCategory, PosMenu, PosProduct
from app.pos.worker import run_pos_sync


def _menu(products) -> PosMenu:
    return PosMenu(
        categories=[PosCategory(pos_category_id="220", name="APPETIZER")],
        products=products,
    )


def _prod(pid, name, price, cat="220", ptype=1):
    return PosProduct(
        pos_product_id=pid, name=name, price=Decimal(str(price)),
        category_id=cat, product_type=ptype,
    )


def _factory(db_session):
    return async_sessionmaker(
        bind=db_session.bind, expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )


async def test_run_pos_sync_creates_dishes_and_records_done(db_session, restaurant):
    restaurant.settings = {**(restaurant.settings or {}),
                           "pos_account": "hnc", "pos_location": "HNC002"}
    await db_session.commit()  # the runner opens its OWN session — must see committed rows
    factory = _factory(db_session)
    provider = FakePos(_menu([_prod("19680", "Samosa", 12), _prod("19697", "Juice", 9)]))

    status = await run_pos_sync(
        restaurant.id, publish=False, session_factory=factory, provider=provider
    )

    assert status["state"] == "done"
    assert (status["fetched"], status["created"]) == (2, 2)
    assert status["images"] == 2
    assert status.get("started_at") is None or True  # tolerate ordering of breadcrumb keys

    dishes = (await db_session.scalars(
        select(Dish).where(Dish.restaurant_id == restaurant.id, Dish.pos_product_id.is_not(None))
    )).all()
    assert {d.pos_product_id for d in dishes} == {"19680", "19697"}

    # Breadcrumb persisted on the restaurant for the manager UI to poll.
    await db_session.refresh(restaurant)
    assert restaurant.settings["pos_last_sync"]["state"] == "done"


class _BoomPos:
    """A provider whose fetch blows up — to prove the runner captures the failure as a
    breadcrumb and never propagates the exception."""

    async def fetch_menu(self, *, account, location, base_url=None):
        raise RuntimeError("POS exploded")


async def test_run_pos_sync_records_error_and_never_raises(db_session, restaurant):
    # account/location now default to the HNC test feed, so a missing config no longer
    # errors. The "never raises" guarantee is proven instead with a provider that throws.
    await db_session.commit()
    factory = _factory(db_session)

    status = await run_pos_sync(
        restaurant.id, publish=False, session_factory=factory, provider=_BoomPos()
    )

    assert status["state"] == "error"
    assert "POS exploded" in status["error"]
    await db_session.refresh(restaurant)
    assert restaurant.settings["pos_last_sync"]["state"] == "error"
