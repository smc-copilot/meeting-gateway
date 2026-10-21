"""Strict input DTOs shared by REST and MCP."""
from datetime import datetime
from typing import Literal
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MeetingCreate(StrictModel):
    subject: str = Field(min_length=1, max_length=256)
    start_at: AwareDatetime
    end_at: AwareDatetime
    host_member_id: str = Field(min_length=1, max_length=64)
    invitee_member_ids: list[str] = Field(default_factory=list, max_length=300)
    connection_ref: str = Field(min_length=1, max_length=64)
    business_ref: str | None = Field(None, max_length=128)
    auto_record_type: Literal["NONE", "CLOUD"] = "NONE"

    @field_validator("subject")
    @classmethod
    def subject_not_blank(cls, value):
        if not value.strip():
            raise ValueError("Subject is empty")
        return value.strip()

    @model_validator(mode="after")
    def times(self):
        if self.end_at <= self.start_at:
            raise ValueError("End must follow start")
        if len(self.invitee_member_ids) != len(set(self.invitee_member_ids)):
            raise ValueError("Duplicate invitees")
        return self


class ApplicationCreate(StrictModel):
    name: str = Field(min_length=1, max_length=128)
    application_type: Literal["ENTERPRISE_AKSK", "THIRD_PARTY_OAUTH"]
    environment: Literal["test", "production"] = "test"
    tencent_corp_id: str = Field(min_length=1, max_length=64)
    sdk_id: str = Field(min_length=1, max_length=64)
    data_scope: Literal["enterprise", "user"]
    secret_id: str | None = Field(None, max_length=256)
    secret_key: str | None = Field(None, max_length=512)
    oauth_secret: str | None = Field(None, max_length=512)
    webhook_token: str = Field(min_length=8, max_length=128)
    webhook_encoding_key: str = Field(min_length=43, max_length=44)
    allowed_open_corp_ids: list[str] = Field(default_factory=list, max_length=20)
    reason: str = Field(min_length=3, max_length=500)

    @model_validator(mode="after")
    def type_fields(self):
        if self.application_type == "ENTERPRISE_AKSK":
            if not self.secret_id or not self.secret_key or self.oauth_secret or self.data_scope != "enterprise":
                raise ValueError("AK/SK application fields do not match type")
        elif not self.oauth_secret or self.secret_id or self.secret_key or self.data_scope != "user":
            raise ValueError("OAuth application fields do not match type")
        from app.integrations.tencent_meeting.webhook import _key
        _key(self.webhook_encoding_key)
        return self


class EnterpriseConnectionCreate(StrictModel):
    application_id: str
    admin_member_id: str
    admin_userid: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=3, max_length=500)


class GrantCreate(StrictModel):
    subject_type: Literal["MEMBER", "SERVICE"]
    subject_id: str
    actions: list[str] = Field(min_length=1, max_length=30)
    scope_type: Literal["SELF_CREATED", "EXPLICIT", "ORG_APPROVED", "PARTICIPATED"]
    resource_ids: list[str] = Field(default_factory=list, max_length=1000)
    connection_ids: list[str] = Field(default_factory=list, max_length=100)
    asset_types: list[Literal["transcript", "minutes", "video", "audio"]] = Field(default_factory=list)
    target_member_ids: list[str] = Field(default_factory=list, max_length=300)
    purpose: Literal["ACCESS", "INGESTION", "MANAGE"] = "ACCESS"
    effect: Literal["ALLOW", "DENY"] = "ALLOW"
    expires_at: AwareDatetime | None = None
    reason: str = Field(min_length=3, max_length=500)


class ClientCreate(StrictModel):
    name: str = Field(min_length=1, max_length=128)
    client_type: Literal["CONFIDENTIAL", "PUBLIC_MCP"] = "CONFIDENTIAL"
    allowed_scopes: list[str] = Field(min_length=1, max_length=30)
    redirect_uris: list[str] = Field(default_factory=list, max_length=10)
    owner_member_id: str
    agent_id: str | None = None
    allow_service: bool = False
    create_policy: Literal["HUMAN_CONFIRM", "TRUSTED_MEMBER", "APPROVED_SERVICE"] = "HUMAN_CONFIRM"
    reason: str = Field(min_length=3, max_length=500)


class MeetingQuery(StrictModel):
    selection: Literal["MEETING_ID", "USER_WINDOW", "CORP_WINDOW", "RECORDINGS", "USER_RECORDINGS"]
    connection_ref: str = Field(min_length=1, max_length=64)
    meeting_id: str | None = Field(None, max_length=128)
    target_member_id: str | None = Field(None, max_length=64)
    start_at: AwareDatetime | None = None
    end_at: AwareDatetime | None = None


class OAuthUsersSync(StrictModel):
    connection_ref: str = Field(min_length=1, max_length=64)
    open_ids: list[str] = Field(min_length=1, max_length=50)

    @field_validator("open_ids")
    @classmethod
    def open_ids_nonblank(cls, value):
        cleaned = []
        seen = set()
        for item in value:
            if not isinstance(item, str):
                raise ValueError("open_id must be string")
            text = item.strip()
            if not text or len(text) > 128:
                raise ValueError("open_id invalid")
            if text in seen:
                continue
            seen.add(text)
            cleaned.append(text)
        if not cleaned:
            raise ValueError("open_ids required")
        return cleaned


class OperationConfirm(StrictModel):
    request_hash: str = Field(min_length=64, max_length=64)


class OperationReject(StrictModel):
    reason: str = Field(min_length=3, max_length=500)


class OAuthSession(StrictModel):
    authorization_code: str = Field(min_length=8, max_length=256)
    client_id: str | None = Field(None, max_length=64)
    client_secret: str | None = Field(None, max_length=512)
    scopes: list[str] = Field(default_factory=list, max_length=30)


class AgentGrantCreate(StrictModel):
    client_id: str
    agent_id: str = Field(min_length=1, max_length=128)
    actions: list[str] = Field(min_length=1, max_length=10)
    scope_type: Literal["SELF_CREATED", "EXPLICIT", "ORG_APPROVED"] = "EXPLICIT"
    resource_ids: list[str] = Field(default_factory=list, max_length=1000)
    connection_ids: list[str] = Field(default_factory=list, max_length=100)
    asset_types: list[str] = Field(default_factory=lambda: ["transcript", "minutes"])
    target_member_ids: list[str] = Field(default_factory=list)
    expires_at: AwareDatetime | None = None
    reason: str = Field(min_length=3, max_length=500)


class IdentityBind(StrictModel):
    application_id: str
    member_id: str
    external_id: str = Field(min_length=1, max_length=128)
    external_corp_id: str = Field(min_length=1, max_length=128)
    verification_source: str = Field(min_length=3, max_length=500)
    reason: str = Field(min_length=3, max_length=500)


class SyncRequest(StrictModel):
    connection_ref: str
    kind: Literal["CORP_RECORDS", "USER_RECORDS", "USER_HISTORY", "USER_UPCOMING", "MEETING_RECORDS", "CONTENT"]
    start_at: AwareDatetime | None = None
    end_at: AwareDatetime | None = None
    meeting_id: str | None = None
    recording_id: str | None = None
    content_type: Literal["transcript", "minutes"] | None = None

    @model_validator(mode="after")
    def interval(self):
        if self.kind in {"CORP_RECORDS", "USER_RECORDS", "USER_HISTORY"} and (
            self.start_at is None or self.end_at is None or self.start_at >= self.end_at
        ):
            raise ValueError("Valid time window required")
        if self.kind == "CONTENT" and (not self.recording_id or not self.content_type):
            raise ValueError("Recording and content type required")
        if self.kind == "MEETING_RECORDS" and not self.meeting_id:
            raise ValueError("Meeting required")
        return self


class Reason(StrictModel):
    reason: str = Field(min_length=3, max_length=500)


class DownloadRequest(StrictModel):
    purpose: str = Field(min_length=3, max_length=128)


class ACLCreate(StrictModel):
    resource_type: Literal["meeting", "asset"]
    resource_id: str
    subject_type: Literal["MEMBER", "SERVICE"]
    subject_id: str
    effect: Literal["ALLOW", "DENY"]
    actions: list[str] = Field(min_length=1)
    asset_types: list[str] = Field(default_factory=list)
    expires_at: AwareDatetime | None = None
    reason: str = Field(min_length=3, max_length=500)
