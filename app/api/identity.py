from fastapi import APIRouter, Request, Depends
from app.api.deps import runtime, envelope, human
from app.core.errors import MeetingError
from app.schemas.requests import StrictModel
from pydantic import Field

router = APIRouter(tags=["meeting-identity"])


class AccountLogin(StrictModel):
    account: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=1, max_length=200)


class MemberChange(StrictModel):
    reason: str = Field(min_length=3, max_length=500)


@router.post("/auth/account-login")
async def account_login(request: Request, body: AccountLogin):
    data = await runtime(request).identity.login(body.account, body.password)
    data.pop("session_id", None)
    return envelope(request, data)


@router.get("/auth/session")
async def current_session(request: Request, p=Depends(human)):
    return envelope(request, {"org_id": p.org_id, "member_id": p.member_id, "user_id": p.user_id,
                              "member_role": p.member_role, "expires_at": p.identity_expires_at})


@router.post("/auth/logout")
async def logout(request: Request):
    header = request.headers.get("authorization", "")
    token = header.removeprefix("Bearer ").strip()
    if not token.startswith("ms_"):
        raise MeetingError("IDENTITY_REAUTH_REQUIRED", 401)
    return envelope(request, await runtime(request).identity.logout(token))


@router.post("/admin/members/{member_id}/disable")
async def disable_member(request: Request, member_id: str, body: MemberChange, p=Depends(human)):
    return envelope(request, await runtime(request).identity.disable(p, member_id, body.reason))


@router.post("/admin/members/{member_id}/enable")
async def enable_member(request: Request, member_id: str, body: MemberChange, p=Depends(human)):
    return envelope(request, await runtime(request).identity.enable(p, member_id, body.reason))
