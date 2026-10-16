"""Shared local schema primitives; no cross-service database dependencies."""
from datetime import UTC, datetime
from uuid import uuid4
from sqlalchemy import DateTime, Index, Integer, JSON, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator
from app.core.types import utcnow


def new_id() -> str:
    return str(uuid4())


class UTCDateTime(TypeDecorator):
    impl = DateTime(timezone=True)
    cache_ok = True
    def process_bind_param(self, value, dialect):
        if value is not None:
            if value.tzinfo is None:
                raise ValueError("Timezone-aware datetime required")
            return value.astimezone(UTC)
        return value
    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


JSON_TYPE = JSON().with_variant(JSONB(), "postgresql")


def active_unique(name: str, *columns):
    return Index(name, *columns, unique=True, postgresql_where=text("deleted_at IS NULL"),
                 sqlite_where=text("deleted_at IS NULL"))


class Base(DeclarativeBase):
    pass


class Record(Base):
    __abstract__ = True
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True, index=True)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    def __init__(self, **values):
        defaults = dict(id=new_id(), created_at=utcnow(), updated_at=utcnow(), deleted_at=None, version=1)
        for key, value in (defaults | values).items():
            if not hasattr(type(self), key):
                raise TypeError(f"Unknown model field: {key}")
            setattr(self, key, value)

    def soft_delete(self):
        self.deleted_at = utcnow()
        self.version += 1


class OrgRecord(Record):
    __abstract__ = True
    org_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
