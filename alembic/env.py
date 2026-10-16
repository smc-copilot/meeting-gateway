"""Only the migration process changes the schema; API/Worker never create tables."""
import asyncio
import os
from logging.config import fileConfig
from alembic import context
from sqlalchemy import create_engine, pool
from sqlalchemy.ext.asyncio import create_async_engine
import app.models  # Register every mapped class.
from app.models.base import Base, UTCDateTime

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)
url = os.getenv('MIGRATION_DATABASE_URL') or os.getenv('DATABASE_URL')
if not url:
    from dotenv import dotenv_values
    url = dotenv_values('.env').get('DATABASE_URL')
if not url:
    raise RuntimeError('DATABASE_URL is required; migrations never guess a target database')

def render_item(kind, value, autogen_context):
    if kind == 'type' and isinstance(value, UTCDateTime):
        return 'sa.DateTime(timezone=True)'
    return False

def migrate(connection):
    context.configure(connection=connection, target_metadata=Base.metadata, compare_type=True,
                      render_item=render_item)
    with context.begin_transaction():
        context.run_migrations()

async def async_migrate():
    engine = create_async_engine(url, poolclass=pool.NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(migrate)
    await engine.dispose()

if context.is_offline_mode():
    context.configure(url=url, target_metadata=Base.metadata, literal_binds=True,
                      dialect_opts={'paramstyle':'named'}, render_item=render_item)
    with context.begin_transaction():
        context.run_migrations()
elif '+asyncpg:' in url:
    asyncio.run(async_migrate())
else:
    # Used for offline migration regression tests only, not a production SQLite runtime.
    with create_engine(url, poolclass=pool.NullPool).connect() as connection:
        migrate(connection)
