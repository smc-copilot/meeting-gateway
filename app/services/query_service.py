"""Source lookup is separate from the local catalogue. A miss stores nothing about the meeting."""
from datetime import timedelta
from app.core.errors import MeetingError, UpstreamError
from app.core.types import Principal, utcnow
from app.schemas.requests import MeetingQuery
from app.services.audit_service import record


class QueryService:
    def __init__(self, runtime):
        self.rt = runtime

    async def submit(self, principal, body: MeetingQuery):
        if body.selection == 'CORP_WINDOW':
            raise MeetingError('PERMISSION_DENIED', 403)
        p = await self.rt.auth.revalidate(principal)
        if p.actor_type != 'MEMBER' or not p.member_id:
            raise MeetingError('PERMISSION_DENIED', 403)
        c, _app = await self.rt.connections.owned(p, body.connection_ref)
        if c.kind != 'THIRD_PARTY_OAUTH' or c.member_id != p.member_id:
            raise MeetingError('PERMISSION_DENIED', 403)
        if body.selection == 'USER_WINDOW':
            if body.target_member_id != p.member_id or body.start_at is None or body.end_at is None or body.start_at >= body.end_at:
                raise MeetingError('PERMISSION_DENIED', 403) if body.target_member_id != p.member_id else MeetingError('INVALID_REQUEST', 422)
        elif not body.meeting_id:
            raise MeetingError('INVALID_REQUEST', 422)
        async with self.rt.db.transaction() as s:
            await self.rt.policy.require(s, p, 'meeting.read', connection_id=c.id)
            payload = body.model_dump(mode='json')
            job = await self.rt.jobs.enqueue(s, 'SOURCE_QUERY', p, payload, connection_id=c.id)
            record(s, p, 'meeting.query.accepted', resource_id=job.id)
            return {'accepted': True, 'job_id': job.id, 'selection': body.selection}

    async def run(self, job, lease_token):
        body = MeetingQuery.model_validate(job.payload)
        if body.selection == 'CORP_WINDOW':
            raise MeetingError('PERMISSION_DENIED', 403)
        p = await self.rt.auth.revalidate(Principal.model_validate(job.principal_data))
        c, _app = await self.rt.connections.owned(p, job.connection_id)
        if c.kind != 'THIRD_PARTY_OAUTH' or c.member_id != p.member_id:
            raise MeetingError('PERMISSION_DENIED', 403)
        operator = await self.rt.connections.operator(c, member_id=p.member_id)
        async with self.rt.db.session() as s:
            await self.rt.jobs.fence(s, job.id, lease_token)
            await self.rt.policy.require(s, p, 'meeting.read', connection_id=c.id)
        await self.rt.tencent.admit(c.id, 'history' if body.selection == 'USER_WINDOW' else 'meeting',
                                    heartbeat=lambda: self.rt.jobs.heartbeat(job.id, lease_token))
        if body.selection == 'USER_WINDOW':
            raw = await self.rt.tencent.call(c.id, 'history', operator, query={
                'start_time': int(body.start_at.timestamp()), 'end_time': int(body.end_at.timestamp()),
                'page': 1, 'page_size': 20}, admitted=True)
            items = raw.get('meeting_info_list') if isinstance(raw, dict) else None
            if not isinstance(items, list):
                raise UpstreamError('UPSTREAM_CONTRACT_ERROR')
            async with self.rt.db.transaction() as s:
                for item in items:
                    if isinstance(item, dict) and item.get('meeting_id'):
                        await self.rt.meetings.upsert(s, c, item, purpose='MEMBER_HISTORY', owner_member_id=p.member_id, history=True)
            return
        try:
            raw = await self.rt.tencent.call(c.id, 'meeting', operator, file_id=body.meeting_id, admitted=True)
        except MeetingError as exc:
            if exc.reason == 'RESOURCE_NOT_ACCESSIBLE':
                raise
            raise MeetingError('RESOURCE_NOT_ACCESSIBLE', 404) from exc
        item = None
        if isinstance(raw, dict):
            listed = raw.get('meeting_info_list')
            if isinstance(listed, list) and listed and isinstance(listed[0], dict):
                item = listed[0]
            elif raw.get('meeting_id'):
                item = raw
        if not item or str(item.get('meeting_id')) != str(body.meeting_id):
            raise MeetingError('RESOURCE_NOT_ACCESSIBLE', 404)
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
            job = await self.rt.jobs.enqueue(s, 'SOURCE_QUERY', p, payload, connection_id=c.id, dedup_key='ensure-meeting:' + row.id)
            return job.id
