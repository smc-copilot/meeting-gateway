"""Only local synthetic identities and provider responses; never live Tencent credentials."""
import base64
from datetime import timedelta
import pytest
from app.core.config import Settings
from app.core.types import MemberContext, Principal, utcnow
from app.core.errors import MeetingError
from app.runtime import Runtime
from app.services.permission_service import ALL_ACTIONS


class FakeBackend:
    disabled: set[str]
    def __init__(self):
        self.disabled = set()
        self.available = True
    async def context(self, token):
        if token not in {'backend-m1', 'backend-m2', 'backend-other'}:
            raise MeetingError('TOKEN_INVALID', 401)
        return await self.resolve('other' if token == 'backend-other' else 'o1', token.removeprefix('backend-'))
    async def resolve(self, org_id, member_id):
        if not self.available:
            raise MeetingError('IDENTITY_SERVICE_UNAVAILABLE', 503)
        if member_id in self.disabled or member_id not in {'m1', 'm2', 'other'}:
            raise MeetingError('MEMBER_INACTIVE', 403)
        return MemberContext(org_id=org_id, member_id=member_id, user_id='u-' + member_id,
                             member_role='admin' if member_id == 'm1' else 'member', name=member_id)
    async def search(self, org_id, query):
        return [await self.resolve(org_id, name) for name in ('m1','m2') if query in name]
    async def close(self):
        return None


class FakeTencent:
    def __init__(self):
        self.calls = []
        self.response = {}
        self.error = None
        self.created = 0
    async def admit(self, connection_id, operation, *, heartbeat=None):
        return None
    def _dispatch(self, operation, kwargs):
        if self.error:
            raise self.error
        if callable(self.response):
            return self.response(operation, kwargs)
        return self.response.get(operation, {'meeting_info_list': [], 'remaining': 0, 'total_page': 0, 'record_meetings': []})
    async def call(self, connection_id, operation, operator, **kwargs):
        kwargs.pop('heartbeat', None)
        kwargs.pop('admitted', None)
        self.calls.append((connection_id, operation, operator, kwargs))
        if operation == 'create':
            if self.error:
                raise self.error
            self.created += 1
            body = kwargs['body']
            return {'meeting_info_list': [{'meeting_id': 'up-created-' + str(self.created), 'meeting_code':'123123123',
                'subject': body['subject'], 'start_time': body['start_time'], 'end_time':body['end_time']}]}
        return self._dispatch(operation, kwargs)
    async def open_id_to_userid(self, *, open_id, heartbeat=None):
        kwargs = {'open_id': open_id}
        self.calls.append(('env-aksk', 'open_id_to_userid', None, kwargs))
        return self._dispatch('open_id_to_userid', kwargs)
    async def records_aksk(self, *, query, heartbeat=None):
        kwargs = {'query': query}
        self.calls.append(('env-aksk', 'records_aksk', None, kwargs))
        return self._dispatch('records_aksk', kwargs)
    async def sts_request(self, *, valid_hours, heartbeat=None):
        kwargs = {'valid_hours': valid_hours}
        self.calls.append(('env-aksk', 'sts_request', None, kwargs))
        return self._dispatch('sts_request', kwargs)
    async def oauth(self, operation, payload):
        self.calls.append(('oauth',operation,payload))
        if self.error:
            raise self.error
        value = self.response.get(operation)
        if value is not None:
            return value
        return {'open_id':'open-m1','open_corp_id':'open-corp','access_token':'upstream-access-private',
                'refresh_token':'upstream-refresh-private','expires':int((utcnow()+timedelta(hours=6)).timestamp()),
                'scopes':['VIEW_USER_INFO','VIEW_VIDEO']}


@pytest.fixture
async def rt(tmp_path):
    provider = FakeTencent()
    settings = Settings(environment='test', database_url=f'sqlite:///{tmp_path}/meeting.sqlite',
        keyring_json={'v1':base64.urlsafe_b64encode(b'x'*32).decode()},
        storage_path=tmp_path/'private',public_base_url='https://meeting.example.org',
        portal_base_url='https://portal.example.org',allowed_hosts=['testserver','meeting.example.org'],
        upstream_min_interval_seconds=0,meeting_create_enabled=True,meeting_mcp_enabled=True,
        meeting_corp_sync_enabled=True,media_allowed_hosts=['media.example.org'])
    runtime = Runtime(settings,backend=FakeBackend(),provider=provider)
    await runtime.db.create_schema_for_test()
    from app.models import LocalMember
    async with runtime.db.transaction() as session:
        for member_id, role in (('m1', 'admin'), ('m2', 'member'), ('other', 'member')):
            session.add(LocalMember(id=member_id, org_id='o1', component_id='meeting-gateway', issuer_id='account-login-v1',
                external_user_id='u-' + member_id, source='ACCOUNT_LOGIN', local_enabled=True, state='ACTIVE',
                identity_version=1, member_role=role, profile_json={'name': member_id}))
    runtime.test_member_session = await runtime.identity.issue_session_for_member('m1')
    yield runtime
    await runtime.close()


@pytest.fixture
def human():
    return Principal(org_id='o1',member_id='m1',user_id='u-m1',actor_type='MEMBER',client_id='portal',
                     portal=True,member_role='admin',scopes=ALL_ACTIONS,audience='portal')


@pytest.fixture
def enterprise_app_body():
    from app.schemas.requests import ApplicationCreate
    return ApplicationCreate(name='Synthetic enterprise',application_type='ENTERPRISE_AKSK',environment='test',
        tencent_corp_id='corp',sdk_id='sdk-enterprise',data_scope='enterprise',secret_id='synthetic-id',
        secret_key='synthetic-key-never-live',webhook_token='callback-token-test',
        webhook_encoding_key=base64.b64encode(b'k'*32).decode().rstrip('='),reason='fixture setup')
