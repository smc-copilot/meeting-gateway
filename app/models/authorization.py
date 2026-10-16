from datetime import datetime
from sqlalchemy import Boolean, ForeignKey, Index, Integer, BigInteger, String, Text, Float
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import OrgRecord, Record, UTCDateTime, JSON_TYPE, active_unique


class Client(OrgRecord):
    __tablename__ = "meeting_clients"
    name: Mapped[str] = mapped_column(String(128))
    client_type: Mapped[str] = mapped_column(String(32))
    secret_hash: Mapped[str | None] = mapped_column(String(64))
    allowed_scopes: Mapped[list] = mapped_column(JSON_TYPE, default=list)
    redirect_uris: Mapped[list] = mapped_column(JSON_TYPE, default=list)
    owner_member_id: Mapped[str] = mapped_column(String(64))
    agent_id: Mapped[str | None] = mapped_column(String(128))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    allow_service: Mapped[bool] = mapped_column(Boolean, default=False)
    create_policy: Mapped[str] = mapped_column(String(32), default="HUMAN_CONFIRM")


class AccessGrant(OrgRecord):
    __tablename__ = "meeting_access_grants"
    subject_type: Mapped[str] = mapped_column(String(16))
    subject_id: Mapped[str] = mapped_column(String(64), index=True)
    actions: Mapped[list] = mapped_column(JSON_TYPE)
    scope_type: Mapped[str] = mapped_column(String(32))
    resource_ids: Mapped[list] = mapped_column(JSON_TYPE, default=list)
    connection_ids: Mapped[list] = mapped_column(JSON_TYPE, default=list)
    asset_types: Mapped[list] = mapped_column(JSON_TYPE, default=list)
    target_member_ids: Mapped[list] = mapped_column(JSON_TYPE, default=list)
    effect: Mapped[str] = mapped_column(String(8), default="ALLOW")
    purpose: Mapped[str] = mapped_column(String(16), default="ACCESS")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    issued_by: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str] = mapped_column(String(500))


class AgentGrant(OrgRecord):
    __tablename__ = "meeting_agent_grants"
    member_id: Mapped[str] = mapped_column(String(64), index=True)
    client_id: Mapped[str] = mapped_column(String(36), ForeignKey("meeting_clients.id"))
    agent_id: Mapped[str] = mapped_column(String(128))
    actions: Mapped[list] = mapped_column(JSON_TYPE)
    scope_type: Mapped[str] = mapped_column(String(32))
    resource_ids: Mapped[list] = mapped_column(JSON_TYPE, default=list)
    connection_ids: Mapped[list] = mapped_column(JSON_TYPE, default=list)
    asset_types: Mapped[list] = mapped_column(JSON_TYPE, default=list)
    target_member_ids: Mapped[list] = mapped_column(JSON_TYPE, default=list)
    effect: Mapped[str] = mapped_column(String(8), default="ALLOW")
    purpose: Mapped[str] = mapped_column(String(16), default="ACCESS")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    issued_by: Mapped[str] = mapped_column(String(64))
    confirmation_required: Mapped[bool] = mapped_column(Boolean, default=True)
    reason: Mapped[str] = mapped_column(String(500))


class AccessToken(OrgRecord):
    __tablename__ = "meeting_access_tokens"
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    refresh_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    family_id: Mapped[str] = mapped_column(String(36), index=True)
    client_id: Mapped[str] = mapped_column(String(36), ForeignKey("meeting_clients.id"), index=True)
    actor_type: Mapped[str] = mapped_column(String(16))
    member_id: Mapped[str | None] = mapped_column(String(64))
    user_id: Mapped[str | None] = mapped_column(String(64))
    agent_id: Mapped[str | None] = mapped_column(String(128))
    agent_grant_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("meeting_agent_grants.id"))
    audience: Mapped[str] = mapped_column(String(512))
    scopes: Mapped[list] = mapped_column(JSON_TYPE)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    refresh_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    refresh_used_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class AuthTransaction(OrgRecord):
    __tablename__ = "meeting_authorization_transactions"
    purpose: Mapped[str] = mapped_column(String(32), index=True)
    secret_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    application_id: Mapped[str | None] = mapped_column(String(36))
    client_id: Mapped[str | None] = mapped_column(String(36))
    member_id: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="PENDING")
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    used_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    payload: Mapped[dict] = mapped_column(JSON_TYPE, default=dict)
    encrypted_payload: Mapped[str | None] = mapped_column(Text)


class PolicyVersion(OrgRecord):
    __tablename__ = "meeting_policy_versions"
    __table_args__ = (active_unique("uq_policy_org", "org_id"),)
    counter: Mapped[int] = mapped_column(BigInteger, default=1)


class OrganizationPolicy(OrgRecord):
    __tablename__ = "meeting_organization_policies"
    __table_args__ = (active_unique("uq_org_policy", "org_id"),)
    approved_by: Mapped[str] = mapped_column(String(64))
    retention_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    metadata_days: Mapped[int] = mapped_column(Integer, default=180)
    content_days: Mapped[int] = mapped_column(Integer, default=30)
    audit_days: Mapped[int] = mapped_column(Integer, default=180)
    reason: Mapped[str] = mapped_column(String(500))
