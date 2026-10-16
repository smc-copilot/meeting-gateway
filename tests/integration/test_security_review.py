from datetime import timedelta
import pytest
from sqlalchemy import BigInteger, select
from app.models import Credential, AccessGrant, Meeting, Client, SyncJob
from app.core.errors import MeetingError
from app.core.types import utcnow
from test_resources_jobs import seed


def test_credential_generation_supports_microsecond_sts_sequence():
    assert isinstance(Credential.__table__.c.generation.type, BigInteger)


async def test_host_does_not_prove_creator(rt, human, enterprise_app_body):
    _, _, p, _ = await seed(rt, human, enterprise_app_body)
    async with rt.db.transaction() as s:
        grants = (await s.execute(select(AccessGrant).where(AccessGrant.purpose == 'ACCESS', AccessGrant.subject_type == 'MEMBER'))).scalars()
        for g in grants:
            g.scope_type = 'SELF_CREATED'
    with pytest.raises(MeetingError):
        await rt.meetings.get(p, 'meeting1')
    async with rt.db.transaction() as s:
        (await s.get(Meeting, 'meeting1')).created_by_member_id = 'm1'
    assert (await rt.meetings.get(p, 'meeting1'))['id'] == 'meeting1'


async def test_scoped_management_cannot_manage_entire_org(rt, human, enterprise_app_body):
    await seed(rt, human, enterprise_app_body)
    async with rt.db.transaction() as s:
        grants = (await s.execute(select(AccessGrant).where(AccessGrant.purpose == 'MANAGE'))).scalars()
        for g in grants:
            g.scope_type = 'EXPLICIT'; g.resource_ids = ['meeting1']
    with pytest.raises(MeetingError):
        await rt.admin.list_rows(human, 'applications')


async def test_disabling_ingestion_client_invalidates_cached_origin(rt, human, enterprise_app_body):
    _, _, p, _ = await seed(rt, human, enterprise_app_body)
    async with rt.db.transaction() as s:
        (await s.get(Client, 'sync-client')).enabled = False
    with pytest.raises(MeetingError):
        await rt.meetings.get(p, 'meeting1')


async def test_global_stop_does_not_execute_worker_jobs(rt, human, enterprise_app_body):
    from app.worker import Worker
    _, c, _, sp = await seed(rt, human, enterprise_app_body)
    async with rt.db.transaction() as s:
        j = await rt.jobs.enqueue(s, 'SYNC', sp, {'kind':'CORP_RECORDS'}, connection_id=c['id'], dedup_key='off-switch')
        ident=j.id
    rt.settings.meeting_enabled=False
    assert await Worker(rt).run_once() is False
    async with rt.db.session() as s:
        assert (await s.get(SyncJob, ident)).state == 'PENDING'

async def test_oauth_invitee_identity_does_not_delegate_operator_authority(rt,human,enterprise_app_body):
    from app.models import Application,Connection,IdentityBinding
    from app.schemas.requests import ApplicationCreate
    from urllib.parse import parse_qs,urlsplit
    await rt.admin.bootstrap(human)
    data=enterprise_app_body.model_dump();data.update(application_type='THIRD_PARTY_OAUTH',sdk_id='oauth-test',data_scope='user',
        secret_id=None,secret_key=None,oauth_secret='private-test',allowed_open_corp_ids=['open-corp'])
    app=await rt.admin.create_application(human,ApplicationCreate(**data))
    start=await rt.connections.oauth_start(human,app['id'])
    received=await rt.connections.oauth_callback(app['id'],parse_qs(urlsplit(start['authorization_url']).query)['state'][0],'code')
    await rt.connections.confirm_oauth(human,received['connection_id'])
    async with rt.db.transaction() as s:
        c=await s.get(Connection,received['connection_id'])
        s.add(IdentityBinding(org_id='o1',application_id=app['id'],member_id='m2',identity_type='openid',external_id='open-m2',
            external_corp_id='open-corp',verification_source='verified second OAuth consent',verified_by='m2',verified_at=utcnow(),enabled=True))
    assert (await rt.connections.invitee(c,'m2')).id=='open-m2'
    with pytest.raises(MeetingError):await rt.connections.operator(c,member_id='m2')
    rt.backend.disabled.add('m2')
    with pytest.raises(MeetingError):await rt.connections.invitee(c,'m2')
