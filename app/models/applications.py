from datetime import datetime
from sqlalchemy import Boolean, ForeignKey, Index, Integer, BigInteger, String, Text, Float
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import OrgRecord, Record, UTCDateTime, JSON_TYPE, active_unique


class Application(OrgRecord):
    __tablename__ = "meeting_applications"
    __table_args__ = (active_unique("uq_meeting_app", "org_id", "environment", "sdk_id"),)
    name: Mapped[str] = mapped_column(String(128))
    application_type: Mapped[str] = mapped_column(String(32))
    environment: Mapped[str] = mapped_column(String(16))
    tencent_corp_id: Mapped[str] = mapped_column(String(64))
    sdk_id: Mapped[str] = mapped_column(String(64))
    data_scope: Mapped[str] = mapped_column(String(16))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    receiver_id: Mapped[str | None] = mapped_column(String(36), unique=True)
    allowed_open_corp_ids: Mapped[list] = mapped_column(JSON_TYPE, default=list)
    webhook_verified_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_callback_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    settings_data: Mapped[dict] = mapped_column(JSON_TYPE, default=dict)


class Credential(OrgRecord):
    __tablename__ = "meeting_credentials"
    application_id: Mapped[str] = mapped_column(String(36), ForeignKey("meeting_applications.id"), index=True)
    connection_id: Mapped[str | None] = mapped_column(String(36), index=True)
    purpose: Mapped[str] = mapped_column(String(32), index=True)
    ciphertext: Mapped[str] = mapped_column(Text)
    key_id: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    generation: Mapped[int] = mapped_column(BigInteger, default=1)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Connection(OrgRecord):
    __tablename__ = "meeting_connections"
    __table_args__ = (active_unique("uq_connection_identity", "org_id", "application_id", "external_id"),)
    application_id: Mapped[str] = mapped_column(String(36), ForeignKey("meeting_applications.id"), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    member_id: Mapped[str | None] = mapped_column(String(64), index=True)
    external_id: Mapped[str] = mapped_column(String(128))
    external_corp_id: Mapped[str | None] = mapped_column(String(128))
    corporate_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(32), default="DRAFT")
    scopes: Mapped[list] = mapped_column(JSON_TYPE, default=list)
    capabilities: Mapped[dict] = mapped_column(JSON_TYPE, default=dict)
    last_verified_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_reason: Mapped[str | None] = mapped_column(String(64))
    last_synced_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    sync_coverage: Mapped[list] = mapped_column(JSON_TYPE, default=list)
    consent_confirmed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    source_health_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    settings_data: Mapped[dict] = mapped_column(JSON_TYPE, default=dict)


class IdentityBinding(OrgRecord):
    __tablename__ = "meeting_identity_bindings"
    __table_args__ = (
        active_unique("uq_binding_external", "org_id", "application_id", "identity_type", "external_id"),
        active_unique("uq_binding_member", "org_id", "application_id", "identity_type", "member_id"),
    )
    application_id: Mapped[str] = mapped_column(String(36), ForeignKey("meeting_applications.id"))
    member_id: Mapped[str] = mapped_column(String(64), index=True)
    identity_type: Mapped[str] = mapped_column(String(16), default="userid")
    external_id: Mapped[str] = mapped_column(String(128))
    external_corp_id: Mapped[str] = mapped_column(String(128))
    verification_source: Mapped[str] = mapped_column(String(500))
    verified_by: Mapped[str] = mapped_column(String(64))
    verified_at: Mapped[datetime] = mapped_column(UTCDateTime)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class STSRequest(OrgRecord):
    __tablename__ = "meeting_sts_requests"
    application_id: Mapped[str] = mapped_column(String(36), ForeignKey("meeting_applications.id"), index=True)
    connection_id: Mapped[str] = mapped_column(String(36), ForeignKey("meeting_connections.id"))
    req_id: Mapped[str | None] = mapped_column(String(128), index=True)
    requested_at: Mapped[datetime] = mapped_column(UTCDateTime)
    valid_hours: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), default="REQUESTED")
    generation: Mapped[int] = mapped_column(BigInteger)


class STSCallback(OrgRecord):
    __tablename__ = "meeting_sts_callbacks"
    __table_args__ = (active_unique("uq_sts_callback_req", "application_id", "req_id"),)
    application_id: Mapped[str] = mapped_column(String(36), ForeignKey("meeting_applications.id"))
    req_id: Mapped[str] = mapped_column(String(128))
    token_ciphertext: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    operator_id: Mapped[str | None] = mapped_column(String(128))
    operate_time_ms: Mapped[int] = mapped_column(BigInteger, default=0)
    associated_request_id: Mapped[str | None] = mapped_column(String(36))
