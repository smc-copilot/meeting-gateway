from pydantic import SecretStr
from sqlalchemy import select
import pytest
from app.core.errors import MeetingError, UpstreamError
from app.models import MeetingDirectorySyncState, MeetingDirectoryUser


def _enable_env_aksk(rt):
    rt.settings.tencent_meeting_corp_id = 'corp-env'
    rt.settings.tencent_meeting_app_secret_id = SecretStr('env-secret-id')
    rt.settings.tencent_meeting_app_secret_key = SecretStr('env-secret-key')
    rt.settings.tencent_meeting_app_sdk_id = 'env-sdk'
    rt.settings.tencent_meeting_app_operator_id = 'admin-userid'


def _user(userid, username):
    return {
        'userid': userid,
        'uuid': 'uuid-' + userid,
        'username': username,
        'area': '',
        'update_time': '1970-01-01 08:00:00',
        'avatar_url': 'https://example.com/' + userid,
        'phone': '',
        'email': '',
        'status': '1',
        'job_title': '',
        'staff_id': '',
        'entry_time': '',
        'role_name': '普通成员',
        'role_code': 'NORMAL_ROLE',
        'department_list': [],
        'user_account_type': 2,
        'account_version': 1,
        'enable_ai_account': False,
        'ai_account_type': 0,
        'phone_status': 2,
        'add_on_largemeeting': 0,
        'add_on_webinar': 0,
        'email_status': 0,
        'is_voov': 0,
        'allow_login_terminal': [],
    }


def _pages(operation, kwargs):
    if operation != 'users_list':
        return {}
    page = kwargs['page']
    if page == 1:
        return {'total_count': 21, 'current_page': 1, 'page_size': 20, 'users': [_user('wo-1', '甲')]}
    if page == 2:
        return {'total_count': 21, 'current_page': 2, 'page_size': 20, 'users': [_user('wo-2', '乙')]}
    return {'total_count': 21, 'users': []}


async def test_users_sync_walks_pages_then_incremental_stops(rt, human):
    _enable_env_aksk(rt)
    rt._provider.response = _pages
    first = await rt.directory_users.sync(human)
    assert first['started_page'] == 1 and first['last_page'] == 2 and first['synced_count'] == 2
    assert first['complete'] is True and first['total_count'] == 21
    pages = [call[3]['page'] for call in rt.tencent.calls if call[1] == 'users_list']
    assert pages == [1, 2]
    assert all(call[3]['page_size'] == 20 for call in rt.tencent.calls if call[1] == 'users_list')
    async with rt.db.session() as s:
        rows = list((await s.execute(select(MeetingDirectoryUser).where(
            MeetingDirectoryUser.deleted_at.is_(None)))).scalars())
        state = await s.scalar(select(MeetingDirectorySyncState).where(
            MeetingDirectorySyncState.deleted_at.is_(None)))
    assert {row.userid: row.username for row in rows} == {'wo-1': '甲', 'wo-2': '乙'}
    assert state.last_page == 2 and state.page_size == 20
    before = len(rt.tencent.calls)
    second = await rt.directory_users.sync(human)
    assert second['synced_count'] == 0 and second['complete'] is True
    assert len(rt.tencent.calls) == before


async def test_users_sync_resumes_after_failed_page_and_all_restarts(rt, human):
    _enable_env_aksk(rt)
    calls = {'page2': 0}

    def response(operation, kwargs):
        if operation == 'users_list' and kwargs['page'] == 2:
            calls['page2'] += 1
            if calls['page2'] == 1:
                raise UpstreamError('UPSTREAM_UNAVAILABLE')
        return _pages(operation, kwargs)

    rt._provider.response = response
    with pytest.raises(UpstreamError):
        await rt.directory_users.sync(human)
    async with rt.db.session() as s:
        state = await s.scalar(select(MeetingDirectorySyncState).where(
            MeetingDirectorySyncState.deleted_at.is_(None)))
        names = [row.userid for row in (await s.execute(select(MeetingDirectoryUser).where(
            MeetingDirectoryUser.deleted_at.is_(None)))).scalars()]
    assert state.last_page == 1 and names == ['wo-1']
    resumed = await rt.directory_users.sync(human)
    assert resumed['started_page'] == 2 and resumed['synced_count'] == 1 and resumed['complete'] is True
    rt._provider.response = _pages
    again = await rt.directory_users.sync(human, full=True)
    assert again['started_page'] == 1 and again['synced_count'] == 2


async def test_users_sync_requires_env_operator(rt, human):
    with pytest.raises(MeetingError, match='UPSTREAM_CREDENTIAL_INVALID'):
        await rt.directory_users.sync(human)
    assert rt.tencent.calls == []


async def test_directory_user_update_keeps_identity_fields(rt, human):
    from pydantic import ValidationError
    from app.schemas.requests import DirectoryUserUpdate
    async with rt.db.transaction() as s:
        s.add(MeetingDirectoryUser(
            org_id='o1', userid='wo-1', uuid='uuid-1', username='甲', email='', staff_id=''))
    updated = await rt.directory_users.update(human, 'wo-1', {'email': 'a@example.com', 'staff_id': 'E100'})
    assert updated['email'] == 'a@example.com' and updated['staff_id'] == 'E100'
    assert updated['userid'] == 'wo-1' and updated['uuid'] == 'uuid-1' and updated['username'] == '甲'
    with pytest.raises(MeetingError, match='INVALID_REQUEST'):
        await rt.directory_users.update(human, 'wo-1', {'username': '乙'})
    with pytest.raises(MeetingError, match='RESOURCE_NOT_ACCESSIBLE'):
        await rt.directory_users.update(human, 'missing', {'email': 'b@example.com'})
    with pytest.raises(ValidationError):
        DirectoryUserUpdate.model_validate({'username': '乙', 'email': 'c@example.com'})
