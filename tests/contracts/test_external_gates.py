"""Optional gates: skipped, never falsely reported as passed, without external dependencies."""
import asyncio
import os
import uuid
from urllib.parse import urlsplit
import pytest


@pytest.mark.postgres
async def test_postgres_independent_connections_lock_and_claim():
    url=os.environ.get('TEST_POSTGRES_URL')
    if not url:pytest.skip('TEST_POSTGRES_URL not configured; PostgreSQL concurrency is not verified locally')
    if not urlsplit(url).path.removeprefix('/').startswith('meeting_test'):
        pytest.fail('Use an isolated database with a meeting_test prefix')
    pytest.importorskip('asyncpg')
    import base64
    from app.core.config import Settings
    from app.runtime import Runtime
    from app.core.types import Principal
    settings=Settings(environment='test',database_url=url,keyring_json={'v1':base64.urlsafe_b64encode(b't'*32).decode()},
        backend_service_token='x'*40,public_base_url='https://meeting.example.org',portal_base_url='https://portal.example.org')
    first,second=Runtime(settings),Runtime(settings)
    entered=[]
    gate=asyncio.Event()
    async def holder():
        async with first.db.lock('postgres-test-advisory'):
            entered.append('holder');gate.set();await asyncio.sleep(.15)
            entered.append('release')
    async def waiter():
        await gate.wait()
        async with second.db.lock('postgres-test-advisory'):entered.append('waiter')
    try:
        await asyncio.gather(holder(),waiter())
        assert entered==['holder','release','waiter']
        p=Principal(org_id='test-'+uuid.uuid4().hex,client_id='test-client',actor_type='SERVICE',scopes=frozenset(),audience='test')
        async with first.db.transaction() as session:
            job=await first.jobs.enqueue(session,'INBOX',p,{'inbox_id':'not-dispatched'},dedup_key=uuid.uuid4().hex)
            ident=job.id
        claimed=await asyncio.gather(first.jobs.claim('test-one'),second.jobs.claim('test-two'))
        assert sum(row is not None and row.id==ident for row in claimed)==1
    finally:
        await first.close();await second.close()


@pytest.mark.sdk
async def test_mcp_sdk_accepts_wire_contract(rt,human,enterprise_app_body):
    types=pytest.importorskip('mcp.types',reason='MCP SDK unavailable; raw HTTP protocol tests run separately')
    from test_resources_jobs import seed
    from test_http_mcp import client_for,issue
    await seed(rt,human,enterprise_app_body)
    token=await issue(rt,human,['meeting.read'],rt.settings.mcp_resource_uri)
    async with await client_for(rt) as client:
        headers={'Authorization':'Bearer '+token,'Accept':'application/json, text/event-stream','MCP-Protocol-Version':'2025-11-25'}
        response=await client.post('/mcp',headers=headers,json={'jsonrpc':'2.0','id':1,'method':'initialize',
            'params':{'protocolVersion':'2025-11-25','capabilities':{},'clientInfo':{'name':'sdk-contract','version':'1'}}})
        types.InitializeResult.model_validate(response.json()['result'])
        listed=await client.post('/mcp',headers=headers,json={'jsonrpc':'2.0','id':2,'method':'tools/list','params':{}})
        types.ListToolsResult.model_validate(listed.json()['result'])
        called=await client.post('/mcp',headers=headers,json={'jsonrpc':'2.0','id':3,'method':'tools/call','params':{'name':'meeting_list','arguments':{}}})
        types.CallToolResult.model_validate(called.json()['result'])
