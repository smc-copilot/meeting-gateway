import base64
from datetime import timedelta

from pydantic import SecretStr
from sqlalchemy import select
import pytest
from app.core.errors import MeetingError, UpstreamError
from app.models import (
    Connection, MeetingEnvStsToken, MeetingOAuthUseridMap,
    MeetingRecordFileRow, MeetingRecordFileSnapshot,
)
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


def _enable_env_aksk(rt):
    rt.settings.tencent_meeting_corp_id = 'corp-env'
    rt.settings.tencent_meeting_app_id = '33510141629'
    rt.settings.tencent_meeting_app_secret_id = SecretStr('env-secret-id')
    rt.settings.tencent_meeting_app_secret_key = SecretStr('env-secret-key')
    rt.settings.tencent_meeting_app_sdk_id = 'env-sdk'
    rt.settings.tencent_meeting_app_operator_id = 'admin-userid'


def _enable_app_webhook(rt):
    rt.settings.tencent_meeting_app_webhook_token = SecretStr('env-sts-callback-token')
    rt.settings.tencent_meeting_app_webhook_encoding_key = SecretStr(
        base64.b64encode(b'e' * 32).decode())
    rt.settings.tencent_meeting_sts_valid_hours = 24
    rt.settings.tencent_meeting_sts_refresh_margin_seconds = 3600


async def _seed_env_sts(rt, token='sts-live-token', *, req_id='req-seed'):
    async with rt.db.transaction() as s:
        s.add(MeetingEnvStsToken(
            req_id=req_id,
            state='ACTIVE',
            token_ciphertext=rt.keys.encrypt(token, f'env-sts:{req_id}'),
            expires_at=utcnow() + timedelta(hours=6),
            valid_hours=24,
            requested_at=utcnow(),
            received_at=utcnow(),
            operator_id='admin-userid',
        ))


def _records_payload(page: int):
    if page == 1:
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


async def test_record_files_cache_fetch_then_hit(rt, human, enterprise_app_body):
    c, p = await _oauth_member(rt, human, enterprise_app_body)
    _enable_env_aksk(rt)
    pages = {'records_aksk': 0, 'open_id_to_userid': 0}

    def response(operation, kwargs):
        if operation == 'open_id_to_userid':
            pages['open_id_to_userid'] += 1
            assert kwargs.get('open_id') == 'open-m1'
            return {
                'userid_list': [{'open_id': 'open-m1', 'userid': 'userid-m1'}],
                'invalid_open_id_list': [],
            }
        if operation == 'records_aksk':
            pages['records_aksk'] += 1
            query = kwargs.get('query') or {}
            assert query.get('meeting_id') == 'meet-rf'
            assert query.get('userid') == 'userid-m1'
            assert query.get('page_size') == RECORDS_PAGE_SIZE
            start = query.get('start_time')
            end = query.get('end_time')
            assert isinstance(start, int) and isinstance(end, int)
            assert end - start == MAX_WINDOW_SECONDS
            assert abs(end - int(utcnow().timestamp())) <= 5
            return _records_payload(query.get('page', 1))
        return {}

    rt._provider.response = response
    first = await rt.record_file_cache.list_record_files(p, c['id'], 'meet-rf', pos=0, size=20)
    assert first['source'] == 'fetched'
    assert first['record_file_count'] == 2
    assert first['record_files'][0]['record_file_id'] == '1318080818611111111'
    assert first['record_files'][0]['password'] == 'cK3wAsfw'
    assert pages['open_id_to_userid'] == 1 and pages['records_aksk'] == 2
    assert not any(call[1] == 'records' for call in rt.tencent.calls)

    second = await rt.record_file_cache.list_record_files(p, c['id'], 'meet-rf', pos=0, size=1)
    assert second['source'] == 'cache'
    assert second['has_remaining'] is True
    assert len(second['record_files']) == 1
    assert pages['records_aksk'] == 2 and pages['open_id_to_userid'] == 1

    async with rt.db.session() as s:
        snap = await s.scalar(select(MeetingRecordFileSnapshot).where(
            MeetingRecordFileSnapshot.connection_id == c['id'],
            MeetingRecordFileSnapshot.external_meeting_id == 'meet-rf',
            MeetingRecordFileSnapshot.deleted_at.is_(None)))
        rows = list((await s.execute(select(MeetingRecordFileRow).where(
            MeetingRecordFileRow.snapshot_id == snap.id,
            MeetingRecordFileRow.deleted_at.is_(None)))).scalars())
        mapped = await s.scalar(select(MeetingOAuthUseridMap).where(
            MeetingOAuthUseridMap.org_id == 'o1',
            MeetingOAuthUseridMap.open_id == 'open-m1',
            MeetingOAuthUseridMap.deleted_at.is_(None)))
    assert snap is not None and len(rows) == 2
    assert mapped is not None and mapped.userid == 'userid-m1'
    assert mapped.oauth_sdk_id == '33510141629'


async def test_record_files_uses_cached_userid_map(rt, human, enterprise_app_body):
    c, p = await _oauth_member(rt, human, enterprise_app_body)
    _enable_env_aksk(rt)
    async with rt.db.transaction() as s:
        s.add(MeetingOAuthUseridMap(
            org_id='o1', open_id='open-m1', userid='cached-userid',
            oauth_sdk_id='sdk-enterprise', resolved_at=utcnow()))
    pages = {'open_id_to_userid': 0, 'records_aksk': 0}

    def response(operation, kwargs):
        if operation == 'open_id_to_userid':
            pages['open_id_to_userid'] += 1
            return {}
        if operation == 'records_aksk':
            pages['records_aksk'] += 1
            assert kwargs['query'].get('userid') == 'cached-userid'
            return {'total_page': 1, 'record_meetings': []}
        return {}

    rt._provider.response = response
    result = await rt.record_file_cache.list_record_files(p, c['id'], 'meet-mapped', pos=0, size=20)
    assert result['source'] == 'fetched'
    assert result['record_file_count'] == 0
    assert pages['open_id_to_userid'] == 0 and pages['records_aksk'] == 1


async def test_record_files_empty_upstream_is_success(rt, human, enterprise_app_body):
    """Meeting with no recordings must cache empty list, not UPSTREAM_CONTRACT_ERROR."""
    c, p = await _oauth_member(rt, human, enterprise_app_body)
    _enable_env_aksk(rt)
    async with rt.db.transaction() as s:
        s.add(MeetingOAuthUseridMap(
            org_id='o1', open_id='open-m1', userid='userid-m1',
            oauth_sdk_id='33510141629', resolved_at=utcnow()))

    def response(operation, kwargs):
        if operation == 'records_aksk':
            # Real Tencent empty shape: no record_meetings key at all
            return {
                'total_count': 0,
                'total_page': 0,
                'current_page': 1,
                'current_size': 0,
            }
        return {}

    rt._provider.response = response
    first = await rt.record_file_cache.list_record_files(p, c['id'], 'meet-empty', pos=0, size=20)
    assert first['source'] == 'fetched'
    assert first['record_file_count'] == 0
    assert first['record_files'] == []
    assert first['has_remaining'] is False

    second = await rt.record_file_cache.list_record_files(p, c['id'], 'meet-empty', pos=0, size=20)
    assert second['source'] == 'cache'
    assert second['record_file_count'] == 0

    async with rt.db.session() as s:
        snap = await s.scalar(select(MeetingRecordFileSnapshot).where(
            MeetingRecordFileSnapshot.external_meeting_id == 'meet-empty',
            MeetingRecordFileSnapshot.deleted_at.is_(None)))
        rows = list((await s.execute(select(MeetingRecordFileRow).where(
            MeetingRecordFileRow.external_meeting_id == 'meet-empty',
            MeetingRecordFileRow.deleted_at.is_(None)))).scalars())
    assert snap is not None and snap.total_count == 0 and rows == []


async def test_record_files_meeting_row_without_files_is_success(rt, human, enterprise_app_body):
    c, p = await _oauth_member(rt, human, enterprise_app_body)
    _enable_env_aksk(rt)
    async with rt.db.transaction() as s:
        s.add(MeetingOAuthUseridMap(
            org_id='o1', open_id='open-m1', userid='userid-m1',
            oauth_sdk_id='33510141629', resolved_at=utcnow()))

    def response(operation, kwargs):
        if operation == 'records_aksk':
            return {
                'total_page': 1,
                'record_meetings': [{
                    'meeting_id': 'meet-nofile',
                    'subject': '无文件',
                    'state': 1,
                    'record_files': None,
                }],
            }
        return {}

    rt._provider.response = response
    result = await rt.record_file_cache.list_record_files(p, c['id'], 'meet-nofile', pos=0, size=20)
    assert result['source'] == 'fetched'
    assert result['record_file_count'] == 0
    assert result['subject'] == '无文件'


async def test_record_files_fetch_failure_leaves_no_rows(rt, human, enterprise_app_body):
    c, p = await _oauth_member(rt, human, enterprise_app_body)
    _enable_env_aksk(rt)

    def response(operation, kwargs):
        if operation == 'open_id_to_userid':
            return {
                'userid_list': [{'open_id': 'open-m1', 'userid': 'userid-m1'}],
                'invalid_open_id_list': [],
            }
        if operation == 'records_aksk':
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


async def test_record_files_missing_env_aksk(rt, human, enterprise_app_body):
    c, p = await _oauth_member(rt, human, enterprise_app_body)
    with pytest.raises(MeetingError, match='UPSTREAM_CREDENTIAL_INVALID'):
        await rt.record_file_cache.list_record_files(p, c['id'], 'meet-no-env')
    assert not any(call[1] in {'records_aksk', 'open_id_to_userid', 'records'} for call in rt.tencent.calls)


async def test_record_file_detail_passthrough(rt, human, enterprise_app_body):
    c, p = await _oauth_member(rt, human, enterprise_app_body)
    _enable_env_aksk(rt)
    await _seed_env_sts(rt, token='sts-for-detail')

    def response(operation, kwargs):
        if operation == 'record_detail_aksk':
            assert kwargs.get('record_file_id') == '1318080811111111111'
            assert kwargs.get('sts_token') == 'sts-for-detail'
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
    assert any(call[1] == 'record_detail_aksk' for call in rt.tencent.calls)
    assert not any(call[1] in {'record_detail', 'records', 'records_aksk'} for call in rt.tencent.calls)


async def test_record_file_detail_missing_env_aksk(rt, human, enterprise_app_body):
    c, p = await _oauth_member(rt, human, enterprise_app_body)
    with pytest.raises(MeetingError, match='UPSTREAM_CREDENTIAL_INVALID'):
        await rt.record_file_cache.get_record_file_detail(p, c['id'], '1318080811111111111')
    assert not any(call[1] in {'record_detail_aksk', 'record_detail', 'sts_request'} for call in rt.tencent.calls)


async def test_record_file_detail_sts_not_ready(rt, human, enterprise_app_body):
    c, p = await _oauth_member(rt, human, enterprise_app_body)
    _enable_env_aksk(rt)
    _enable_app_webhook(rt)
    rt._provider.response = {'sts_request': {'req_id': 'req-waiting'}}
    with pytest.raises(MeetingError, match='STS_NOT_READY'):
        await rt.record_file_cache.get_record_file_detail(p, c['id'], '1318080811111111111')
    assert any(call[1] == 'sts_request' for call in rt.tencent.calls)
    assert not any(call[1] == 'record_detail_aksk' for call in rt.tencent.calls)
    async with rt.db.session() as s:
        row = await s.scalar(select(MeetingEnvStsToken).where(MeetingEnvStsToken.req_id == 'req-waiting'))
        assert row is not None and row.state == 'WAITING'


async def test_record_files_rejects_aksk(rt, human, enterprise_app_body):
    _a, c, p, _sp = await seed(rt, human, enterprise_app_body)
    with pytest.raises(MeetingError, match='PERMISSION_DENIED'):
        await rt.record_file_cache.list_record_files(p, c['id'], 'meet-x')
    with pytest.raises(MeetingError, match='PERMISSION_DENIED'):
        await rt.record_file_cache.get_record_file_detail(p, c['id'], 'file-x')
