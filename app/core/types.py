"""Identity context is constructed by authentication, never from tool arguments."""
from datetime import UTC, datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


def utcnow() -> datetime:
    return datetime.now(UTC)


class MemberContext(BaseModel):
    model_config = ConfigDict(extra="ignore")
    org_id: str
    user_id: str
    member_id: str
    name: str = ""
    member_role: str = "member"
    is_active: bool = True
    must_change_password: bool = False
    is_super_admin: bool = False
    employee_no: str | None = None
    department: str | None = None


class Principal(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    org_id: str
    actor_type: Literal["MEMBER", "AGENT", "SERVICE"]
    client_id: str
    member_id: str | None = None
    user_id: str | None = None
    agent_id: str | None = None
    agent_grant_id: str | None = None
    token_id: str | None = None
    audience: str = ""
    scopes: frozenset[str] = Field(default_factory=frozenset)
    policy_version: int = 0
    portal: bool = False
    member_role: str = "member"
    is_super_admin: bool = False
    trace_id: str = ""
    session_issued_at: datetime | None = None
    identity_expires_at: datetime | None = None
    identity_session_id: str | None = None
    identity_version: int | None = None
    auth_mode_epoch: int | None = None

    @property
    def subject_id(self) -> str:
        return self.member_id or self.client_id

    @property
    def subject_type(self) -> str:
        return "SERVICE" if self.actor_type == "SERVICE" else "MEMBER"

    @property
    def binding(self) -> str:
        return ":".join([self.org_id, self.client_id, self.actor_type, self.subject_id,
                         self.agent_grant_id or "", self.audience])


class Operator(BaseModel):
    id: str
    type: Literal[1, 2]
