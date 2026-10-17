"""Durable create journal: prepare -> human confirmation -> one upstream attempt.

An unknown result can only be linked to a separately verified, exactly matching
local meeting or closed unresolved. Closing never asserts the upstream write failed.
"""
import asyncio
from datetime import timedelta
import uuid
from sqlalchemy import select
from app.core.errors import MeetingError, UpstreamError
from app.core.security import canonical, digest
from app.core.types import Principal, utcnow
from app.models import Operation, SyncJob, Meeting, Client
from app.schemas.requests import MeetingCreate
from app.services.audit_service import record


class OperationService:
    def __init__(self, runtime):
        self.rt = runtime

    async def _parameters(self, principal, body):
        if not self.rt.settings.meeting_create_enabled:
            raise MeetingError('FEATURE_DISABLED', 403)
        p = await self.rt.auth.revalidate(principal)
        if p.actor_type == 'SERVICE' or not p.member_id:
            raise MeetingError('PERMISSION_DENIED', 403)
        if body.start_at <= utcnow() or len(body.subject.encode('utf-16-le')) > 512:
            raise MeetingError('INVALID_REQUEST', 422)
        if body.host_member_id != p.member_id:
            raise MeetingError('PERMISSION_DENIED', 403)
        c, app = await self.rt.connections.owned(p, body.connection_ref)
        if c.member_id != p.member_id or c.kind not in {'THIRD_PARTY_OAUTH', 'ENTERPRISE_AKSK'}:
            raise MeetingError('PERMISSION_DENIED', 403)
        async with self.rt.db.session() as s:
            await self.rt.policy.require(s, p, 'meeting.create.self', target_member_id=p.member_id, connection_id=c.id)
            client = await s.get(Client, p.client_id)
        policy = client.create_policy if client and client.create_policy else 'HUMAN_CONFIRM'
        if policy == 'APPROVED_SERVICE' or p.actor_type == 'SERVICE':
            raise MeetingError('PERMISSION_DENIED', 403)
        operator = await self.rt.connections.operator(c, member_id=p.member_id)
        invitees = []
        for member in sorted(body.invitee_member_ids):
            who = await self.rt.connections.invitee(c, member)
            invitees.append({'userid': who.id})
        if body.auto_record_type == 'CLOUD' and not self.rt.settings.meeting_auto_record_enabled:
            raise MeetingError('AUTO_RECORD_DISABLED', 403)
        wire = {'subject': body.subject, 'userid': operator.id, 'instanceid': 1, 'type': 0,
                'meeting_type': 0, 'start_time': str(int(body.start_at.timestamp())),
                'end_time': str(int(body.end_at.timestamp())), 'invitees': invitees,
                'settings': {'auto_record_type': 'none' if body.auto_record_type == 'NONE' else 'cloud'}}
        normalized = body.model_dump(mode='json')
        normalized['start_at'] = int(body.start_at.timestamp())
        normalized['end_at'] = int(body.end_at.timestamp())
        normalized['invitee_member_ids'] = sorted(body.invitee_member_ids)
        request_hash = digest(canonical({'request': normalized, 'wire': wire, 'connection': c.id}))
        return p, c, operator, wire, request_hash

    def info(self, row, job_id=None):
        return {'id': row.id, 'state': row.state, 'request_hash': row.request_hash,
                'request': row.request_data, 'confirm_deadline': row.confirm_deadline,
                'approved_at': row.approved_at, 'meeting_id': row.result_meeting_id,
                'last_reason': row.last_reason, 'created_at': row.created_at,
                'resolution_note': row.resolution_note, 'job_id': job_id}

    async def _owned(self, s, p, ident):
        row = await self.rt.admin._get(s, Operation, p.org_id, ident)
        if p.portal:
            await self.rt.admin.human(p)
            own = row.owner_member_id == p.member_id
        else:
            own = (row.owner_member_id == p.member_id and row.client_id == p.client_id
                   and row.agent_grant_id == p.agent_grant_id)
        if not own:
            raise MeetingError('RESOURCE_NOT_ACCESSIBLE', 404)
        return row

    async def prepare(self, principal, body: MeetingCreate, idempotency_key):
        if not isinstance(idempotency_key, str) or not 1 <= len(idempotency_key) <= 128:
            raise MeetingError('INVALID_REQUEST', 422)
        p, c, operator, wire, request_hash = await self._parameters(principal, body)
        # REST/MCP audience is not part of business idempotency; credentials themselves remain audience-bound.
        scope = digest(canonical([p.org_id, p.client_id, p.actor_type, p.member_id, p.agent_grant_id, 'meeting.create']))
        key_hash = digest(idempotency_key)
        async with self.rt.db.lock('create-idempotency:' + scope + key_hash), self.rt.db.transaction() as s:
            old = await s.scalar(select(Operation).where(Operation.idempotency_scope == scope,
                Operation.idempotency_key_hash == key_hash, Operation.deleted_at.is_(None)))
            if old:
                if old.request_hash != request_hash:
                    raise MeetingError('IDEMPOTENCY_CONFLICT', 409)
                return self.info(old)
            version = await self.rt.policy.policy_version(s, p.org_id)
            client = await s.get(Client, p.client_id)
            policy = client.create_policy if client and client.create_policy else 'HUMAN_CONFIRM'
            trusted = policy == 'TRUSTED_MEMBER' and p.actor_type == 'MEMBER'
            row = Operation(org_id=p.org_id, owner_member_id=p.member_id, client_id=p.client_id,
                agent_grant_id=p.agent_grant_id, connection_id=c.id, host_member_id=body.host_member_id,
                idempotency_scope=scope, idempotency_key_hash=key_hash, request_hash=request_hash,
                request_data=body.model_dump(mode='json'), principal_data=p.model_dump(mode='json'),
                operator_data=operator.model_dump(), state='QUEUED' if trusted else 'AWAITING_CONFIRMATION',
                policy_version=version, approved_by=p.member_id if trusted else None,
                approved_at=utcnow() if trusted else None,
                confirm_deadline=utcnow()+timedelta(seconds=self.rt.settings.confirmation_seconds))
            s.add(row)
            await s.flush()
            job_id = None
            if trusted:
                job = await self.rt.jobs.enqueue(s, 'CREATE', p, {'operation_id': row.id},
                                                connection_id=c.id, dedup_key='create:' + row.id)
                job_id = job.id
            record(s, p, 'meeting.create.queued' if trusted else 'meeting.create.prepared', resource_id=row.id)
            return self.info(row, job_id)

    async def get(self, principal, ident):
        p = await self.rt.auth.revalidate(principal) if not principal.portal else principal
        async with self.rt.db.session() as s:
            row = await self._owned(s, p, ident)
            job = await s.scalar(select(SyncJob).where(SyncJob.dedup_key == 'create:' + row.id,
                                                     SyncJob.deleted_at.is_(None)))
            return self.info(row, job.id if job else None)

    async def list(self, principal, limit=50):
        await self.rt.admin.human(principal)
        async with self.rt.db.session() as s:
            rows = (await s.execute(select(Operation).where(Operation.org_id == principal.org_id,
                Operation.owner_member_id == principal.member_id, Operation.deleted_at.is_(None))
                .order_by(Operation.created_at.desc()).limit(min(max(limit, 1), 100)))).scalars()
            return {'items': [self.info(row) for row in rows]}

    async def confirm(self, human, ident, expected_hash):
        await self.rt.admin.human(human)
        return await self._confirm(human, ident, expected_hash)

    async def confirm_business(self, principal, ident, expected_hash):
        if principal.actor_type != 'MEMBER' or not principal.member_id:
            raise MeetingError('PERMISSION_DENIED', 403)
        return await self._confirm(await self.rt.auth.revalidate(principal), ident, expected_hash)

    async def _confirm(self, actor, ident, expected_hash):
        async with self.rt.db.lock('operation:' + ident), self.rt.db.transaction() as s:
            row = await self._owned(s, actor, ident)
            if expected_hash != row.request_hash:
                raise MeetingError('CONFLICT', 409)
            if row.state in {'QUEUED', 'EXECUTING', 'SUCCEEDED', 'OUTCOME_UNKNOWN'}:
                job = await s.scalar(select(SyncJob).where(SyncJob.dedup_key == 'create:' + row.id))
                return self.info(row, job.id if job else None)
            if row.state == 'OPERATION_EXPIRED' or (row.state == 'AWAITING_CONFIRMATION' and row.confirm_deadline <= utcnow()):
                row.state = 'OPERATION_EXPIRED'
                row.last_reason = 'OPERATION_EXPIRED'
                raise MeetingError('OPERATION_EXPIRED', 409)
            if row.state != 'AWAITING_CONFIRMATION':
                raise MeetingError('CONFLICT', 409)
            if row.policy_version != await self.rt.policy.policy_version(s, actor.org_id):
                raise MeetingError('AUTHORIZATION_CHANGED', 409)
            stored = Principal.model_validate(row.principal_data)
            p, c, operator, wire, current_hash = await self._parameters(stored, MeetingCreate.model_validate(row.request_data))
            if current_hash != row.request_hash or operator.model_dump() != row.operator_data:
                raise MeetingError('AUTHORIZATION_CHANGED', 409)
            row.state = 'QUEUED'
            row.approved_by = actor.member_id
            row.approved_at = utcnow()
            job = await self.rt.jobs.enqueue(s, 'CREATE', p, {'operation_id': row.id},
                                            connection_id=c.id, dedup_key='create:' + row.id)
            record(s, actor, 'meeting.create.confirmed', resource_id=row.id)
            return self.info(row, job.id)

    async def reject(self, human, ident, reason):
        await self.rt.admin.human(human)
        return await self._reject(human, ident, reason)

    async def reject_business(self, principal, ident, reason):
        if principal.actor_type != 'MEMBER' or not principal.member_id:
            raise MeetingError('PERMISSION_DENIED', 403)
        return await self._reject(await self.rt.auth.revalidate(principal), ident, reason)

    async def _reject(self, actor, ident, reason):
        async with self.rt.db.lock('operation:' + ident), self.rt.db.transaction() as s:
            row = await self._owned(s, actor, ident)
            if row.state not in {'AWAITING_CONFIRMATION', 'QUEUED'}:
                raise MeetingError('CONFLICT', 409)
            row.state = 'REJECTED'
            row.resolution_note = reason[:500]
            record(s, actor, 'meeting.create.rejected', resource_id=row.id)
            return self.info(row)

    async def _terminal(self, ident, attempt, state, reason, principal):
        async with self.rt.db.transaction() as s:
            row = await s.get(Operation, ident, with_for_update=True)
            if row.execution_attempt_id != attempt or row.state == 'SUCCEEDED':
                return
            row.state, row.last_reason = state, reason
            record(s, principal, 'meeting.create.' + state.lower(), resource_id=row.id,
                   decision='DENY', reason=reason)
            if state == 'OUTCOME_UNKNOWN':
                await self.rt.events.publish('meeting.create.unknown', row.org_id, row.id, {'state': state}, session=s)

    async def execute(self, job_id, lease_token):
        async with self.rt.db.session() as s:
            job = await s.get(SyncJob, job_id)
            if not job or job.kind != 'CREATE':
                raise MeetingError('CONFLICT', 409)
            ident = job.payload['operation_id']
        async with self.rt.db.lock('operation:' + ident):
            async with self.rt.db.session() as s:
                row = await s.get(Operation, ident)
                if row.state != 'QUEUED':
                    return
                actor = Principal.model_validate(row.principal_data)
            attempt = None
            try:
                p, c, operator, wire, request_hash = await self._parameters(actor, MeetingCreate.model_validate(row.request_data))
                await self.rt.tencent.admit(c.id, 'create', heartbeat=lambda: self.rt.jobs.heartbeat(job_id, lease_token))
                async with self.rt.db.transaction() as s:
                    await self.rt.jobs.fence(s, job_id, lease_token)
                    row = await s.get(Operation, ident, with_for_update=True)
                    if row.state != 'QUEUED':
                        return
                    if not row.approved_by or request_hash != row.request_hash or operator.model_dump() != row.operator_data:
                        raise MeetingError('AUTHORIZATION_CHANGED', 409)
                    if row.policy_version != await self.rt.policy.policy_version(s, row.org_id):
                        raise MeetingError('AUTHORIZATION_CHANGED', 409)
                    attempt = str(uuid.uuid4())
                    row.execution_attempt_id = attempt
                    row.attempt_started_at = utcnow()
                    row.state = 'EXECUTING'
                    record(s, p, 'meeting.create.started', resource_id=row.id)
                # No automatic transport retry is allowed beyond this durable journal point.
                raw = await self.rt.tencent.call(c.id, 'create', operator, body=wire, admitted=True)
                values = raw.get('meeting_info_list')
                if not isinstance(values, list) or len(values) != 1 or not isinstance(values[0], dict) or not values[0].get('meeting_id'):
                    raise UpstreamError('UPSTREAM_CONTRACT_ERROR', uncertain=True)
                value = values[0]
                # Preserve only known metadata; password, host key and joining tokens are deliberately dropped.
                safe = {key: value[key] for key in ('meeting_id', 'meeting_code', 'subject', 'start_time', 'end_time') if key in value}
                safe.setdefault('subject', wire['subject'])
                safe.setdefault('start_time', wire['start_time'])
                safe.setdefault('end_time', wire['end_time'])
                async with self.rt.db.transaction() as s:
                    current = await s.get(Operation, ident, with_for_update=True)
                    if current.execution_attempt_id != attempt:
                        raise MeetingError('CONFLICT', 409)
                    # A conclusive response from this exact journaled attempt remains evidence even if a job lease expired.
                    meeting = await self.rt.meetings.upsert(s, c, safe, purpose='CREATED',
                        owner_member_id=current.host_member_id, created_host=current.host_member_id)
                    current.state = 'SUCCEEDED'
                    current.external_meeting_id = str(value['meeting_id'])
                    current.result_meeting_id = meeting.id
                    current.last_reason = None
                    record(s, p, 'meeting.create.succeeded', resource_id=current.id)
                    await self.rt.events.publish('meeting.create.succeeded', current.org_id, current.id,
                                                 {'state': current.state}, session=s)
                await self.rt.jobs.finish(job_id, lease_token)
            except asyncio.CancelledError:
                if attempt:
                    await asyncio.shield(self._terminal(ident, attempt, 'OUTCOME_UNKNOWN', 'OUTCOME_UNKNOWN', actor))
                raise
            except Exception as exc:
                if attempt is None and isinstance(exc, MeetingError) and not exc.budgeted:
                    await self.rt.jobs.fail(job_id, lease_token, exc)
                    return
                reason = exc.reason if isinstance(exc, MeetingError) else 'INTERNAL_ERROR'
                uncertain = attempt is not None and (not isinstance(exc, UpstreamError) or exc.uncertain)
                if attempt:
                    await self._terminal(ident, attempt, 'OUTCOME_UNKNOWN' if uncertain else 'FAILED',
                                         'OUTCOME_UNKNOWN' if uncertain else reason, actor)
                else:
                    async with self.rt.db.transaction() as s:
                        current = await s.get(Operation, ident, with_for_update=True)
                        if current.state == 'QUEUED':
                            current.state, current.last_reason = 'FAILED', reason
                            record(s, actor, 'meeting.create.blocked', resource_id=ident, decision='DENY', reason=reason)
                await self.rt.jobs.fail(job_id, lease_token,
                    MeetingError('OUTCOME_UNKNOWN' if uncertain else reason, 502))

    async def reconcile(self, human, ident, *, action, reason, meeting_id=None):
        await self.rt.admin.human(human)
        if action not in {'LINK_VERIFIED_MEETING', 'CLOSE_UNRESOLVED'} or len(reason.strip()) < 3:
            raise MeetingError('INVALID_REQUEST', 422)
        async with self.rt.db.lock('operation:' + ident), self.rt.db.transaction() as s:
            row = await self._owned(s, human, ident)
            if row.state != 'OUTCOME_UNKNOWN':
                raise MeetingError('CONFLICT', 409)
            if action == 'LINK_VERIFIED_MEETING':
                m = await self.rt.admin._get(s, Meeting, human.org_id, meeting_id)
                body = MeetingCreate.model_validate(row.request_data)
                if (m.connection_id != row.connection_id or m.host_member_id != row.host_member_id
                    or m.subject != body.subject or m.start_at != body.start_at.replace(microsecond=0)
                    or m.end_at != body.end_at.replace(microsecond=0) or not m.synced_at
                    or m.synced_at < row.attempt_started_at):
                    raise MeetingError('CONFLICT', 409)
                await self.rt.policy.require(s, human, 'meeting.read', meeting=m)
                row.state, row.result_meeting_id, row.external_meeting_id = 'SUCCEEDED', m.id, m.external_id
                await self.rt.events.publish('meeting.create.succeeded', row.org_id, row.id, {'state': row.state}, session=s)
            else:
                row.state = 'CLOSED_UNRESOLVED'
            row.resolution_note = reason[:500]
            record(s, human, 'meeting.create.reconciled', resource_id=row.id)
            return self.info(row)
