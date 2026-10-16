from datetime import datetime
from sqlalchemy import Boolean, ForeignKey, Index, Integer, BigInteger, String, Text, Float
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import OrgRecord, Record, UTCDateTime, JSON_TYPE, active_unique


class Operation(OrgRecord):
    __tablename__ = "meeting_operations"
    __table_args__ = (active_unique("uq_operation_idempotency", "idempotency_scope", "idempotency_key_hash"),)
    owner_member_id: Mapped[str] = mapped_column(String(64), index=True)
    client_id: Mapped[str] = mapped_column(String(36))
    agent_grant_id: Mapped[str | None] = mapped_column(String(36))
    connection_id: Mapped[str] = mapped_column(String(36))
    host_member_id: Mapped[str] = mapped_column(String(64))
    idempotency_scope: Mapped[str] = mapped_column(String(64))
    idempotency_key_hash: Mapped[str] = mapped_column(String(64))
    request_hash: Mapped[str] = mapped_column(String(64))
    request_data: Mapped[dict] = mapped_column(JSON_TYPE)
    principal_data: Mapped[dict] = mapped_column(JSON_TYPE)
    operator_data: Mapped[dict] = mapped_column(JSON_TYPE)
    state: Mapped[str] = mapped_column(String(32))
    confirm_deadline: Mapped[datetime] = mapped_column(UTCDateTime)
    approved_by: Mapped[str | None] = mapped_column(String(64))
    approved_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    policy_version: Mapped[int] = mapped_column(BigInteger)
    attempt_started_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    execution_attempt_id: Mapped[str | None] = mapped_column(String(36))
    external_meeting_id: Mapped[str | None] = mapped_column(String(128))
    result_meeting_id: Mapped[str | None] = mapped_column(String(36))
    last_reason: Mapped[str | None] = mapped_column(String(64))
    resolution_note: Mapped[str | None] = mapped_column(String(500))


class DownloadTicket(OrgRecord):
    __tablename__ = "meeting_download_tickets"
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    principal_binding: Mapped[str] = mapped_column(String(64))
    principal_data: Mapped[dict] = mapped_column(JSON_TYPE)
    asset_id: Mapped[str] = mapped_column(String(36), ForeignKey("meeting_assets.id"))
    asset_version: Mapped[str] = mapped_column(String(64))
    purpose: Mapped[str] = mapped_column(String(128))
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    session_expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    bytes_sent: Mapped[int] = mapped_column(BigInteger, default=0)
    active_streams: Mapped[int] = mapped_column(Integer, default=0)
    stream_lease_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class SyncJob(OrgRecord):
    __tablename__ = "meeting_sync_jobs"
    __table_args__ = (active_unique("uq_job_dedup", "dedup_key"), Index("ix_job_ready", "state", "run_after"))
    kind: Mapped[str] = mapped_column(String(32))
    connection_id: Mapped[str | None] = mapped_column(String(36))
    owner_member_id: Mapped[str | None] = mapped_column(String(64))
    client_id: Mapped[str] = mapped_column(String(36))
    agent_grant_id: Mapped[str | None] = mapped_column(String(36))
    ingestion_grant_id: Mapped[str | None] = mapped_column(String(36))
    principal_data: Mapped[dict] = mapped_column(JSON_TYPE, default=dict)
    payload: Mapped[dict] = mapped_column(JSON_TYPE, default=dict)
    progress: Mapped[dict] = mapped_column(JSON_TYPE, default=dict)
    dedup_key: Mapped[str | None] = mapped_column(String(128))
    state: Mapped[str] = mapped_column(String(32), default="PENDING")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    run_after: Mapped[datetime] = mapped_column(UTCDateTime)
    lease_until: Mapped[datetime | None] = mapped_column(UTCDateTime)
    lease_owner: Mapped[str | None] = mapped_column(String(64))
    lease_token: Mapped[str | None] = mapped_column(String(36))
    last_reason: Mapped[str | None] = mapped_column(String(64))


class SyncPolicy(OrgRecord):
    __tablename__ = "meeting_sync_policies"
    connection_id: Mapped[str] = mapped_column(String(36))
    client_id: Mapped[str] = mapped_column(String(36))
    ingestion_grant_id: Mapped[str] = mapped_column(String(36))
    interval_seconds: Mapped[int] = mapped_column(Integer, default=900)
    overlap_seconds: Mapped[int] = mapped_column(Integer, default=3600)
    next_run_at: Mapped[datetime] = mapped_column(UTCDateTime)
    last_success_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
