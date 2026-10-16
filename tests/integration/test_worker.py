from datetime import timedelta
import pytest
from sqlalchemy import select
from app.models import Asset,AccessGrant,SyncJob,SyncPolicy,ResourceOrigin
from app.core.errors import MeetingError
from app.core.types import utcnow
from app.schemas.requests import SyncRequest
from test_resources_jobs import seed

async def test_worker_corp_ingests_but_service_cannot_read(rt,human,enterprise_app_body):
    from app.worker import Worker
    _,c,p,sp=await seed(rt,human,enterprise_app_body)
    rt.tencent.response={'corp_records':{'record_meetings':[{'meeting_id':'up-new','subject':'Imported',
        'host_user_id':'external-m1','state':3,'record_files':[{'record_file_id':'file-new','record_size':100}]}],
        'total_page':1,'current_page':1},'minutes':{'meeting_minute':{'minute':'# Native minutes','todo':''}},
        'transcript':{'more':False,'minutes':{'paragraphs':[{'pid':'0','sentences':[{'words':[{'text':'Native text'}]}]}]}}}
    job=await rt.sync.request(sp,SyncRequest(connection_ref=c['id'],kind='CORP_RECORDS',
        start_at=utcnow()-timedelta(days=1),end_at=utcnow()))
    worker=Worker(rt,'worker-test')
    for _ in range(8):
        if not await worker.run_once():break
    async with rt.db.session() as s:
        rows=list((await s.execute(select(Asset).where(Asset.state=='READY'))).scalars())
        assert {a.asset_type for a in rows}=={'transcript','minutes'}
        rec_id=rows[0].recording_id
        source=await s.get(SyncJob,job['id']);assert source.state=='SUCCEEDED'
    assert (await rt.content.read(p,rec_id,'minutes'))['is_complete']
    with pytest.raises(MeetingError):await rt.content.read(sp,rec_id,'minutes')

async def test_ingestion_deny_revokes_previously_cached_source(rt,human,enterprise_app_body):
    _,c,p,sp=await seed(rt,human,enterprise_app_body)
    assert (await rt.meetings.list(p))['items']
    async with rt.db.transaction() as s:
        s.add(AccessGrant(org_id='o1',subject_type='SERVICE',subject_id='sync-client',purpose='INGESTION',effect='DENY',
            actions=['meeting.sync.manage'],scope_type='ORG_APPROVED',connection_ids=[c['id']],issued_by='m1',reason='Stop acquisition'))
    assert not (await rt.meetings.list(p))['items']

async def test_worker_failure_retry_and_graceful_no_work(rt,human,enterprise_app_body):
    from app.worker import Worker
    _,c,p,sp=await seed(rt,human,enterprise_app_body)
    rt.tencent.error=MeetingError('UPSTREAM_UNAVAILABLE',503)
    result=await rt.sync.request(sp,SyncRequest(connection_ref=c['id'],kind='CORP_RECORDS',
        start_at=utcnow()-timedelta(days=1),end_at=utcnow()))
    worker=Worker(rt,'worker-test');assert await worker.run_once()
    async with rt.db.session() as s:
        j=await s.get(SyncJob,result['id']);assert j.state=='RETRYING'
    assert not await worker.run_once()

async def test_maintenance_expires_private_bytes_and_confirmation(rt,human,enterprise_app_body):
    from app.services.maintenance_service import MaintenanceService
    _,c,p,sp=await seed(rt,human,enterprise_app_body)
    rt.tencent.response={'minutes':{'meeting_minute':{'minute':'Private body','todo':''}}}
    result=await rt.content.fetch(p,'record1','minutes')
    async with rt.db.transaction() as s:
        a=await s.get(Asset,result['id']);a.expires_at=utcnow()-timedelta(seconds=1);key=a.object_key
    await MaintenanceService(rt).expire()
    async with rt.db.session() as s:
        a=await s.get(Asset,result['id']);assert a.object_key is None and a.state=='EXPIRED'
    with pytest.raises(FileNotFoundError):await rt.storage.get(key,'o1',result['id'])

async def test_maintenance_sts_requests_ticket_not_fake_active(rt,human,enterprise_app_body):
    from app.services.maintenance_service import MaintenanceService
    from app.models import STSRequest
    _,c,p,sp=await seed(rt,human,enterprise_app_body)
    rt.tencent.response={'sts':{'req_id':'maintenance-request'}}
    await MaintenanceService(rt).tokens();await MaintenanceService(rt).tokens()
    async with rt.db.session() as s:
        rows=list((await s.execute(select(STSRequest))).scalars())
        assert len(rows)==1 and rows[0].status=='WAITING_CALLBACK'
    with pytest.raises(MeetingError,match='STS_NOT_READY'):await rt.connections.sts_token(c['id'])
