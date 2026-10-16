"""Durable at-least-once read jobs with leases/fencing; uncertain writes are never retried."""
from datetime import timedelta
import random
import uuid
from sqlalchemy import select, or_, and_
from app.core.errors import MeetingError
from app.core.types import utcnow, Principal
from app.core.security import canonical
from app.models import SyncJob, Operation
from app.services.audit_service import record

RETRYABLE=frozenset({'RATE_LIMITED','UPSTREAM_UNAVAILABLE','STS_NOT_READY','CONTENT_NOT_READY',
                    'CONTENT_CHANGED','IDENTITY_SERVICE_UNAVAILABLE'})


class JobService:
    def __init__(self,runtime):self.rt=runtime

    async def enqueue(self,s,kind,principal,payload,*,connection_id=None,ingestion_grant_id=None,dedup_key=None,run_after=None):
        if kind not in {'SYNC','CONTENT','INGEST_CONTENT','CREATE','INBOX','OUTBOX','SOURCE_QUERY'} or len(canonical(payload))>65536:
            raise MeetingError('INVALID_REQUEST',422)
        if dedup_key:
            old=await s.scalar(select(SyncJob).where(SyncJob.dedup_key==dedup_key,SyncJob.deleted_at.is_(None)))
            if old:return old
        job=SyncJob(org_id=principal.org_id,kind=kind,connection_id=connection_id,owner_member_id=principal.member_id,
            client_id=principal.client_id,agent_grant_id=principal.agent_grant_id,ingestion_grant_id=ingestion_grant_id,
            principal_data=principal.model_dump(mode='json'),payload=payload,progress={},dedup_key=dedup_key,
            state='PENDING',attempts=0,run_after=run_after or utcnow())
        s.add(job);await s.flush();record(s,principal,'job.enqueued',resource_id=job.id)
        return job

    async def claim(self,worker_id):
        if not worker_id or len(worker_id)>64:raise ValueError('Worker ID invalid')
        async with self.rt.db.lock('jobs:claim'),self.rt.db.transaction() as s:
            now=utcnow()
            query=select(SyncJob).where(SyncJob.deleted_at.is_(None),or_(
                and_(SyncJob.state.in_(['PENDING','RETRYING']),SyncJob.run_after<=now),
                and_(SyncJob.state=='PROCESSING',SyncJob.lease_until<=now))).order_by(SyncJob.run_after,SyncJob.id).with_for_update(skip_locked=True).limit(20)
            rows=list((await s.execute(query)).scalars())
            for job in rows:
                if job.kind=='CREATE' and job.state=='PROCESSING':
                    op=await s.get(Operation,job.payload.get('operation_id'))
                    if op and op.state in {'EXECUTING','APPROVED','QUEUED'}:
                        op.state='OUTCOME_UNKNOWN';op.last_reason='OUTCOME_UNKNOWN'
                    job.state='FAILED';job.last_reason='OUTCOME_UNKNOWN';continue
                if job.attempts>=self.rt.settings.job_max_attempts:
                    job.state='FAILED';continue
                job.state='PROCESSING';job.attempts+=1;job.lease_owner=worker_id;job.lease_token=str(uuid.uuid4())
                job.lease_until=now+timedelta(seconds=self.rt.settings.worker_lease_seconds)
                await s.flush();return job
        return None

    async def fence(self,s,job_id,lease_token):
        job=await s.get(SyncJob,job_id,with_for_update=True)
        if not job or job.state!='PROCESSING' or job.lease_token!=lease_token or not job.lease_until or job.lease_until<=utcnow():
            raise MeetingError('CONFLICT',409)
        return job

    async def heartbeat(self,job_id,lease_token):
        async with self.rt.db.transaction() as s:
            try:job=await self.fence(s,job_id,lease_token)
            except MeetingError:return False
            job.lease_until=utcnow()+timedelta(seconds=self.rt.settings.worker_lease_seconds)
            return True

    async def checkpoint(self,job_id,lease_token,progress):
        async with self.rt.db.transaction() as s:
            job=await self.fence(s,job_id,lease_token);job.progress=progress

    async def finish(self,job_id,lease_token):
        async with self.rt.db.transaction() as s:
            try:job=await self.fence(s,job_id,lease_token)
            except MeetingError:return False
            job.state='SUCCEEDED';job.lease_until=None;job.last_reason=None
            self.rt.metrics['jobs_succeeded']+=1
            return True

    async def fail(self,job_id,lease_token,error):
        async with self.rt.db.transaction() as s:
            try:job=await self.fence(s,job_id,lease_token)
            except MeetingError:return False
            reason=error.reason if isinstance(error,MeetingError) else 'INTERNAL_ERROR'
            if isinstance(error,MeetingError) and not error.budgeted:
                job.attempts=max(0,job.attempts-1)
                job.state='RETRYING'
                job.run_after=utcnow()+timedelta(seconds=max(1,error.retry_after or 1))
                job.last_reason=reason;job.lease_until=None
                record(s,Principal.model_validate(job.principal_data),'job.deferred',resource_id=job.id,decision='ALLOW',reason=reason)
                return True
            retry=job.kind!='CREATE' and reason in RETRYABLE and job.attempts<self.rt.settings.job_max_attempts
            delay=max(getattr(error,'retry_after',0) or 0,min(3600,2**min(job.attempts,10)+random.randint(0,5)))
            job.state='RETRYING' if retry else 'FAILED';job.run_after=utcnow()+timedelta(seconds=delay)
            job.last_reason=reason;job.lease_until=None
            record(s,Principal.model_validate(job.principal_data),'job.failed',resource_id=job.id,decision='DENY',reason=reason)
            self.rt.metrics['jobs_failed']+=1
            return True

    async def get(self,principal,job_id):
        async with self.rt.db.session() as s:
            row=await self.rt.admin._get(s,SyncJob,principal.org_id,job_id)
            own=(row.client_id==principal.client_id and row.owner_member_id==principal.member_id
                 and row.agent_grant_id==principal.agent_grant_id)
            if principal.portal:
                await self.rt.admin.require(s,principal,'meeting.sync.manage')
            elif not own:raise MeetingError('RESOURCE_NOT_ACCESSIBLE',404)
            if not principal.portal:await self.rt.auth.revalidate(principal)
            return self.info(row)

    def info(self,row):
        return {'id':row.id,'kind':row.kind,'state':row.state,'attempts':row.attempts,
                'run_after':row.run_after,'progress':row.progress,'last_reason':row.last_reason,'created_at':row.created_at}

    async def retry(self,principal,job_id):
        async with self.rt.db.lock('job:'+job_id),self.rt.db.transaction() as s:
            await self.rt.admin.require(s,principal,'meeting.sync.manage')
            job=await self.rt.admin._get(s,SyncJob,principal.org_id,job_id)
            if job.kind=='CREATE' or job.state!='FAILED':raise MeetingError('CONFLICT',409)
            # Stored actor/grants are still revalidated by execution; admin cannot replace the owner.
            job.state='PENDING';job.attempts=0;job.run_after=utcnow();job.lease_token=None
            record(s,principal,'job.retry_requested',resource_id=job.id)
            return self.info(job)
