# alembic/env.py
import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import get_settings
from app.db import Base
import app.audit.models  # noqa: F401  (register tables; later modules append imports)
import app.identity.models  # noqa: F401

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
