import json
from datetime import timedelta
import pytest
from sqlalchemy import select
from app.core.errors import MeetingError
from app.core.security import canonical
from app.core.types import utcnow
from app.models import EventInbox,EventOutbox,SyncJob,Subscription,DeliveredResource,AccessGrant
from app.integrations.tencent_meeting.webhook import encrypt_fixture,callback_signature
from test_admin_connections import prepare
from test_resources_jobs import seed


def callback(body,key,token='callback-token-test'):
    encrypted=encrypt_fixture(canonical(body),key)
    timestamp='1750000000000';nonce='nonce'
    return encrypted,{'timestamp':timestamp,'nonce':nonce,'signature':callback_signature(token,timestamp,nonce,encrypted)}


async def test_webhook_exact_challenge_and_replay_dedup(rt,human,enterprise_app_body):
    a,c=await prepare(rt,human,enterprise_app_body)
    text=encrypt_fixture(b'raw-verification-value',enterprise_app_body.webhook_encoding_key)
    headers={'timestamp':'1750000000000','nonce':'n','signature':callback_signature('callback-token-test','1750000000000','n',text)}
    assert await rt.events.challenge(a['receiver_id'],text,headers)==b'raw-verification-value'
    data,h=callback({'event':'recording.completed','trace_id':'same-event','payload':[]},enterprise_app_body.webhook_encoding_key)
    first=await rt.events.receive(a['receiver_id'],data,h)
    second=await rt.events.receive(a['receiver_id'],data,h)
    assert first==second
    async with rt.db.session() as s:
        assert len(list((await s.execute(select(EventInbox))).scalars()))==1
        assert len(list((await s.execute(select(SyncJob))).scalars()))==1


async def test_forged_callback_not_persisted(rt,human,enterprise_app_body):
    a,c=await prepare(rt,human,enterprise_app_body)
    data,h=callback({'event':'common.sts-token','payload':[]},enterprise_app_body.webhook_encoding_key)
    h['signature']='bad'
    with pytest.raises(MeetingError):await rt.events.receive(a['receiver_id'],data,h)
    async with rt.db.session() as s:assert not list((await s.execute(select(EventInbox))).scalars())


async def test_sts_worker_no_sensitive_payload_in_summary(rt,human,enterprise_app_body):
    a,c=await prepare(rt,human,enterprise_app_body)
    rt._provider.response={'sts':{'req_id':'request-from-api'}}
    await rt.connections.request_sts(human,c['id'])
    body={'event':'common.sts-token','trace_id':'sts-event','payload':[{'operate_time':1750000000000,
        'operator':{'userid':'external-m1'},'token_info':{'req_id':'request-from-api','sts_token':'sensitive-ticket-never-log',
        'expire_ts':int((utcnow()+timedelta(hours=6)).timestamp())}}]}
    data,h=callback(body,enterprise_app_body.webhook_encoding_key)
    inbox=await rt.events.receive(a['receiver_id'],data,h)
    job=await rt.jobs.claim('event-worker')
    await rt.events.process_inbox(job,job.lease_token)
    assert await rt.connections.sts_token(c['id'])=='sensitive-ticket-never-log'
    async with rt.db.session() as s:
        row=await s.get(EventInbox,inbox)
        assert row.encrypted_payload is None and 'sensitive-ticket' not in str(row.safe_summary)


async def test_outbox_same_transaction_and_no_title_or_body(rt,human,enterprise_app_body):
    a,c,p,sp=await seed(rt,human,enterprise_app_body)
    async with rt.db.transaction() as s:
        s.add(Subscription(id='subscription',org_id='o1',client_id='employee-client',member_id='m1',
            destination='https://notify.example.org/events',secret_ciphertext=rt.keys.encrypt('notification-key','subscription:o1:subscription'),
            event_types=['meeting.synced'],enabled=True))
    with pytest.raises(RuntimeError):
        async with rt.db.transaction() as s:
            await rt.events.publish('meeting.synced','o1','meeting1',{'subject':'PRIVATE TITLE','body':'PRIVATE BODY'},session=s)
            raise RuntimeError('rollback')
    async with rt.db.session() as s:assert not list((await s.execute(select(EventOutbox))).scalars())
    async with rt.db.transaction() as s:
        await rt.events.publish('meeting.synced','o1','meeting1',{'version':2,'subject':'PRIVATE TITLE'},session=s)
    async with rt.db.session() as s:
        out=await s.scalar(select(EventOutbox))
        assert 'PRIVATE' not in str(out.payload) and out.payload['resource_id']=='meeting1'
    async with rt.db.session() as s:
        sub=await s.get(Subscription,'subscription')
        assert await rt.events.can_deliver(s,sub,'meeting.synced','meeting1')
    async with rt.db.transaction() as s:(await s.get(AccessGrant,'ingestion')).enabled=False
    async with rt.db.session() as s:
        sub=await s.get(Subscription,'subscription')
        assert not await rt.events.can_deliver(s,sub,'meeting.synced','meeting1')


async def test_invalidation_only_for_previously_delivered_id(rt,human,enterprise_app_body):
    a,c,p,sp=await seed(rt,human,enterprise_app_body)
    async with rt.db.transaction() as s:
        sub=Subscription(id='subscription',org_id='o1',client_id='employee-client',member_id='m1',destination='https://notify.example.org/events',
            secret_ciphertext='cipher',event_types=['meeting.resource.invalidated'],enabled=True);s.add(sub)
        s.add(DeliveredResource(org_id='o1',subscription_id=sub.id,resource_id='previously-seen',last_delivered_at=utcnow()))
    async with rt.db.session() as s:
        sub=await s.get(Subscription,'subscription')
        assert await rt.events.can_deliver(s,sub,'meeting.resource.invalidated','previously-seen')
        assert not await rt.events.can_deliver(s,sub,'meeting.resource.invalidated','never-seen')
