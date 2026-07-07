# alembic/env.py
import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import get_settings
from app.db import Base
import app.audit.models  # noqa: F401  (register tables; later modules append imports)
import app.identity.models  # noqa: F401
import app.menu.models  # noqa: F401
import app.menu.modifiers  # noqa: F401
import app.menu.combos  # noqa: F401
import app.webhook.models   # noqa: F401
import app.outbox.models    # noqa: F401
import app.conversation.models  # noqa: F401
import app.ordering.models  # noqa: F401
import app.dispatch.models  # noqa: F401
import app.sla.models  # noqa: F401
import app.coupons.models  # noqa: F401
import app.cod.models  # noqa: F401
import app.marketing.models  # noqa: F401
import app.predictions.models  # noqa: F401
import app.partner.models  # noqa: F401
import app.wallet.models  # noqa: F401
import app.tickets.models  # noqa: F401
import app.okf.models  # noqa: F401
import app.catalog.models  # noqa: F401
import app.idempotency.models  # noqa: F401
import app.kds.models  # noqa: F401
import app.cashdrawer.models  # noqa: F401
import app.tables.models  # noqa: F401
import app.inventory.models  # noqa: F401
import app.staff.models  # noqa: F401
import app.staff.scheduling  # noqa: F401
import app.organizations.models  # noqa: F401
import app.payments.models  # noqa: F401

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def include_object(object, name, type_, reflected, compare_to):
    """Ignore tables that exist in the DB but not in our models.

    The postgis/postgis image pre-creates PostGIS + Tiger geocoder tables
    (spatial_ref_sys, state, edges, ...). Without this filter, autogenerate
    emits drop_table for every one of them.
    """
    if type_ == "table" and reflected and compare_to is None:
        return False
    # Same for raw-SQL indexes created in migrations but absent from models
    # (e.g. GIN trigram ix_dishes_name_normalized_trgm) — don't drop them.
    if type_ == "index" and reflected and compare_to is None:
        return False
    return True


def do_run_migrations(connection):
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations():
    engine = create_async_engine(get_settings().database_url)
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await engine.dispose()


def run_migrations_online():
    asyncio.run(run_async_migrations())


run_migrations_online()
