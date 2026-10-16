from datetime import datetime
from sqlalchemy import Boolean, ForeignKey, Index, Integer, BigInteger, String, Text, Float
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import OrgRecord, Record, UTCDateTime, JSON_TYPE, active_unique


class EventInbox(OrgRecord):
    __tablename__ = "meeting_event_inbox"
    __table_args__ = (active_unique("uq_inbox_fingerprint", "fingerprint"),)
    application_id: Mapped[str] = mapped_column(String(36))
    event_type: Mapped[str] = mapped_column(String(64))
    fingerprint: Mapped[str] = mapped_column(String(64))
    encrypted_payload: Mapped[str | None] = mapped_column(Text)
    safe_summary: Mapped[dict] = mapped_column(JSON_TYPE, default=dict)
    state: Mapped[str] = mapped_column(String(32), default="PENDING")
    processed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_reason: Mapped[str | None] = mapped_column(String(64))


class Subscription(OrgRecord):
    __tablename__ = "meeting_event_subscriptions"
    client_id: Mapped[str] = mapped_column(String(36), ForeignKey("meeting_clients.id"))
    destination: Mapped[str] = mapped_column(String(1024))
    secret_ciphertext: Mapped[str] = mapped_column(Text)
    event_types: Mapped[list] = mapped_column(JSON_TYPE)
    member_id: Mapped[str | None] = mapped_column(String(64))
    agent_grant_id: Mapped[str | None] = mapped_column(String(36))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class EventOutbox(OrgRecord):
    __tablename__ = "meeting_event_outbox"
    __table_args__ = (active_unique("uq_outbox_delivery", "event_id", "subscription_id"),)
    event_id: Mapped[str] = mapped_column(String(36))
    subscription_id: Mapped[str] = mapped_column(String(36), ForeignKey("meeting_event_subscriptions.id"))
    event_type: Mapped[str] = mapped_column(String(64))
    resource_id: Mapped[str | None] = mapped_column(String(36))
    payload: Mapped[dict] = mapped_column(JSON_TYPE)
    state: Mapped[str] = mapped_column(String(32), default="PENDING")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    run_after: Mapped[datetime] = mapped_column(UTCDateTime)
    delivered_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_reason: Mapped[str | None] = mapped_column(String(64))


class DeliveredResource(OrgRecord):
    __tablename__ = "meeting_delivered_resources"
    __table_args__ = (active_unique("uq_delivered_resource", "subscription_id", "resource_id"),)
    subscription_id: Mapped[str] = mapped_column(String(36))
    resource_id: Mapped[str] = mapped_column(String(36))
    last_delivered_at: Mapped[datetime] = mapped_column(UTCDateTime)


class AuditLog(OrgRecord):
    __tablename__ = "meeting_audit_logs"
    actor_type: Mapped[str] = mapped_column(String(16))
    subject_id: Mapped[str | None] = mapped_column(String(64))
    client_id: Mapped[str | None] = mapped_column(String(36))
    agent_id: Mapped[str | None] = mapped_column(String(128))
    action: Mapped[str] = mapped_column(String(64))
    resource_id: Mapped[str | None] = mapped_column(String(128))
    decision: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str | None] = mapped_column(String(64))
    trace_id: Mapped[str] = mapped_column(String(64))
    details: Mapped[dict] = mapped_column(JSON_TYPE, default=dict)


class RateLimit(Record):
    __tablename__ = "meeting_rate_limits"
    __table_args__ = (active_unique("uq_rate_bucket", "bucket"),)
    bucket: Mapped[str] = mapped_column(String(128))
    next_allowed_at: Mapped[datetime] = mapped_column(UTCDateTime)


class DownloadQuota(OrgRecord):
    __tablename__ = "meeting_download_quotas"
    __table_args__ = (active_unique("uq_download_quota", "client_id", "day"),)
    client_id: Mapped[str] = mapped_column(String(36))
    day: Mapped[str] = mapped_column(String(10))
    reserved_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    completed_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
