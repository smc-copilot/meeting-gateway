"""OAuth user basic-info sync; independent of meeting participant cache."""
from sqlalchemy import select
from app.core.errors import MeetingError
from app.core.types import utcnow
from app.integrations.tencent_meeting.mapper import USER_BASIC_MAX_LOOKUPS
from app.models import MeetingOAuthUser
from app.schemas.requests import OAuthUsersSync
from app.services.audit_service import record


def _scalar_str(value, *, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text[:limit] if text else None


class OAuthUsersService:
    def __init__(self, runtime):
        self.rt = runtime

    async def sync(self, principal, body: OAuthUsersSync):
        p = await self.rt.auth.revalidate(principal)
        if p.actor_type != 'MEMBER' or not p.member_id:
            raise MeetingError('PERMISSION_DENIED', 403)
        c, _app = await self.rt.connections.owned(p, body.connection_ref)
        if c.member_id != p.member_id or c.kind != 'THIRD_PARTY_OAUTH':
            raise MeetingError('PERMISSION_DENIED', 403)
        async with self.rt.db.session() as s:
            await self.rt.policy.require(s, p, 'meeting.read', connection_id=c.id)
        operator = await self.rt.connections.operator(c, member_id=p.member_id)
        open_ids = body.open_ids[:USER_BASIC_MAX_LOOKUPS]
        items = []
        upserted = 0
        failed = 0
        for open_id in open_ids:
            try:
                raw = await self.rt.tencent.call(
                    c.id, 'user_basic', operator, query={'operator_id': open_id})
                if not isinstance(raw, dict):
                    raise MeetingError('UPSTREAM_CONTRACT_ERROR', 502)
                username = _scalar_str(raw.get('username'), limit=256)
                open_corp_id = _scalar_str(raw.get('open_corp_id'), limit=128) or ''
                open_corp_name = _scalar_str(raw.get('open_corp_name'), limit=256)
                status = _scalar_str(raw.get('status'), limit=32)
                avatar_url = _scalar_str(raw.get('avatar_url') or raw.get('avatar'), limit=1024)
                async with self.rt.db.transaction() as s:
                    row = await s.scalar(select(MeetingOAuthUser).where(
                        MeetingOAuthUser.org_id == p.org_id,
                        MeetingOAuthUser.open_id == open_id,
                        MeetingOAuthUser.deleted_at.is_(None)))
                    now = utcnow()
                    if row is None:
                        row = MeetingOAuthUser(org_id=p.org_id, open_id=open_id)
                        s.add(row)
                    else:
                        row.version += 1
                    row.open_corp_id = open_corp_id
                    row.username = username
                    row.open_corp_name = open_corp_name
                    row.status = status
                    row.avatar_url = avatar_url
                    row.connection_id = c.id
                    row.synced_at = now
                items.append({
                    'open_id': open_id,
                    'username': username,
                    'open_corp_id': open_corp_id or None,
                    'status': 'UPSERTED',
                    'reason': None,
                })
                upserted += 1
            except MeetingError as exc:
                items.append({
                    'open_id': open_id,
                    'username': None,
                    'open_corp_id': None,
                    'status': 'FAILED',
                    'reason': exc.reason,
                })
                failed += 1
        async with self.rt.db.transaction() as s:
            record(s, p, 'oauth.users.synced', resource_id=c.id,
                   details={'status': upserted, 'bytes': failed})
        return {'items': items, 'upserted': upserted, 'failed': failed}
