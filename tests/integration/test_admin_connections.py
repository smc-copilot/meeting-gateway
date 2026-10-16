import base64
from datetime import timedelta
from urllib.parse import urlsplit, parse_qs
import pytest
from sqlalchemy import select
from app.core.errors import MeetingError
from app.core.types import utcnow
from app.models import AccessGrant, Application, Credential, Connection, IdentityBinding, STSRequest, STSCallback, Client
from app.schemas.requests import ApplicationCreate, IdentityBind, EnterpriseConnectionCreate, GrantCreate, ClientCreate


async def prepare(rt, human, enterprise_app_body):
    await rt.admin.bootstrap(human)
    a = await rt.admin.create_application(human, enterprise_app_body)
    await rt.admin.bind_identity(human, IdentityBind(application_id=a['id'],member_id='m1',external_id='external-m1',
                        external_corp_id='corp',verification_source='signed directory export',reason='test mapping'))
    c = await rt.connections.create_enterprise(human, EnterpriseConnectionCreate(application_id=a['id'],
                        admin_member_id='m1',admin_userid='external-m1',reason='test connection'))
    return a,c


async def test_bootstrap_once_and_no_implicit_content(rt,human):
    result = await rt.admin.bootstrap(human)
    assert result['bootstrapped'] is True
    with pytest.raises(MeetingError):
        await rt.admin.bootstrap(human)
    async with rt.db.session() as s:
        assert await rt.policy.allowed(s,human,'meeting.application.manage')
        assert not await rt.policy.allowed(s,human,'meeting.content.read')


async def test_config_encrypts_and_never_returns_secrets(rt,human,enterprise_app_body):
    await rt.admin.bootstrap(human)
    app = await rt.admin.create_application(human,enterprise_app_body)
    assert 'secret_key' not in str(app) and 'synthetic-key' not in str(app)
    async with rt.db.session() as s:
        rows = list((await s.execute(select(Credential))).scalars())
        assert len(rows)==2 and all('synthetic-key' not in r.ciphertext for r in rows)
    assert (await rt.admin.list_rows(human,'applications'))['items'][0]['id'] == app['id']


async def test_employee_identity_conflict_and_tenant_isolation(rt,human,enterprise_app_body):
    a,c = await prepare(rt,human,enterprise_app_body)
    with pytest.raises(MeetingError) as e:
        await rt.admin.bind_identity(human,IdentityBind(application_id=a['id'],member_id='m2',external_id='external-m1',
            external_corp_id='corp',verification_source='test source',reason='conflict test'))
    assert e.value.reason == 'IDENTITY_CONFLICT'
    with pytest.raises(MeetingError):
        await rt.connections.get('other',c['id'])


async def test_enterprise_cannot_claim_unbound_operator(rt,human,enterprise_app_body):
    await rt.admin.bootstrap(human)
    app=await rt.admin.create_application(human,enterprise_app_body)
    with pytest.raises(MeetingError) as e:
        await rt.connections.create_enterprise(human,EnterpriseConnectionCreate(application_id=app['id'],
            admin_member_id='m2',admin_userid='administrator',reason='unbound test'))
    assert e.value.reason == 'IDENTITY_UNBOUND'


async def test_oauth_state_single_use_and_confirmation_bound_to_owner(rt,human,enterprise_app_body):
    await rt.admin.bootstrap(human)
    data=enterprise_app_body.model_dump()
    data.update(application_type='THIRD_PARTY_OAUTH',sdk_id='oauth-sdk',data_scope='user',secret_id=None,secret_key=None,
                oauth_secret='oauth-client-test-secret',allowed_open_corp_ids=['open-corp'])
    app=await rt.admin.create_application(human,ApplicationCreate(**data))
    start=await rt.connections.oauth_start(human,app['id'])
    state=parse_qs(urlsplit(start['authorization_url']).query)['state'][0]
    assert state.isalnum() and len(state)<=64
    callback=await rt.connections.oauth_callback(app['id'],state,'auth-code')
    async with rt.db.session() as s:
        c=await s.get(Connection,callback['connection_id']); assert c.status=='PENDING_CONFIRMATION'
    with pytest.raises(MeetingError):
        await rt.connections.oauth_callback(app['id'],state,'auth-code')
    with pytest.raises(MeetingError):
        await rt.connections.confirm_oauth(human.model_copy(update={'member_id':'m2','user_id':'u-m2'}),c.id)
    confirmed=await rt.connections.confirm_oauth(human,c.id)
    assert confirmed['status']=='ACTIVE'
    token=await rt.connections.oauth_credentials(c.id)
    assert token['access_token']=='upstream-access-private'


async def test_oauth_foreign_corporation_not_activated(rt,human,enterprise_app_body):
    await rt.admin.bootstrap(human)
    data=enterprise_app_body.model_dump();data.update(application_type='THIRD_PARTY_OAUTH',sdk_id='oauth-sdk',data_scope='user',
        secret_id=None,secret_key=None,oauth_secret='test',allowed_open_corp_ids=['different-corp'])
    a=await rt.admin.create_application(human,ApplicationCreate(**data))
    start=await rt.connections.oauth_start(human,a['id'])
    state=parse_qs(urlsplit(start['authorization_url']).query)['state'][0]
    result=await rt.connections.oauth_callback(a['id'],state,'code')
    assert result['status']=='CORP_MISMATCH'
    with pytest.raises(MeetingError): await rt.connections.confirm_oauth(human,result['connection_id'])


async def test_sts_early_callback_waits_for_request_and_newer_wins(rt,human,enterprise_app_body):
    a,c=await prepare(rt,human,enterprise_app_body)
    await rt.connections.receive_sts(a['id'],{'req_id':'req1','sts_token':'private-sts','expire_ts':int((utcnow()+timedelta(hours=6)).timestamp())},
                                     operator_id='external-m1',operate_time_ms=1)
    with pytest.raises(MeetingError): await rt.connections.sts_token(c['id'])
    rt._provider.response={'sts':{'req_id':'req1'}}
    result=await rt.connections.request_sts(human,c['id'],6)
    assert result['status']=='ACTIVE'
    assert await rt.connections.sts_token(c['id'])=='private-sts'
    await rt.connections.receive_sts(a['id'],{'req_id':'unknown','sts_token':'bad','expire_ts':int((utcnow()+timedelta(hours=6)).timestamp())},
                                     operator_id='external-m1',operate_time_ms=2)
    assert await rt.connections.sts_token(c['id'])=='private-sts'


async def test_client_scopes_and_grants_need_explicit_approved_ingestion(rt,human,enterprise_app_body):
    a,c=await prepare(rt,human,enterprise_app_body)
    client=await rt.admin.create_client(human,ClientCreate(name='sync',allowed_scopes=['meeting.sync.manage'],
                    owner_member_id='m1',allow_service=True,reason='service account'))
    body=GrantCreate(subject_type='SERVICE',subject_id=client['id'],actions=['meeting.sync.manage'],scope_type='ORG_APPROVED',
        connection_ids=[c['id']],purpose='INGESTION',reason='collection approved')
    with pytest.raises(MeetingError) as e: await rt.admin.create_grant(human,body)
    assert e.value.reason=='RETENTION_UNCONFIRMED'
    await rt.admin.approve_retention(human,{'metadata_days':180,'content_days':30,'audit_days':180,'reason':'approved by data owner'})
    g=await rt.admin.create_grant(human,body)
    assert g['purpose']=='INGESTION'
    assert 'client_secret' in client
    assert 'client_secret' not in str((await rt.admin.list_rows(human,'clients'))['items'])


async def test_management_requires_human_and_own_scope(rt,human):
    await rt.admin.bootstrap(human)
    with pytest.raises(MeetingError): await rt.admin.list_rows(human.model_copy(update={'portal':False,'actor_type':'AGENT'}),'applications')
    with pytest.raises(MeetingError): await rt.admin.list_rows(human.model_copy(update={'org_id':'other'}),'applications')
