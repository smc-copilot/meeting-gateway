from datetime import timedelta
import asyncio
import pytest
from sqlalchemy import select
from app.schemas.requests import MeetingCreate
from app.core.types import utcnow
from app.core.errors import MeetingError,UpstreamError
from app.models import Operation,SyncJob,AccessGrant,Connection,Application
from test_resources_jobs import seed


async def member_oauth(rt, connection):
    async with rt.db.transaction() as s:
        row = await s.get(Connection, connection['id'])
        app = await s.get(Application, row.application_id)
        app.application_type = 'THIRD_PARTY_OAUTH'
        row.kind = 'THIRD_PARTY_OAUTH'
        row.member_id = 'm1'
    return connection


def request(c):
    start=(utcnow()+timedelta(hours=1)).replace(microsecond=0)
    return MeetingCreate(subject='Review',start_at=start,end_at=start+timedelta(hours=1),host_member_id='m1',connection_ref=c['id'])

async def test_creation_prepare_is_cross_protocol_idempotent(rt,human,enterprise_app_body):
    _,c,p,_=await seed(rt,human,enterprise_app_body);await member_oauth(rt,c);body=request(c)
    rows=await asyncio.gather(*(rt.operations.prepare(p,body,'business-1') for _ in range(12)))
    other=await rt.operations.prepare(p.model_copy(update={'audience':rt.settings.mcp_resource_uri}),body,'business-1')
    assert len({r['id'] for r in rows} | {other['id']})==1
    assert rows[0]['state']=='AWAITING_CONFIRMATION' and not rt.tencent.created
    with pytest.raises(MeetingError,match='IDEMPOTENCY_CONFLICT'):
        await rt.operations.prepare(p,body.model_copy(update={'subject':'Changed'}),'business-1')

async def test_confirm_only_trusted_owner_then_execute_once(rt,human,enterprise_app_body):
    _,c,p,_=await seed(rt,human,enterprise_app_body);await member_oauth(rt,c);op=await rt.operations.prepare(p,request(c),'business-2')
    with pytest.raises(MeetingError):await rt.operations.confirm(p,op['id'],op['request_hash'])
    approved=await rt.operations.confirm(human,op['id'],op['request_hash'])
    again=await rt.operations.confirm(human,op['id'],op['request_hash'])
    assert approved['job_id']==again['job_id']
    job=await rt.jobs.claim('test-worker');assert job.kind=='CREATE'
    await rt.operations.execute(job.id,job.lease_token)
    assert rt.tencent.created==1
    result=await rt.operations.get(p,op['id'])
    assert result['state']=='SUCCEEDED' and result['meeting_id']
    assert 'operator_data' not in result and 'password' not in str(result)
    await rt.operations.execute(job.id,job.lease_token)
    assert rt.tencent.created==1

async def test_confirm_hash_and_policy_changes_block(rt,human,enterprise_app_body):
    _,c,p,_=await seed(rt,human,enterprise_app_body);await member_oauth(rt,c);op=await rt.operations.prepare(p,request(c),'policy-1')
    with pytest.raises(MeetingError,match='CONFLICT'):await rt.operations.confirm(human,op['id'],'0'*64)
    async with rt.db.transaction() as s:await rt.policy.bump(s,'o1')
    with pytest.raises(MeetingError,match='AUTHORIZATION_CHANGED'):
        await rt.operations.confirm(human,op['id'],op['request_hash'])
    assert not rt.tencent.created

async def test_upstream_timeout_unknown_never_retry(rt,human,enterprise_app_body):
    _,c,p,_=await seed(rt,human,enterprise_app_body);await member_oauth(rt,c);op=await rt.operations.prepare(p,request(c),'unknown-1')
    await rt.operations.confirm(human,op['id'],op['request_hash'])
    job=await rt.jobs.claim('test-worker');rt.tencent.error=UpstreamError('UPSTREAM_UNAVAILABLE',uncertain=True)
    await rt.operations.execute(job.id,job.lease_token)
    result=await rt.operations.get(p,op['id']);assert result['state']=='OUTCOME_UNKNOWN'
    calls=len(rt.tencent.calls)
    await rt.operations.execute(job.id,job.lease_token)
    assert len(rt.tencent.calls)==calls
    with pytest.raises(MeetingError):await rt.jobs.retry(human,job.id)

async def test_revocation_between_confirm_and_execution_blocks(rt,human,enterprise_app_body):
    _,c,p,_=await seed(rt,human,enterprise_app_body);await member_oauth(rt,c);op=await rt.operations.prepare(p,request(c),'revoked-1')
    await rt.operations.confirm(human,op['id'],op['request_hash']);job=await rt.jobs.claim('test-worker')
    async with rt.db.transaction() as s:
        grants=list((await s.execute(select(AccessGrant).where(AccessGrant.subject_id=='m1'))).scalars())
        for grant in grants:
            if 'meeting.create.self' in grant.actions:grant.effect='DENY'
        await rt.policy.bump(s,'o1')
    await rt.operations.execute(job.id,job.lease_token)
    assert not rt.tencent.created
    assert (await rt.operations.get(p,op['id']))['state']=='FAILED'

async def test_no_service_creation_no_expired_confirmation(rt,human,enterprise_app_body):
    _,c,p,sp=await seed(rt,human,enterprise_app_body);await member_oauth(rt,c)
    with pytest.raises(MeetingError):await rt.operations.prepare(sp,request(c),'service')
    op=await rt.operations.prepare(p,request(c),'expired')
    async with rt.db.transaction() as s:
        row=await s.get(Operation,op['id']);row.confirm_deadline=utcnow()-timedelta(seconds=1)
    with pytest.raises(MeetingError,match='OPERATION_EXPIRED'):await rt.operations.confirm(human,op['id'],op['request_hash'])
