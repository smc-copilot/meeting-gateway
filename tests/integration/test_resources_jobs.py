from datetime import timedelta
import pytest
from sqlalchemy import select
from app.models import (Meeting,Recording,Asset,ResourceOrigin,AccessGrant,Client,SyncJob,Connection,OrganizationPolicy)
from app.core.types import utcnow,Principal
from app.core.errors import MeetingError
from app.schemas.requests import GrantCreate,SyncRequest
from app.services.permission_service import ALL_ACTIONS
from test_admin_connections import prepare


async def seed(rt,human,enterprise_app_body):
    a,c=await prepare(rt,human,enterprise_app_body)
    async with rt.db.transaction() as s:
        service=Client(id='sync-client',org_id='o1',name='Approved ingestion',client_type='CONFIDENTIAL',owner_member_id='m1',
            secret_hash='not-issued',allow_service=True,allowed_scopes=['meeting.sync.manage'],enabled=True)
        s.add(service)
        s.add(OrganizationPolicy(org_id='o1',approved_by='m1',retention_confirmed=True,reason='test approved'))
        s.add(Client(id='employee-client',org_id='o1',name='Employee app',client_type='CONFIDENTIAL',owner_member_id='m1',
                     secret_hash='not-issued',allow_service=False,allowed_scopes=sorted(ALL_ACTIONS),enabled=True))
        await s.flush()
        ingestion=AccessGrant(id='ingestion',org_id='o1',subject_type='SERVICE',subject_id=service.id,purpose='INGESTION',
            actions=['meeting.sync.manage'],scope_type='ORG_APPROVED',connection_ids=[c['id']],issued_by='m1',reason='approved ingestion')
        s.add(ingestion)
        s.add(AccessGrant(org_id='o1',subject_type='SERVICE',subject_id=service.id,purpose='ACCESS',actions=['meeting.sync.manage'],
            scope_type='ORG_APPROVED',connection_ids=[c['id']],issued_by='m1',reason='sync operation'))
        s.add(AccessGrant(org_id='o1',subject_type='MEMBER',subject_id='m1',purpose='ACCESS',
            actions=['meeting.read','meeting.content.read','meeting.content.download','meeting.create.self'],
            scope_type='ORG_APPROVED',issued_by='m1',reason='test approval'))
        m=Meeting(id='meeting1',org_id='o1',connection_id=c['id'],external_namespace=c['id'],external_id='up-meeting',subject='Visible',
                  host_member_id='m1',state='ENDED',start_at=utcnow()-timedelta(hours=2),end_at=utcnow()-timedelta(hours=1))
        s.add(m);await s.flush()
        rec=Recording(id='record1',org_id='o1',meeting_id=m.id,connection_id=c['id'],external_file_id='file1',
            external_record_id='group1',recording_group_id='group1',state='READY',size_bytes=100)
        s.add(rec);await s.flush()
        s.add(ResourceOrigin(org_id='o1',meeting_id=m.id,connection_id=c['id'],purpose='INGESTION',ingestion_grant_id=ingestion.id,enabled=True))
    p=human.model_copy(update={'portal':False,'client_id':'employee-client','audience':rt.settings.rest_resource_uri})
    servicep=Principal(org_id='o1',client_id='sync-client',actor_type='SERVICE',scopes=frozenset({'meeting.sync.manage'}),
                       audience=rt.settings.rest_resource_uri)
    return a,c,p,servicep


async def test_visible_before_pagination_and_resource_nonleak(rt,human,enterprise_app_body):
    a,c,p,sp=await seed(rt,human,enterprise_app_body)
    async with rt.db.transaction() as s:
        s.add(Meeting(id='aaa',org_id='other',connection_id=c['id'],external_namespace='else',external_id='hidden',subject='SECRET'))
    result=await rt.meetings.list(p,limit=1)
    assert [i['id'] for i in result['items']]==['meeting1'] and 'SECRET' not in str(result)
    with pytest.raises(MeetingError) as e:await rt.meetings.get(p,'aaa')
    assert e.value.status==404


async def test_cache_read_still_checks_current_origin_and_action(rt,human,enterprise_app_body):
    a,c,p,sp=await seed(rt,human,enterprise_app_body)
    rt._provider.response={'minutes':{'meeting_minute':{'minute':'# Meeting notes','todo':''}}}
    asset=await rt.content.fetch(p,'record1','minutes')
    result=await rt.content.read(p,'record1','minutes')
    assert result['content']['minute']=='# Meeting notes' and result['is_complete']
    assert asset['asset_type']=='minutes'
    async with rt.db.transaction() as s:(await s.get(AccessGrant,'ingestion')).enabled=False
    with pytest.raises(MeetingError):await rt.content.read(p,'record1','minutes')


async def test_transcript_full_inclusive_pagination(rt,human,enterprise_app_body):
    a,c,p,sp=await seed(rt,human,enterprise_app_body)
    def paragraph(pid,text):return {'pid':pid,'sentences':[{'words':[{'text':text}]}]}
    one=paragraph('opaque-a','Hello');two=paragraph('opaque-b','World');three=paragraph('opaque-c','Done')
    def response(operation,kwargs):
        if operation=='transcript':
            pid=kwargs['query'].get('pid','0')
            return {'more':True,'minutes':{'paragraphs':[one,two]}} if pid=='0' else {'more':False,'minutes':{'paragraphs':[two,three]}}
        return {}
    rt._provider.response=response
    asset=await rt.content.fetch(p,'record1','transcript')
    result=await rt.content.read(p,'record1','transcript',limit=2)
    assert [x['pid'] for x in result['content']['paragraphs']]==['opaque-a','opaque-b']
    assert result['next_cursor'] and asset['is_complete']
    second=await rt.content.read(p,'record1','transcript',limit=2,cursor=result['next_cursor'])
    assert [x['pid'] for x in second['content']['paragraphs']]==['opaque-c']


async def test_partial_or_stuck_transcript_never_published(rt,human,enterprise_app_body):
    a,c,p,sp=await seed(rt,human,enterprise_app_body)
    rt._provider.response={'transcript':{'more':True,'minutes':{'paragraphs':[{'pid':'only','sentences':[]}]}}}
    with pytest.raises(MeetingError):await rt.content.fetch(p,'record1','transcript')
    async with rt.db.session() as s:assert not list((await s.execute(select(Asset))).scalars())


async def test_job_lease_fencing_and_retry_after(rt,human,enterprise_app_body):
    a,c,p,sp=await seed(rt,human,enterprise_app_body)
    async with rt.db.transaction() as s:
        j=await rt.jobs.enqueue(s,'SYNC',sp,{'kind':'CORP_RECORDS'},connection_id=c['id'],ingestion_grant_id='ingestion',dedup_key='same')
        j2=await rt.jobs.enqueue(s,'SYNC',sp,{'kind':'CORP_RECORDS'},connection_id=c['id'],dedup_key='same')
        assert j.id==j2.id
    claimed=await rt.jobs.claim('worker-one')
    assert claimed.id==j.id and claimed.lease_token
    assert await rt.jobs.claim('worker-two') is None
    assert not await rt.jobs.heartbeat(j.id,'wrong-token')
    await rt.jobs.fail(j.id,claimed.lease_token,MeetingError('RATE_LIMITED',429,retry_after=60))
    async with rt.db.session() as s:
        row=await s.get(SyncJob,j.id)
        assert row.state=='RETRYING' and row.run_after>=utcnow()+timedelta(seconds=58)
    assert not await rt.jobs.finish(j.id,claimed.lease_token)


async def test_corp_sync_window_and_dedup_upsert(rt,human,enterprise_app_body):
    a,c,p,sp=await seed(rt,human,enterprise_app_body)
    def response(operation,kwargs):
        if operation!='corp_records':return {}
        q=kwargs['query'];assert q['end_time']-q['start_time']<=31*86400
        return {'total_page':1,'current_page':q['page'],'record_meetings':[{'meeting_id':'new-meeting',
            'meeting_record_id':'new-record','subject':'Synced','host_user_id':'external-m1','state':3,
            'record_files':[{'record_file_id':12345678901234567890,'record_start_time':1700000000000,
                'record_end_time':1700001000000,'record_size':1024}]}]}
    rt._provider.response=response
    requested=await rt.sync.request(sp,SyncRequest(connection_ref=c['id'],kind='CORP_RECORDS',start_at=utcnow()-timedelta(days=35),end_at=utcnow()))
    job=await rt.jobs.claim('sync-worker')
    await rt.sync.run(job,job.lease_token)
    await rt.jobs.finish(job.id,job.lease_token)
    async with rt.db.session() as s:
        rows=list((await s.execute(select(Meeting).where(Meeting.external_id=='new-meeting'))).scalars())
        assert len(rows)==1
        record=await s.scalar(select(Recording).where(Recording.meeting_id==rows[0].id))
        assert record.external_file_id=='12345678901234567890'
        conn=await s.get(Connection,c['id']);assert conn.last_synced_at is not None
    assert len(rt._provider.calls)==2


async def test_ingestion_revoked_before_worker_executes(rt,human,enterprise_app_body):
    a,c,p,sp=await seed(rt,human,enterprise_app_body)
    await rt.sync.request(sp,SyncRequest(connection_ref=c['id'],kind='CORP_RECORDS',start_at=utcnow()-timedelta(days=1),end_at=utcnow()))
    job=await rt.jobs.claim('worker')
    async with rt.db.transaction() as s:(await s.get(AccessGrant,'ingestion')).enabled=False
    with pytest.raises(MeetingError):await rt.sync.run(job,job.lease_token)
    assert not rt._provider.calls


async def test_mcp_or_employee_metadata_scope_does_not_allow_content(rt,human,enterprise_app_body):
    a,c,p,sp=await seed(rt,human,enterprise_app_body)
    limited=p.model_copy(update={'scopes':frozenset({'meeting.read'})})
    with pytest.raises(MeetingError):await rt.content.fetch(limited,'record1','minutes')
    assert not rt._provider.calls
