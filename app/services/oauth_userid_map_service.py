"""Resolve OAuth open_id to enterprise userid via env AK/SK open-id-to-userid + local map."""
import logging
from sqlalchemy import select
from app.core.errors import MeetingError, UpstreamError
from app.core.types import utcnow
from app.models import Connection, MeetingOAuthUseridMap

logger = logging.getLogger(__name__)


def _as_str_id(value) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value)[:128]
    if isinstance(value, float):
        text = str(int(value)) if value.is_integer() else str(value)
        return text[:128] if text else None
    if isinstance(value, str) and value.strip():
        return value.strip()[:128]
    return None


class OAuthUseridMapService:
    def __init__(self, runtime):
        self.rt = runtime

    async def resolve_userid(self, connection: Connection, *, log_prefix: str) -> str:
        open_id = (connection.external_id or '').strip()
        if not 1 <= len(open_id) <= 128:
            raise MeetingError('IDENTITY_UNBOUND', 409)
        org_id = connection.org_id
        oauth_sdk_id = (self.rt.settings.tencent_meeting_app_id or '').strip()
        fail_event = f'{log_prefix}.userid_resolve_failed'
        lock_key = 'oauth-userid-map:' + org_id + ':' + open_id
        async with self.rt.db.lock(lock_key):
            async with self.rt.db.session() as s:
                row = await s.scalar(select(MeetingOAuthUseridMap).where(
                    MeetingOAuthUseridMap.org_id == org_id,
                    MeetingOAuthUseridMap.open_id == open_id,
                    MeetingOAuthUseridMap.deleted_at.is_(None)))
                if row is not None and row.userid:
                    return row.userid
            try:
                raw = await self.rt.tencent.open_id_to_userid(open_id=open_id)
            except MeetingError as exc:
                logger.warning(
                    '%s connection_id=%s step=open_id_to_userid reason=%s upstream_code=%s',
                    fail_event, connection.id, exc.reason,
                    getattr(exc, 'upstream_code', '') or '')
                raise
            if not isinstance(raw, dict):
                logger.warning(
                    '%s connection_id=%s step=open_id_to_userid reason=UPSTREAM_CONTRACT_ERROR kind=not_object',
                    fail_event, connection.id)
                raise UpstreamError('UPSTREAM_CONTRACT_ERROR')
            invalid = raw.get('invalid_open_id_list') or []
            if isinstance(invalid, list) and open_id in invalid:
                logger.warning(
                    '%s connection_id=%s step=open_id_to_userid reason=IDENTITY_UNBOUND kind=invalid_open_id',
                    fail_event, connection.id)
                raise MeetingError('IDENTITY_UNBOUND', 409)
            userid = None
            listed = raw.get('userid_list')
            if isinstance(listed, list):
                for item in listed:
                    if not isinstance(item, dict):
                        continue
                    if str(item.get('open_id') or '') != open_id:
                        continue
                    candidate = _as_str_id(item.get('userid'))
                    if candidate:
                        userid = candidate
                        break
            if not userid:
                logger.warning(
                    '%s connection_id=%s step=open_id_to_userid reason=UPSTREAM_CONTRACT_ERROR kind=userid_missing',
                    fail_event, connection.id)
                raise UpstreamError('UPSTREAM_CONTRACT_ERROR')
            async with self.rt.db.transaction() as s:
                existing = await s.scalar(select(MeetingOAuthUseridMap).where(
                    MeetingOAuthUseridMap.org_id == org_id,
                    MeetingOAuthUseridMap.open_id == open_id,
                    MeetingOAuthUseridMap.deleted_at.is_(None)))
                if existing is not None:
                    existing.userid = userid
                    existing.oauth_sdk_id = oauth_sdk_id
                    existing.resolved_at = utcnow()
                    existing.version += 1
                else:
                    s.add(MeetingOAuthUseridMap(
                        org_id=org_id,
                        open_id=open_id,
                        userid=userid,
                        oauth_sdk_id=oauth_sdk_id,
                        resolved_at=utcnow(),
                    ))
            return userid
