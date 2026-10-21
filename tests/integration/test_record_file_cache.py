from sqlalchemy import select
import pytest
from app.core.errors import MeetingError, UpstreamError
from app.models import Connection, MeetingRecordFileRow, MeetingRecordFileSnapshot
from app.core.types import utcnow
from app.services.record_file_cache_service import MAX_WINDOW_SECONDS, RECORDS_PAGE_SIZE
from test_resources_jobs import seed
from test_operations import member_oauth


async def _oauth_member(rt, human, enterprise_app_body):
    _a, c, p, _sp = await seed(rt, human, enterprise_app_body)
    await member_oauth(rt, c)
    async with rt.db.transaction() as s:
        row = await s.get(Connection, c['id'])
        row.external_id = 'open-m1'
        row.corporate_verified = True
        row.status = 'ACTIVE'
    return c, p


async def test_record_files_cache_fetch_then_hit(rt, human, enterprise_app_body):
    c, p = await _oauth_member(rt, human, enterprise_app_body)
    pages = {'records': 0, 'meeting': 0}

    def response(operation, kwargs):
        if operation == 'meeting':
            pages['meeting'] += 1
            return {}
        if operation == 'records':
            pages['records'] += 1
            query = kwargs.get('query') or {}
            assert query.get('meeting_id') == 'meet-rf'
            assert query.get('page_size') == RECORDS_PAGE_SIZE
            start = query.get('start_time')
            end = query.get('end_time')
            assert isinstance(start, int) and isinstance(end, int)
            assert end - start == MAX_WINDOW_SECONDS
            assert abs(end - int(utcnow().timestamp())) <= 5
            if query.get('page', 1) == 1:
                return {
                    'total_page': 2,
                    'record_meetings': [{
                        'meeting_id': 'meet-rf',
                        'meeting_code': '111222',
                        'subject': '有录制',
                        'meeting_record_id': 'rec-group-1',
                        'state': 3,
                        'record_files': [{
                            'record_file_id': 1318080818611111111,
                            'record_start_time': 1603089930577,
                            'record_end_time': 1603089967213,
                            'record_size': 604081,
                            'sharing_state': 1,
                            'required_same_corp': False,
                            'required_participant': False,
                            'password': 'cK3wAsfw',
                            'sharing_expire': 0,
                            'allow_download': False,
                        }],
                    }],
                }
            return {
                'total_page': 2,
                'record_meetings': [{
                    'meeting_id': 'meet-rf',
                    'state': 3,
                    'record_files': [{
                        'record_file_id': 'file-2',
                        'record_start_time': 1603089970000,
                        'record_end_time': 1603089980000,
                        'record_size': 100,
                        'sharing_state': 0,
                    }],
                }],
            }
        return {}

    rt._provider.response = response
    first = await rt.record_file_cache.list_record_files(p, c['id'], 'meet-rf', pos=0, size=20)
    assert first['source'] == 'fetched'
    assert first['record_file_count'] == 2
    assert first['record_files'][0]['record_file_id'] == '1318080818611111111'
    assert first['record_files'][0]['password'] == 'cK3wAsfw'
    assert pages['meeting'] == 0 and pages['records'] == 2

    second = await rt.record_file_cache.list_record_files(p, c['id'], 'meet-rf', pos=0, size=1)
    assert second['source'] == 'cache'
    assert second['has_remaining'] is True
    assert len(second['record_files']) == 1
    assert pages['records'] == 2 and pages['meeting'] == 0

    async with rt.db.session() as s:
        snap = await s.scalar(select(MeetingRecordFileSnapshot).where(
            MeetingRecordFileSnapshot.connection_id == c['id'],
            MeetingRecordFileSnapshot.external_meeting_id == 'meet-rf',
            MeetingRecordFileSnapshot.deleted_at.is_(None)))
        rows = list((await s.execute(select(MeetingRecordFileRow).where(
            MeetingRecordFileRow.snapshot_id == snap.id,
            MeetingRecordFileRow.deleted_at.is_(None)))).scalars())
    assert snap is not None and len(rows) == 2


async def test_record_files_fetch_failure_leaves_no_rows(rt, human, enterprise_app_body):
    c, p = await _oauth_member(rt, human, enterprise_app_body)

    def response(operation, kwargs):
        if operation == 'records':
            raise UpstreamError('UPSTREAM_PERMISSION_DENIED')
        return {}

    rt._provider.response = response
    with pytest.raises(MeetingError):
        await rt.record_file_cache.list_record_files(p, c['id'], 'meet-fail')
    async with rt.db.session() as s:
        snap = await s.scalar(select(MeetingRecordFileSnapshot).where(
            MeetingRecordFileSnapshot.external_meeting_id == 'meet-fail',
            MeetingRecordFileSnapshot.deleted_at.is_(None)))
        rows = list((await s.execute(select(MeetingRecordFileRow).where(
            MeetingRecordFileRow.external_meeting_id == 'meet-fail',
            MeetingRecordFileRow.deleted_at.is_(None)))).scalars())
    assert snap is None and rows == []


async def test_record_file_detail_passthrough(rt, human, enterprise_app_body):
    c, p = await _oauth_member(rt, human, enterprise_app_body)

    def response(operation, kwargs):
        if operation == 'record_detail':
            assert kwargs.get('file_id') == '1318080811111111111'
            return {
                'record_file_id': '1318080811111111111',
                'meeting_id': 'meet-rf',
                'view_address': 'https://example.com/view',
                'download_address': 'https://example.com/dl',
                'meeting_summary': [{'download_address': 'https://example.com/txt', 'file_type': 'txt'}],
            }
        return {}

    rt._provider.response = response
    raw = await rt.record_file_cache.get_record_file_detail(p, c['id'], '1318080811111111111')
    assert raw['view_address'] == 'https://example.com/view'
    assert raw['meeting_summary'][0]['file_type'] == 'txt'
    assert not any(call[1] == 'records' for call in rt.tencent.calls)


async def test_record_files_rejects_aksk(rt, human, enterprise_app_body):
    _a, c, p, _sp = await seed(rt, human, enterprise_app_body)
    with pytest.raises(MeetingError, match='PERMISSION_DENIED'):
        await rt.record_file_cache.list_record_files(p, c['id'], 'meet-x')
    with pytest.raises(MeetingError, match='PERMISSION_DENIED'):
        await rt.record_file_cache.get_record_file_detail(p, c['id'], 'file-x')
