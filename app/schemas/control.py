"""Bounded control-plane payloads; never pass arbitrary operator or upstream API parameters."""
from typing import Literal
from pydantic import Field
from app.schemas.requests import StrictModel,SyncRequest

class ExchangeRequest(StrictModel):
    client_id: str = Field(min_length=1,max_length=64)
    client_secret: str = Field(min_length=1,max_length=512)
    subject_token: str = Field(min_length=1,max_length=8192)
    scopes: list[str] = Field(min_length=1,max_length=30)
    resource: str = Field(min_length=1,max_length=512)

class Approval(StrictModel):
    request_hash: str = Field(pattern=r'^[0-9a-f]{64}$')

class Consent(StrictModel):
    agent_grant_id: str | None = Field(None,max_length=64)

class Reconciliation(StrictModel):
    action: Literal['LINK_VERIFIED_MEETING','CLOSE_UNRESOLVED']
    reason: str = Field(min_length=3,max_length=500)
    meeting_id: str | None = Field(None,max_length=64)

class Retention(StrictModel):
    metadata_days: int = Field(180,ge=1,le=3650)
    content_days: int = Field(30,ge=1,le=3650)
    audit_days: int = Field(180,ge=1,le=3650)
    reason: str = Field(min_length=3,max_length=500)

class STSGenerate(StrictModel):
    valid_hours: Literal[6,12,24] = 6

class Diagnostic(StrictModel):
    probe: Literal['configuration','oauth_user_info','upcoming','history','records','corp_records','record_detail','transcript','minutes']
    recording_id: str | None = Field(None,max_length=64)

class AdminSync(StrictModel):
    service_client_id: str = Field(min_length=1,max_length=64)
    request: SyncRequest

class PolicyCreate(StrictModel):
    connection_ref: str
    client_id: str
    ingestion_grant_id: str
    interval_seconds: int = Field(900,ge=300,le=86400)
    overlap_seconds: int = Field(3600,ge=60,le=2678400)
    reason: str = Field(min_length=3,max_length=500)

class SubscriptionCreate(StrictModel):
    client_id: str
    destination: str = Field(max_length=1024)
    event_types: list[str] = Field(min_length=1,max_length=10)
    member_id: str | None = None
    agent_grant_id: str | None = None
    reason: str = Field(min_length=3,max_length=500)

class TokenForm(StrictModel):
    grant_type: Literal['authorization_code','refresh_token','client_credentials']
    client_id: str | None = Field(None,max_length=64)
    client_secret: str | None = Field(None,max_length=512)
    code: str | None = Field(None,max_length=256)
    code_verifier: str | None = Field(None,max_length=128)
    redirect_uri: str | None = Field(None,max_length=1024)
    refresh_token: str | None = Field(None,max_length=256)
    resource: str = Field(max_length=512)
    scope: str = Field('',max_length=1024)
