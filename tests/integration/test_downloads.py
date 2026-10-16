from datetime import timedelta
import pytest
from sqlalchemy import select
from app.models import Asset,DownloadTicket,AccessGrant
from app.core.errors import MeetingError
from app.core.types import utcnow
from test_resources_jobs import seed

async def asset_seed(rt,human,body):
    _,c,p,_=await seed(rt,human,body)
    async with rt.db.transaction() as s:
        a=Asset(id='text1',org_id='o1',meeting_id='meeting1',recording_id='record1',connection_id=c['id'],
            asset_type='transcript',content_hash='a'*64,state='READY',is_complete=True,content_type='application/json',
            details={},fetched_at=utcnow(),expires_at=utcnow()+timedelta(days=1))
        s.add(a)
    rt.tencent.response={'record_detail':{'meeting_summary':[{'download_address':'https://media.example.org/native.txt','file_type':'txt'}]}}
    return c,p

async def test_native_ticket_is_bound_not_url_leak(rt,human,enterprise_app_body):
    c,p=await asset_seed(rt,human,enterprise_app_body)
    result=await rt.downloads.issue(p,'text1','Business review')
    assert 'media.example' not in str(result) and result['download_path'].startswith('/api/v1/downloads/')
    await rt.downloads.validate(p,result['ticket'])
    async with rt.db.session() as s:
        ticket=await s.scalar(select(DownloadTicket));assert ticket.token_hash!=result['ticket']
    for modified in ({'member_id':'m2'},{'client_id':'different'},{'audience':rt.settings.mcp_resource_uri}):
        with pytest.raises(MeetingError):await rt.downloads.validate(p.model_copy(update=modified),result['ticket'])

async def test_download_rechecks_revocation_and_expiry(rt,human,enterprise_app_body):
    c,p=await asset_seed(rt,human,enterprise_app_body);result=await rt.downloads.issue(p,'text1','Review')
    async with rt.db.transaction() as s:
        row=await s.scalar(select(DownloadTicket));row.expires_at=utcnow()-timedelta(seconds=1)
    with pytest.raises(MeetingError,match='DOWNLOAD_EXPIRED'):await rt.downloads.validate(p,result['ticket'])
    result=await rt.downloads.issue(p,'text1','Review again')
    async with rt.db.transaction() as s:
        s.add(AccessGrant(org_id='o1',subject_type='MEMBER',subject_id='m1',actions=['meeting.content.download'],
            scope_type='ORG_APPROVED',effect='DENY',issued_by='m1',reason='Revoked'))
    with pytest.raises(MeetingError):await rt.downloads.validate(p,result['ticket'])

async def test_private_url_and_unavailable_native_export_rejected(rt,human,enterprise_app_body):
    c,p=await asset_seed(rt,human,enterprise_app_body)
    rt.tencent.response={'record_detail':{'meeting_summary':[{'download_address':'http://127.0.0.1/a','file_type':'txt'}]}}
    with pytest.raises(MeetingError,match='SSRF_BLOCKED'):await rt.downloads.issue(p,'text1','Review')
    rt.tencent.response={'record_detail':{'ai_topic_minutes':[{'download_address':'https://media.example.org/other.txt','file_type':'txt'}]}}
    async with rt.db.transaction() as s:
        a=await s.get(Asset,'text1');a.asset_type='minutes';a.details={'llm':3}
    with pytest.raises(MeetingError,match='DOWNLOAD_NOT_ALLOWED'):await rt.downloads.issue(p,'text1','Review')

async def test_stream_quota_and_single_range_validation(rt,human,enterprise_app_body):
    c,p=await asset_seed(rt,human,enterprise_app_body)
    rt.settings.daily_download_bytes_per_client=100
    result=await rt.downloads.issue(p,'text1','Review')
    await rt.downloads.charge(p,80)
    with pytest.raises(MeetingError,match='RATE_LIMITED'):await rt.downloads.charge(p,30)
    for value in ['bytes=0-1,4-8','bytes=-','bytes=10-2','items=0-1','bytes=0-1\r\nX: 1']:
        with pytest.raises(MeetingError):rt.downloads.parse_range(value)
    assert rt.downloads.parse_range('bytes=0-10')=='bytes=0-10'
