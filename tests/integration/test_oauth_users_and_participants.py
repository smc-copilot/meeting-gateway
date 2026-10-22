import base64
from pydantic import SecretStr
from sqlalchemy import select
import pytest
from app.core.errors import MeetingError, UpstreamError
from app.integrations.tencent_meeting.mapper import PARTICIPANTS_PAGE_SIZE
from app.models import Connection, MeetingOAuthUser, MeetingParticipantRow, MeetingParticipantSnapshot
from app.schemas.requests import OAuthUsersSync
from test_resources_jobs import seed
from test_operations import member_oauth


def _name(text: str) -> str:
    return base64.b64encode(text.encode()).decode()


def _enable_env_aksk(rt):
    rt.settings.tencent_meeting_corp_id = 'corp-env'
    rt.settings.tencent_meeting_app_id = '33510141629'
    rt.settings.tencent_meeting_app_secret_id = SecretStr('env-secret-id')
    rt.settings.tencent_meeting_app_secret_key = SecretStr('env-secret-key')
    rt.settings.tencent_meeting_app_sdk_id = 'env-sdk'
    rt.settings.tencent_meeting_app_operator_id = 'admin-userid'


async def _oauth_member(rt, human, enterprise_app_body):
    _a, c, p, _sp = await seed(rt, human, enterprise_app_body)
    await member_oauth(rt, c)
    async with rt.db.transaction() as s:
        row = await s.get(Connection, c['id'])
        row.external_id = 'open-m1'
        row.corporate_verified = True
        row.status = 'ACTIVE'
    return c, p


async def test_oauth_users_sync_upserts_and_soft_fails(rt, human, enterprise_app_body):
    c, p = await _oauth_member(rt, human, enterprise_app_body)

    def response(operation, kwargs):
        if operation != 'user_basic':
            return {}
        target = kwargs.get('query', {}).get('operator_id')
        if target == 'open-ok':
            return {
                'username': '昵称OK', 'open_corp_id': 'corp-1',
                'open_corp_name': '示例企业', 'status': '1', 'avatar_url': 'https://example.com/a.png',
            }
        raise UpstreamError('UPSTREAM_CAPABILITY_UNAVAILABLE')

    rt._provider.response = response
    result = await rt.oauth_users.sync(p, OAuthUsersSync(
        connection_ref=c['id'], open_ids=['open-ok', 'open-fail', 'open-ok']))
    assert result['upserted'] == 1 and result['failed'] == 1
    by_id = {item['open_id']: item for item in result['items']}
    assert by_id['open-ok']['status'] == 'UPSERTED'
    assert by_id['open-ok']['username'] == '昵称OK'
    assert by_id['open-fail']['status'] == 'FAILED'
    async with rt.db.session() as s:
        row = await s.scalar(select(MeetingOAuthUser).where(
            MeetingOAuthUser.org_id == 'o1', MeetingOAuthUser.open_id == 'open-ok',
            MeetingOAuthUser.deleted_at.is_(None)))
    assert row is not None and row.username == '昵称OK' and row.open_corp_id == 'corp-1'


async def test_oauth_users_sync_rejects_aksk(rt, human, enterprise_app_body):
    _a, c, p, _sp = await seed(rt, human, enterprise_app_body)
    with pytest.raises(MeetingError, match='PERMISSION_DENIED'):
        await rt.oauth_users.sync(p, OAuthUsersSync(connection_ref=c['id'], open_ids=['x']))


async def test_participants_cache_fetch_then_hit(rt, human, enterprise_app_body):
    _enable_env_aksk(rt)
    c, p = await _oauth_member(rt, human, enterprise_app_body)
    pages = {'participants_aksk': 0, 'open_id_to_userid': 0}

    def response(operation, kwargs):
        if operation == 'open_id_to_userid':
            pages['open_id_to_userid'] += 1
            return {'userid_list': [{'open_id': 'open-m1', 'userid': 'enterprise-u1'}]}
        if operation != 'participants_aksk':
            return {}
        pages['participants_aksk'] += 1
        assert kwargs.get('userid') == 'enterprise-u1'
        assert kwargs.get('meeting_id') == 'meet-1'
        query = kwargs.get('query') or {}
        assert query.get('size') == PARTICIPANTS_PAGE_SIZE
        if query.get('pos', 0) == 0:
            return {
                'participants': [{
                    'open_id': 'p1', 'user_name': _name('一'), 'is_enterprise_user': False,
                }],
                'has_remaining': True, 'next_pos': 10, 'total_count': 2,
            }
        return {
            'participants': [{
                'open_id': 'p2', 'user_name': _name('二'), 'is_enterprise_user': True,
            }],
            'has_remaining': False,
        }

    rt._provider.response = response
    first = await rt.participant_cache.list_participants(p, c['id'], 'meet-1', pos=0, size=20)
    assert first['source'] == 'fetched'
    assert first['participant_count'] == 2
    assert first['participants'][0]['join_name'] == '一'
    assert first['participants'][0]['open_id'] == 'p1'
    assert 'profile' not in first['participants'][0]
    assert pages['participants_aksk'] == 2
    assert pages['open_id_to_userid'] == 1

    second = await rt.participant_cache.list_participants(p, c['id'], 'meet-1', pos=0, size=1)
    assert second['source'] == 'cache'
    assert second['has_remaining'] is True
    assert second['next_pos'] == 1
    assert len(second['participants']) == 1
    assert pages['participants_aksk'] == 2
    assert pages['open_id_to_userid'] == 1

    async with rt.db.session() as s:
        snap = await s.scalar(select(MeetingParticipantSnapshot).where(
            MeetingParticipantSnapshot.connection_id == c['id'],
            MeetingParticipantSnapshot.external_meeting_id == 'meet-1',
            MeetingParticipantSnapshot.deleted_at.is_(None)))
        rows = list((await s.execute(select(MeetingParticipantRow).where(
            MeetingParticipantRow.snapshot_id == snap.id,
            MeetingParticipantRow.deleted_at.is_(None)))).scalars())
    assert snap is not None and len(rows) == 2


async def test_participants_fetch_failure_leaves_no_rows(rt, human, enterprise_app_body):
    _enable_env_aksk(rt)
    c, p = await _oauth_member(rt, human, enterprise_app_body)

    def response(operation, kwargs):
        if operation == 'open_id_to_userid':
            return {'userid_list': [{'open_id': 'open-m1', 'userid': 'enterprise-u1'}]}
        if operation == 'participants_aksk':
            raise UpstreamError('UPSTREAM_PERMISSION_DENIED')
        return {}

    rt._provider.response = response
    with pytest.raises(MeetingError):
        await rt.participant_cache.list_participants(p, c['id'], 'meet-fail')
    async with rt.db.session() as s:
        snap = await s.scalar(select(MeetingParticipantSnapshot).where(
            MeetingParticipantSnapshot.external_meeting_id == 'meet-fail',
            MeetingParticipantSnapshot.deleted_at.is_(None)))
        rows = list((await s.execute(select(MeetingParticipantRow).where(
            MeetingParticipantRow.external_meeting_id == 'meet-fail',
            MeetingParticipantRow.deleted_at.is_(None)))).scalars())
    assert snap is None and rows == []


async def test_participants_rejects_aksk(rt, human, enterprise_app_body):
    _enable_env_aksk(rt)
    _a, c, p, _sp = await seed(rt, human, enterprise_app_body)
    with pytest.raises(MeetingError, match='PERMISSION_DENIED'):
        await rt.participant_cache.list_participants(p, c['id'], 'meet-x')


async def test_participants_missing_env_aksk(rt, human, enterprise_app_body):
    c, p = await _oauth_member(rt, human, enterprise_app_body)
    with pytest.raises(MeetingError) as exc:
        await rt.participant_cache.list_participants(p, c['id'], 'meet-no-aksk')
    assert exc.value.reason == 'UPSTREAM_CREDENTIAL_INVALID'
