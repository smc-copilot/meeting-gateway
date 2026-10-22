"""Local-first meeting participants cache backed by Tencent 42701 (env AK/SK)."""
import logging
from sqlalchemy import select
from app.core.errors import MeetingError, UpstreamError
from app.core.types import utcnow
from app.integrations.tencent_meeting.mapper import (
    PARTICIPANTS_MAX_PAGES, PARTICIPANTS_MAX_PEOPLE, PARTICIPANTS_PAGE_SIZE,
    cache_participant_fields, participant_dedupe_key,
)
from app.models import MeetingParticipantRow, MeetingParticipantSnapshot
from app.services.audit_service import record
from app.services.oauth_userid_map_service import OAuthUseridMapService

logger = logging.getLogger(__name__)


class ParticipantCacheService:
    def __init__(self, runtime):
        self.rt = runtime

    async def list_participants(self, principal, connection_ref: str, meeting_id: str, *,
                                pos: int = 0, size: int = 20):
        if not meeting_id or len(meeting_id) > 128:
            raise MeetingError('INVALID_REQUEST', 422)
        if pos < 0 or size < 1 or size > 100:
            raise MeetingError('INVALID_REQUEST', 422)
        p = await self.rt.auth.revalidate(principal)
        if p.actor_type != 'MEMBER' or not p.member_id:
            raise MeetingError('PERMISSION_DENIED', 403)
        c, _app = await self.rt.connections.owned(p, connection_ref)
        if c.member_id != p.member_id or c.kind != 'THIRD_PARTY_OAUTH':
            raise MeetingError('PERMISSION_DENIED', 403)
        async with self.rt.db.session() as s:
            await self.rt.policy.require(s, p, 'meeting.read', connection_id=c.id)

        lock_key = 'participants-cache:' + c.id + ':' + meeting_id
        async with self.rt.db.lock(lock_key):
            snapshot = await self._find_snapshot(p.org_id, c.id, meeting_id)
            source = 'cache'
            if snapshot is None:
                if self.rt.settings.tencent_enterprise_aksk() is None:
                    logger.warning(
                        'q2.participants_failed connection_id=%s meeting_id=%s step=env_aksk reason=UPSTREAM_CREDENTIAL_INVALID',
                        c.id, meeting_id)
                    raise MeetingError('UPSTREAM_CREDENTIAL_INVALID', 409)
                try:
                    userid = await OAuthUseridMapService(self.rt).resolve_userid(c, log_prefix='q2')
                    pages, meta = await self._fetch_all_pages(userid, meeting_id)
                except MeetingError as exc:
                    logger.warning(
                        'q2.participants_failed connection_id=%s meeting_id=%s reason=%s upstream_code=%s status=%s',
                        c.id, meeting_id, exc.reason,
                        getattr(exc, 'upstream_code', '') or '',
                        exc.status)
                    raise
                rows = self._dedupe_rows(pages)
                snapshot = await self._write_all(p.org_id, c.id, meeting_id, rows, meta)
                source = 'fetched'
                async with self.rt.db.transaction() as s:
                    record(s, p, 'meeting.participants.cached', resource_id=c.id,
                           details={'status': len(rows)})

        return await self._page_local(snapshot, meeting_id, source=source, pos=pos, size=size)

    async def _find_snapshot(self, org_id, connection_id, meeting_id):
        async with self.rt.db.session() as s:
            return await s.scalar(select(MeetingParticipantSnapshot).where(
                MeetingParticipantSnapshot.org_id == org_id,
                MeetingParticipantSnapshot.connection_id == connection_id,
                MeetingParticipantSnapshot.external_meeting_id == meeting_id,
                MeetingParticipantSnapshot.deleted_at.is_(None)))

    async def _fetch_all_pages(self, userid, meeting_id):
        pages = []
        pos = 0
        people = 0
        meta = {'meeting_code': None, 'subject': None, 'total_count': None}
        for _ in range(PARTICIPANTS_MAX_PAGES):
            page = await self.rt.tencent.participants_aksk(
                meeting_id=meeting_id,
                userid=userid,
                query={'pos': pos, 'size': PARTICIPANTS_PAGE_SIZE})
            if not isinstance(page, dict):
                raise UpstreamError('UPSTREAM_CONTRACT_ERROR')
            rows = page.get('participants')
            if not isinstance(rows, list):
                raise UpstreamError('UPSTREAM_CONTRACT_ERROR')
            people += len(rows)
            if people > PARTICIPANTS_MAX_PEOPLE:
                raise UpstreamError('UPSTREAM_CONTRACT_ERROR')
            pages.append(page)
            if meta['meeting_code'] is None and page.get('meeting_code') not in (None, ''):
                meta['meeting_code'] = str(page.get('meeting_code'))[:64]
            if meta['subject'] is None and isinstance(page.get('subject'), str) and page.get('subject'):
                meta['subject'] = page['subject'][:512]
            if meta['total_count'] is None and isinstance(page.get('total_count'), int):
                meta['total_count'] = page['total_count']
            remaining = page.get('has_remaining')
            if remaining is True:
                next_pos = page.get('next_pos')
                if not isinstance(next_pos, int) or next_pos == pos:
                    raise UpstreamError('UPSTREAM_CONTRACT_ERROR')
                pos = next_pos
                continue
            if remaining in (False, None):
                return pages, meta
            raise UpstreamError('UPSTREAM_CONTRACT_ERROR')
        raise UpstreamError('UPSTREAM_CONTRACT_ERROR')

    def _dedupe_rows(self, pages: list[dict]) -> list[dict]:
        ordered = []
        seen: set[str] = set()
        for page in pages:
            rows = page.get('participants') if isinstance(page, dict) else None
            if not isinstance(rows, list):
                raise UpstreamError('UPSTREAM_CONTRACT_ERROR')
            for row in rows:
                if not isinstance(row, dict):
                    raise UpstreamError('UPSTREAM_CONTRACT_ERROR')
                fields = cache_participant_fields(row)
                key = participant_dedupe_key(row)
                if key is None:
                    ordered.append(fields)
                    continue
                if key in seen:
                    continue
                seen.add(key)
                ordered.append(fields)
        return ordered

    async def _write_all(self, org_id, connection_id, meeting_id, rows, meta):
        async with self.rt.db.transaction() as s:
            existing = await s.scalar(select(MeetingParticipantSnapshot).where(
                MeetingParticipantSnapshot.org_id == org_id,
                MeetingParticipantSnapshot.connection_id == connection_id,
                MeetingParticipantSnapshot.external_meeting_id == meeting_id,
                MeetingParticipantSnapshot.deleted_at.is_(None)))
            if existing is not None:
                return existing
            now = utcnow()
            snapshot = MeetingParticipantSnapshot(
                org_id=org_id,
                connection_id=connection_id,
                external_meeting_id=meeting_id,
                meeting_code=meta.get('meeting_code'),
                subject=meta.get('subject'),
                total_count=meta.get('total_count') if meta.get('total_count') is not None else len(rows),
                fetched_at=now,
            )
            s.add(snapshot)
            await s.flush()
            for index, fields in enumerate(rows):
                s.add(MeetingParticipantRow(
                    org_id=org_id,
                    snapshot_id=snapshot.id,
                    connection_id=connection_id,
                    external_meeting_id=meeting_id,
                    open_id=fields['open_id'],
                    userid=fields['userid'],
                    ms_open_id=fields['ms_open_id'],
                    user_name_b64=fields['user_name_b64'],
                    join_name=fields['join_name'],
                    is_enterprise_user=fields['is_enterprise_user'],
                    sort_index=index,
                ))
            return snapshot

    async def _page_local(self, snapshot, meeting_id, *, source: str, pos: int, size: int):
        async with self.rt.db.session() as s:
            result = await s.execute(
                select(MeetingParticipantRow)
                .where(
                    MeetingParticipantRow.snapshot_id == snapshot.id,
                    MeetingParticipantRow.deleted_at.is_(None),
                )
                .order_by(MeetingParticipantRow.sort_index.asc())
            )
            all_rows = list(result.scalars())
        total = len(all_rows)
        page = all_rows[pos:pos + size]
        participants = [{
            'open_id': row.open_id,
            'userid': row.userid,
            'ms_open_id': row.ms_open_id,
            'join_name': row.join_name,
            'is_enterprise_user': row.is_enterprise_user,
        } for row in page]
        next_pos = pos + len(page)
        return {
            'meeting_id': meeting_id,
            'source': source,
            'participant_count': total,
            'total_count': snapshot.total_count if snapshot.total_count is not None else total,
            'pos': pos,
            'size': size,
            'has_remaining': next_pos < total,
            'next_pos': next_pos if next_pos < total else None,
            'participants': participants,
        }
