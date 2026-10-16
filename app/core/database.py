"""PostgreSQL asyncio in production; explicit synchronous SQLite facade for offline tests only.
SQLite does not claim to emulate PostgreSQL distributed locks or deployment performance.
"""
import asyncio
import hashlib
from contextlib import asynccontextmanager
from sqlalchemy import create_engine, event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from app.models import Base


class SQLiteTestSession:
    """Single-process test facade. Never selected for a production URL."""
    def __init__(self, session: Session):
        self.sync = session
    def add(self, row):
        self.sync.add(row)
    def add_all(self, rows):
        self.sync.add_all(rows)
    async def execute(self, query, params=None):
        return self.sync.execute(query, params or {})
    async def scalar(self, query, params=None):
        return self.sync.scalar(query, params or {})
    async def get(self, model, ident, **kwargs):
        return self.sync.get(model, ident, **kwargs)
    async def flush(self):
        self.sync.flush()
    async def commit(self):
        self.sync.commit()
    async def rollback(self):
        self.sync.rollback()
    async def refresh(self, row):
        self.sync.refresh(row)
    async def close(self):
        self.sync.close()
    @asynccontextmanager
    async def begin_nested(self):
        with self.sync.begin_nested():
            yield


class Database:
    def __init__(self, url: str, *, allow_sqlite=False):
        self.url = url
        self.sqlite = url.startswith("sqlite:")
        self._locks: dict[str, asyncio.Lock] = {}
        if self.sqlite:
            if not allow_sqlite:
                raise ValueError("SQLite is only available in explicitly selected development/test mode")
            options = {"connect_args": {"check_same_thread": False, "timeout": 30}}
            if url in {"sqlite://", "sqlite:///:memory:"}:
                options["poolclass"] = StaticPool
            self.engine = create_engine(url, **options)
            @event.listens_for(self.engine, "connect")
            def set_sqlite_pragmas(connection, _record):
                connection.execute("PRAGMA foreign_keys=ON")
                connection.execute("PRAGMA busy_timeout=30000")
            self.factory = sessionmaker(self.engine, expire_on_commit=False)
        else:
            if not url.startswith("postgresql+asyncpg://"):
                raise ValueError("Production driver must be postgresql+asyncpg")
            self.engine = create_async_engine(url, pool_pre_ping=True, pool_size=15, max_overflow=15)
            self.factory = async_sessionmaker(self.engine, expire_on_commit=False)

    @asynccontextmanager
    async def session(self):
        session = SQLiteTestSession(self.factory()) if self.sqlite else self.factory()
        try:
            yield session
        except BaseException:
            await session.rollback()
            raise
        finally:
            await session.close()

    @asynccontextmanager
    async def transaction(self):
        async with self.session() as session:
            yield session
            await session.commit()

    @asynccontextmanager
    async def lock(self, name: str):
        """Session advisory lock survives intermediate commits without spanning app data transactions."""
        if self.sqlite:
            lock = self._locks.setdefault(name, asyncio.Lock())
            async with lock:
                yield
            return
        number = int.from_bytes(hashlib.sha256(name.encode()).digest()[:8], "big", signed=True)
        async with self.engine.connect() as connection:
            await connection.execute(text("SELECT pg_advisory_lock(:key)"), {"key": number})
            try:
                yield
            finally:
                await connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": number})
                await connection.commit()

    async def create_schema_for_test(self):
        if not self.sqlite:
            raise ValueError("Use Alembic for PostgreSQL migrations")
        Base.metadata.create_all(self.engine)

    async def ready(self):
        async with self.session() as session:
            await session.execute(text("SELECT 1"))
        return True

    async def close(self):
        if self.sqlite:
            self.engine.dispose()
        else:
            await self.engine.dispose()
