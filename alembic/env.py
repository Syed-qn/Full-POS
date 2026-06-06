# alembic/env.py
import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import get_settings
from app.db import Base
import app.audit.models  # noqa: F401  (register tables; later modules append imports)

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def do_run_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata)
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
