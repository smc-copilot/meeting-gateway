from datetime import datetime
from sqlalchemy import Boolean, BigInteger, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import OrgRecord, Record, UTCDateTime, JSON_TYPE, active_unique


class IdentityDeployment(Record):
    __tablename__ = "meeting_identity_deployments"
    __table_args__ = (active_unique("uq_identity_deployment_component", "component_id"),)
    component_id: Mapped[str] = mapped_column(String(64))
    org_id: Mapped[str] = mapped_column(String(64))
    issuer_id: Mapped[str] = mapped_column(String(64))
    namespace_version: Mapped[int] = mapped_column(Integer, default=1)
    auth_mode_epoch: Mapped[int] = mapped_column(BigInteger, default=1)
    applied_config_digest: Mapped[str] = mapped_column(String(64))


class LocalMember(OrgRecord):
    __tablename__ = "meeting_local_members"
    __table_args__ = (active_unique("uq_local_member_external", "component_id", "org_id", "issuer_id", "external_user_id"),)
    component_id: Mapped[str] = mapped_column(String(64))
    issuer_id: Mapped[str] = mapped_column(String(64))
    external_user_id: Mapped[str] = mapped_column(String(64), index=True)
    source: Mapped[str] = mapped_column(String(32), default="ACCOUNT_LOGIN")
    local_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    state: Mapped[str] = mapped_column(String(32), default="ACTIVE")
    identity_version: Mapped[int] = mapped_column(BigInteger, default=1)
    last_applied_attempt_seq: Mapped[int] = mapped_column(BigInteger, default=0)
    last_verified_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    member_role: Mapped[str] = mapped_column(String(16), default="member")
    profile_json: Mapped[dict] = mapped_column(JSON_TYPE, default=dict)


class LoginObservation(Record):
    __tablename__ = "meeting_login_observations"
    member_id: Mapped[str | None] = mapped_column(String(36), index=True)
    attempt_seq: Mapped[int] = mapped_column(BigInteger)
    received_at: Mapped[datetime] = mapped_column(UTCDateTime)
    normalized_role: Mapped[str] = mapped_column(String(32))
    observed_flags: Mapped[dict] = mapped_column(JSON_TYPE, default=dict)
    accepted_for_session: Mapped[bool] = mapped_column(Boolean)
    source_expires_in: Mapped[int] = mapped_column(Integer, default=0)
    valid_until: Mapped[datetime] = mapped_column(UTCDateTime)
    projection_digest: Mapped[str] = mapped_column(String(64))


class IdentitySession(Record):
    __tablename__ = "meeting_identity_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    member_id: Mapped[str] = mapped_column(String(36), index=True)
    observation_id: Mapped[str] = mapped_column(String(36))
    component_id: Mapped[str] = mapped_column(String(64))
    org_id: Mapped[str] = mapped_column(String(64), index=True)
    issued_at: Mapped[datetime] = mapped_column(UTCDateTime)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    identity_version: Mapped[int] = mapped_column(BigInteger)
    auth_mode_epoch: Mapped[int] = mapped_column(BigInteger)


class LegacyMemberMap(OrgRecord):
    __tablename__ = "meeting_legacy_member_maps"
    __table_args__ = (active_unique("uq_legacy_member", "org_id", "legacy_member_id"),)
    legacy_member_id: Mapped[str] = mapped_column(String(64))
    local_member_id: Mapped[str] = mapped_column(String(36))
    external_user_id: Mapped[str] = mapped_column(String(64))
    note: Mapped[str] = mapped_column(Text, default="")
