from datetime import datetime
from sqlalchemy import Boolean, ForeignKey, Index, Integer, BigInteger, String, Text, Float
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import OrgRecord, Record, UTCDateTime, JSON_TYPE, active_unique


class Meeting(OrgRecord):
    __tablename__ = "meetings"
    __table_args__ = (active_unique("uq_meeting_namespace", "org_id", "external_namespace", "external_id"),)
    connection_id: Mapped[str] = mapped_column(String(36), ForeignKey("meeting_connections.id"), index=True)
    external_namespace: Mapped[str] = mapped_column(String(128))
    external_id: Mapped[str] = mapped_column(String(128))
    subject: Mapped[str] = mapped_column(String(512))
    meeting_code: Mapped[str | None] = mapped_column(String(64))
    created_by_member_id: Mapped[str | None] = mapped_column(String(64), index=True)
    host_member_id: Mapped[str | None] = mapped_column(String(64), index=True)
    start_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    end_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    state: Mapped[str] = mapped_column(String(32), default="UNKNOWN")
    synced_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    source_time_ms: Mapped[int] = mapped_column(BigInteger, default=0)


class Participant(OrgRecord):
    __tablename__ = "meeting_participants"
    __table_args__ = (active_unique("uq_meeting_participant", "meeting_id", "member_id"),)
    meeting_id: Mapped[str] = mapped_column(String(36), ForeignKey("meetings.id"), index=True)
    member_id: Mapped[str] = mapped_column(String(64))
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    source: Mapped[str] = mapped_column(String(32))


class Recording(OrgRecord):
    __tablename__ = "meeting_recordings"
    __table_args__ = (active_unique("uq_record_file", "org_id", "connection_id", "external_file_id"),)
    meeting_id: Mapped[str] = mapped_column(String(36), ForeignKey("meetings.id"), index=True)
    connection_id: Mapped[str] = mapped_column(String(36), ForeignKey("meeting_connections.id"))
    external_file_id: Mapped[str] = mapped_column(String(128))
    external_record_id: Mapped[str | None] = mapped_column(String(128))
    recording_group_id: Mapped[str] = mapped_column(String(128))
    start_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    end_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    state: Mapped[str] = mapped_column(String(32), default="UNKNOWN")
    synced_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class Asset(OrgRecord):
    __tablename__ = "meeting_assets"
    __table_args__ = (active_unique("uq_asset_version", "recording_id", "asset_type", "content_hash"),)
    meeting_id: Mapped[str] = mapped_column(String(36), ForeignKey("meetings.id"), index=True)
    recording_id: Mapped[str] = mapped_column(String(36), ForeignKey("meeting_recordings.id"), index=True)
    connection_id: Mapped[str] = mapped_column(String(36), ForeignKey("meeting_connections.id"))
    asset_type: Mapped[str] = mapped_column(String(16))
    content_hash: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(32), default="UNKNOWN")
    is_complete: Mapped[bool] = mapped_column(Boolean, default=False)
    object_key: Mapped[str | None] = mapped_column(String(256))
    content_type: Mapped[str] = mapped_column(String(128), default="application/json")
    details: Mapped[dict] = mapped_column(JSON_TYPE, default=dict)
    fetched_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    source_health_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class ResourceOrigin(OrgRecord):
    __tablename__ = "meeting_resource_origins"
    meeting_id: Mapped[str] = mapped_column(String(36), ForeignKey("meetings.id"), index=True)
    recording_id: Mapped[str | None] = mapped_column(String(36))
    asset_id: Mapped[str | None] = mapped_column(String(36), index=True)
    connection_id: Mapped[str] = mapped_column(String(36), ForeignKey("meeting_connections.id"))
    purpose: Mapped[str] = mapped_column(String(16))
    ingestion_grant_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("meeting_access_grants.id"))
    owner_member_id: Mapped[str | None] = mapped_column(String(64))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_verified_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_reason: Mapped[str | None] = mapped_column(String(64))


class ResourceACL(OrgRecord):
    __tablename__ = "meeting_resource_acl"
    resource_type: Mapped[str] = mapped_column(String(16))
    resource_id: Mapped[str] = mapped_column(String(36), index=True)
    subject_type: Mapped[str] = mapped_column(String(16))
    subject_id: Mapped[str] = mapped_column(String(64))
    effect: Mapped[str] = mapped_column(String(8))
    actions: Mapped[list] = mapped_column(JSON_TYPE)
    asset_types: Mapped[list] = mapped_column(JSON_TYPE, default=list)
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    issued_by: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str] = mapped_column(String(500))
