"""Source lookup is separate from the local catalogue. A miss stores nothing about the meeting."""
import logging
from datetime import timedelta
from sqlalchemy import select
from app.core.errors import MeetingError, UpstreamError
from app.core.types import Principal, utcnow
from app.integrations.tencent_meeting.mapper import milliseconds, seconds
from app.models import SyncJob
from app.schemas.requests import MeetingQuery
from app.services.audit_service import record
from app.services.sync_service import windows

logger = logging.getLogger(__name__)


class QueryService:
    def __init__(self, runtime):
        self.rt = runtime

    async def submit(self, principal, body: MeetingQuery):
        if body.selection == 'USER_RECORDINGS':
            body = body.model_copy(update={'selection': 'RECORDINGS'})
        if body.selection == 'CORP_WINDOW':
            raise MeetingError('PERMISSION_DENIED', 403)
        p = await self.rt.auth.revalidate(principal)
        if p.actor_type != 'MEMBER' or not p.member_id:
            raise MeetingError('PERMISSION_DENIED', 403)
        c, _app = await self.rt.connections.owned(p, body.connection_ref)
        if c.member_id != p.member_id or c.kind not in {'THIRD_PARTY_OAUTH', 'ENTERPRISE_AKSK'}:
            raise MeetingError('PERMISSION_DENIED', 403)
        if body.selection == 'USER_WINDOW':
            if body.target_member_id != p.member_id or body.start_at is None or body.end_at is None or body.start_at >= body.end_at:
                raise MeetingError('PERMISSION_DENIED', 403) if body.target_member_id != p.member_id else MeetingError('INVALID_REQUEST', 422)
            if list(windows(body.start_at, body.end_at, 90)).__len__() > 120:
                raise MeetingError('INVALID_REQUEST', 422)
        elif body.selection in {'MEETING_ID', 'RECORDINGS'}:
            if not body.meeting_id:
                raise MeetingError('INVALID_REQUEST', 422)
        else:
            raise MeetingError('INVALID_REQUEST', 422)
        async with self.rt.db.session() as s:
            await self.rt.policy.require(s, p, 'meeting.read', connection_id=c.id)
        if body.selection == 'RECORDINGS':
            async with self.rt.db.transaction() as s:
                payload = body.model_dump(mode='json')
                job = await self.rt.jobs.enqueue(s, 'SOURCE_QUERY', p, payload, connection_id=c.id)
                record(s, p, 'meeting.query.accepted', resource_id=job.id)
                return {'accepted': True, 'job_id': job.id, 'selection': body.selection}
        operator = await self.rt.connections.operator(c, member_id=p.member_id)
        try:
            if body.selection == 'USER_WINDOW':
                items = []
                for raw in await self._scan_history(c, operator, body):
                    item = self._project(c, raw, history=True)
                    if item:
                        items.append(item)
            else:
                items = [await self._fetch_meeting(c, operator, body.meeting_id)]
        except MeetingError as exc:
            logger.warning(
                'q1.meeting_queries_failed connection_id=%s selection=%s step=upstream '
                'reason=%s upstream_code=%s status=%s',
                c.id, body.selection, exc.reason,
                getattr(exc, 'upstream_code', '') or '',
                exc.status)
            raise
        async with self.rt.db.transaction() as s:
            record(s, p, 'meeting.query.listed', resource_id=c.id)
        return {'selection': body.selection, 'items': items, 'meeting_count': len(items)}

    async def run(self, job, lease_token):
        body = MeetingQuery.model_validate(job.payload)
        if body.selection == 'USER_RECORDINGS':
            body = body.model_copy(update={'selection': 'RECORDINGS'})
        if body.selection == 'CORP_WINDOW':
            raise MeetingError('PERMISSION_DENIED', 403)
        p = await self.rt.auth.revalidate(Principal.model_validate(job.principal_data))
        c, _app = await self.rt.connections.owned(p, job.connection_id)
        if c.member_id != p.member_id or c.kind not in {'THIRD_PARTY_OAUTH', 'ENTERPRISE_AKSK'}:
            raise MeetingError('PERMISSION_DENIED', 403)
        operator = await self.rt.connections.operator(c, member_id=p.member_id)
        async with self.rt.db.session() as s:
            await self.rt.jobs.fence(s, job.id, lease_token)
            await self.rt.policy.require(s, p, 'meeting.read', connection_id=c.id)
        if body.selection == 'USER_WINDOW':
            await self._history(job, lease_token, p, c, operator, body)
            return
        if body.selection == 'RECORDINGS':
            await self._recordings(job, lease_token, p, c, operator, body)
            return
        item = await self._fetch_meeting(c, operator, body.meeting_id,
                                         heartbeat=lambda: self.rt.jobs.heartbeat(job.id, lease_token), raw=True)
        async with self.rt.db.transaction() as s:
            await self.rt.meetings.upsert(s, c, item, purpose='SOURCE_QUERY', owner_member_id=p.member_id)

    async def ensure_meeting(self, principal, meeting_id):
        p = await self.rt.auth.revalidate(principal)
        async with self.rt.db.transaction() as s:
            row = await self.rt.meetings.row(s, p, meeting_id)
            fresh = row.synced_at and row.synced_at > utcnow() - timedelta(seconds=self.rt.settings.source_health_seconds)
            if fresh:
                return None
            c, _app = await self.rt.connections.owned(p, row.connection_id)
            payload = {'selection': 'MEETING_ID', 'connection_ref': c.id, 'meeting_id': row.external_id,
                       'target_member_id': None, 'start_at': None, 'end_at': None}
            try:
                await self.rt.connections.operator(c, member_id=p.member_id)
            except MeetingError as exc:
                raise MeetingError('UPSTREAM_CAPABILITY_UNAVAILABLE', 409) from exc
            job = await self.rt.jobs.enqueue(s, 'SOURCE_QUERY', p, payload, connection_id=c.id, dedup_key='ensure-meeting:' + row.id)
            return job.id

    async def ensure_recordings(self, principal, meeting_id):
        p = await self.rt.auth.revalidate(principal)
        async with self.rt.db.transaction() as s:
            row = await self.rt.meetings.row(s, p, meeting_id)
            c, _app = await self.rt.connections.owned(p, row.connection_id)
            if c.member_id != p.member_id or c.kind not in {'THIRD_PARTY_OAUTH', 'ENTERPRISE_AKSK'}:
                raise MeetingError('UPSTREAM_CAPABILITY_UNAVAILABLE', 409)
            try:
                await self.rt.connections.operator(c, member_id=p.member_id)
            except MeetingError as exc:
                raise MeetingError('UPSTREAM_CAPABILITY_UNAVAILABLE', 409) from exc
            slot = int(utcnow().timestamp()) // max(self.rt.settings.source_health_seconds, 1)
            dedup = 'ensure-recordings:' + row.id + ':' + str(slot)
            existing = await s.scalar(select(SyncJob).where(SyncJob.dedup_key == dedup, SyncJob.deleted_at.is_(None)))
            if existing and existing.state == 'SUCCEEDED':
                return None
            if existing:
                return existing.id
            payload = {'selection': 'RECORDINGS', 'connection_ref': c.id, 'meeting_id': row.external_id,
                       'target_member_id': p.member_id, 'start_at': (row.start_at or utcnow()).isoformat(),
                       'end_at': (row.end_at or utcnow()).isoformat()}
            job = await self.rt.jobs.enqueue(s, 'SOURCE_QUERY', p, payload, connection_id=c.id, dedup_key=dedup)
            return job.id

    async def _remember(self, job_id, lease_token, progress):
        async with self.rt.db.transaction() as s:
            current = await self.rt.jobs.fence(s, job_id, lease_token)
            current.progress = {**(current.progress or {}), **progress}

    def _project(self, connection, raw, *, history=False):
        if not isinstance(raw, dict) or not raw.get('meeting_id') or not isinstance(raw.get('subject', ''), str):
            return None
        return {
            'meeting_id': str(raw['meeting_id']),
            'subject': raw.get('subject', '')[:512],
            'meeting_code': str(raw.get('meeting_code') or '') or None,
            'start_at': seconds(raw.get('start_time')) or milliseconds(raw.get('media_start_time')),
            'end_at': seconds(raw.get('end_time')),
            'state': 'ENDED' if history else str(raw.get('status') or 'UNKNOWN')[:32],
            'connection_ref': connection.id,
        }

    async def _fetch_meeting(self, connection, operator, meeting_id, *, heartbeat=None, raw=False):
        try:
            payload = await self.rt.tencent.call(connection.id, 'meeting', operator, file_id=meeting_id, heartbeat=heartbeat)
        except MeetingError as exc:
            if exc.reason == 'RESOURCE_NOT_ACCESSIBLE':
                raise
            raise MeetingError('RESOURCE_NOT_ACCESSIBLE', 404) from exc
        item = None
        if isinstance(payload, dict):
            listed = payload.get('meeting_info_list')
            if isinstance(listed, list) and listed and isinstance(listed[0], dict):
                item = listed[0]
            elif payload.get('meeting_id'):
                item = payload
        if not item or str(item.get('meeting_id')) != str(meeting_id):
            raise MeetingError('RESOURCE_NOT_ACCESSIBLE', 404)
        if raw:
            return item
        projected = self._project(connection, item)
        if projected is None:
            raise MeetingError('RESOURCE_NOT_ACCESSIBLE', 404)
        return projected

    async def _scan_history(self, connection, operator, body, heartbeat=None):
        seen = set()
        found = []
        intervals = list(windows(body.start_at, body.end_at, 90))
        for begin, stop in intervals:
            page = 1
            while page <= 100000:
                payload = await self.rt.tencent.call(connection.id, 'history', operator, query={
                    'start_time': begin, 'end_time': stop, 'page': page, 'page_size': 20}, heartbeat=heartbeat)
                items = payload.get('meeting_info_list') if isinstance(payload, dict) else None
                total = payload.get('total_page') if isinstance(payload, dict) else None
                if not isinstance(items, list) or not isinstance(total, int):
                    logger.warning(
                        'q1.meeting_queries_failed connection_id=%s selection=USER_WINDOW step=history '
                        'reason=UPSTREAM_CONTRACT_ERROR kind=page_shape page=%s',
                        connection.id, page)
                    raise UpstreamError('UPSTREAM_CONTRACT_ERROR')
                if not items and page < total:
                    logger.warning(
                        'q1.meeting_queries_failed connection_id=%s selection=USER_WINDOW step=history '
                        'reason=UPSTREAM_CONTRACT_ERROR kind=empty_before_last page=%s total_page=%s',
                        connection.id, page, total)
                    raise UpstreamError('UPSTREAM_CONTRACT_ERROR')
                for item in items:
                    if not isinstance(item, dict) or not item.get('meeting_id'):
                        continue
                    ident = str(item['meeting_id'])
                    if ident in seen:
                        continue
                    seen.add(ident)
                    found.append(item)
                if page >= total or total == 0:
                    break
                page += 1
            else:
                raise UpstreamError('UPSTREAM_CONTRACT_ERROR')
        return found

    async def _history(self, job, lease_token, principal, connection, operator, body):
        found = await self._scan_history(connection, operator, body,
                                         heartbeat=lambda: self.rt.jobs.heartbeat(job.id, lease_token))
        async with self.rt.db.transaction() as s:
            await self.rt.jobs.fence(s, job.id, lease_token)
            for item in found:
                await self.rt.meetings.upsert(s, connection, item, purpose='MEMBER_HISTORY',
                                              owner_member_id=principal.member_id, history=True)
        await self._remember(job.id, lease_token, {'complete': True, 'pages': 1, 'meeting_count': len(found)})

    async def _recordings(self, job, lease_token, principal, connection, operator, body):
        start = int(body.start_at.timestamp()) if body.start_at else int((utcnow() - timedelta(days=1)).timestamp())
        end = int(body.end_at.timestamp()) if body.end_at else int(utcnow().timestamp())
        if end <= start:
            end = start + 60
        page = 1
        found = 0
        while page <= 100000:
            raw = await self.rt.tencent.call(connection.id, 'records', operator, query={
                'start_time': start, 'end_time': end, 'page': page, 'page_size': 20, 'meeting_id': body.meeting_id},
                heartbeat=lambda: self.rt.jobs.heartbeat(job.id, lease_token))
            rows = raw.get('record_meetings') if isinstance(raw, dict) else None
            total = raw.get('total_page') if isinstance(raw, dict) else None
            if not isinstance(rows, list) or not isinstance(total, int):
                raise UpstreamError('UPSTREAM_CONTRACT_ERROR')
            async with self.rt.db.transaction() as s:
                await self.rt.jobs.fence(s, job.id, lease_token)
                for item in rows:
                    if isinstance(item, dict) and item.get('meeting_id'):
                        await self.rt.meetings.upsert(s, connection, item, purpose='USER', owner_member_id=principal.member_id)
                        found += len(item.get('record_files') or [])
            if page >= total or total == 0:
                break
            page += 1
        await self._remember(job.id, lease_token, {'complete': True, 'pages': page, 'recording_count': found,
                                                    'upstream_empty': found == 0})
