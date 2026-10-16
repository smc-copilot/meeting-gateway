"""Meeting identity bridge for NoDeskClaw Backend (baseline 83edfb0d).

This module grants no meeting permissions. Protect /internal/ at the ingress as
well as with the separate service credential. Do not reuse Backend JWT_SECRET.
"""
import hmac
import os
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.deps import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.org_membership import OrgMembership
from app.models.organization import Organization

router = APIRouter(tags=['meeting-identity'])


class ResolveInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    org_id: str = Field(min_length=1, max_length=64)
    member_ids: list[str] = Field(min_length=1, max_length=100)


class SearchInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    org_id: str = Field(min_length=1, max_length=64)
    query: str = Field(default='', max_length=128)
    limit: int = Field(default=30, ge=1, le=100)


def denied(code=403):
    return HTTPException(code, detail={'error_code':40300, 'message_key':'errors.auth.credentials_invalid',
                                      'message':'身份验证失败'})


async def require_service(authorization: str | None = Header(default=None)):
    expected = os.getenv('MEETING_IDENTITY_SERVICE_TOKEN', '')
    if len(expected) < 32:
        raise HTTPException(503, detail={'error_code':50300, 'message_key':'errors.meeting.identity_unconfigured',
                                         'message':'Meeting 身份服务未配置'})
    supplied = authorization[7:] if authorization and authorization.lower().startswith('bearer ') else ''
    if not supplied or not hmac.compare_digest(supplied.encode(), expected.encode()):
        raise denied(401)


def principal(member, user):
    return {'user_id':user.id, 'member_id':member.id, 'org_id':member.org_id, 'name':user.name or '',
            'employee_no':member.employee_no, 'department':member.department, 'job_title':member.job_title,
            'member_role':member.role, 'supervisor_member_id':member.supervisor_membership_id,
            'is_active':bool(user.is_active), 'is_super_admin':bool(user.is_super_admin),
            'must_change_password':bool(user.must_change_password)}


def members_query(org_id):
    return select(OrgMembership, User).join(User, User.id == OrgMembership.user_id).join(
        Organization, Organization.id == OrgMembership.org_id).where(
        OrgMembership.org_id == org_id, OrgMembership.deleted_at.is_(None),
        User.deleted_at.is_(None), User.is_active.is_(True), User.must_change_password.is_(False),
        Organization.deleted_at.is_(None), Organization.is_active.is_(True))


@router.get('/auth/meeting-context')
async def meeting_context(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    from app.services.org.factory import get_org_provider
    organization = await get_org_provider().resolve_org_for_user(user, db)
    if organization is None:
        raise denied()
    pair = (await db.execute(members_query(organization.id).where(User.id == user.id))).one_or_none()
    if pair is None:
        raise denied()
    return {'code':0, 'data':principal(*pair), 'message':'success'}


@router.post('/internal/meeting/principals/resolve', dependencies=[Depends(require_service)])
async def resolve(body: ResolveInput, db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(members_query(body.org_id).where(OrgMembership.id.in_(body.member_ids)))).all()
    return {'code':0, 'data':{'principals':[principal(*row) for row in rows]}, 'message':'success'}


@router.post('/internal/meeting/principals/search', dependencies=[Depends(require_service)])
async def search(body: SearchInput, db: AsyncSession = Depends(get_db)):
    query = members_query(body.org_id)
    if body.query.strip():
        value = body.query.strip()
        query = query.where(or_(User.name.contains(value, autoescape=True),
                                OrgMembership.employee_no.contains(value, autoescape=True)))
    rows = (await db.execute(query.order_by(OrgMembership.id).limit(body.limit))).all()
    return {'code':0, 'data':{'principals':[principal(*row) for row in rows]}, 'message':'success'}
