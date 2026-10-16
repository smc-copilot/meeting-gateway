from datetime import timedelta
import json
import pytest
import httpx
from app.schemas.requests import ClientCreate,GrantCreate
from app.models import AccessGrant,AccessToken
from sqlalchemy import select
from test_resources_jobs import seed

async def client_for(rt):
    from app.main import create_app
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(runtime=rt)),base_url='https://meeting.example.org')

async def issue(rt,human,scopes,audience):
    c=await rt.admin.create_client(human,ClientCreate(name='HTTP client',allowed_scopes=scopes,owner_member_id='m1',reason='Test client'))
    result=await rt.auth.exchange(c['id'],c['client_secret'],'backend-m1',scopes,audience)
    return result['access_token']

async def test_http_auth_validation_redacts_secret(rt,human,enterprise_app_body):
    await seed(rt,human,enterprise_app_body)
    async with await client_for(rt) as client:
        res=await client.get('/api/v1/meetings')
        assert res.status_code==401 and 'trace_id' in res.json()
        res=await client.post('/api/v1/admin/applications',headers={'Authorization':'Bearer backend-m1'},json={'secret_key':'must-not-echo'})
        assert res.status_code==422 and 'must-not-echo' not in res.text
        assert res.json()['reason']=='INVALID_REQUEST'

async def test_rest_metadata_only_mcp_equivalent_denial(rt,human,enterprise_app_body):
    await seed(rt,human,enterprise_app_body)
    rest=await issue(rt,human,['meeting.read'],rt.settings.rest_resource_uri)
    mcp=await issue(rt,human,['meeting.read'],rt.settings.mcp_resource_uri)
    async with await client_for(rt) as client:
        headers={'Authorization':'Bearer '+rest}
        res=await client.get('/api/v1/meetings',headers=headers);assert res.status_code==200
        assert res.json()['data']['items'] and 'sync_coverage' in res.json()['data']
        assert (await client.get('/api/v1/recordings/record1/transcript',headers=headers)).status_code==404
        mh={'Authorization':'Bearer '+mcp,'Accept':'application/json, text/event-stream','MCP-Protocol-Version':'2025-11-25'}
        response=await client.post('/mcp',headers=mh,json={'jsonrpc':'2.0','id':1,'method':'tools/call',
            'params':{'name':'meeting_transcript_read','arguments':{'recording_id':'record1'}}})
        assert response.status_code==200 and response.json()['result']['isError'] is True
        assert 'text' not in response.json()['result'].get('structuredContent',{})

async def test_mcp_protocol_handshake_list_and_wrong_audience(rt,human,enterprise_app_body):
    await seed(rt,human,enterprise_app_body)
    token=await issue(rt,human,['meeting.read'],rt.settings.mcp_resource_uri)
    async with await client_for(rt) as client:
        headers={'Authorization':'Bearer '+token,'Accept':'application/json, text/event-stream'}
        response=await client.post('/mcp',headers=headers,json={'jsonrpc':'2.0','id':1,'method':'initialize',
            'params':{'protocolVersion':'2025-11-25','capabilities':{},'clientInfo':{'name':'test','version':'1'}}})
        assert response.status_code==200
        assert response.json()['result']['protocolVersion']=='2025-11-25'
        headers['MCP-Protocol-Version']='2025-11-25'
        notify=await client.post('/mcp',headers=headers,json={'jsonrpc':'2.0','method':'notifications/initialized'})
        assert notify.status_code==202 and not notify.content
        res=await client.post('/mcp',headers=headers,json={'jsonrpc':'2.0','id':2,'method':'tools/list'})
        names={t['name'] for t in res.json()['result']['tools']};assert 'meeting_list' in names and 'meeting_create_prepare' not in names
        assert (await client.get('/api/v1/meetings',headers=headers)).status_code==401
        assert (await client.post('/mcp',headers={'Authorization':'Bearer backend-m1'},json={})).status_code==401
        headers['MCP-Protocol-Version']='1900-01-01'
        assert (await client.post('/mcp',headers=headers,json={'jsonrpc':'2.0','id':3,'method':'ping'})).status_code==400

async def test_public_metadata_and_wrong_host_origin(rt):
    async with await client_for(rt) as client:
        for path in ('/.well-known/oauth-protected-resource/mcp','/.well-known/oauth-authorization-server'):
            res=await client.get(path);assert res.status_code==200
        assert (await client.get('/health/live')).json()=={'status':'ok'}
        assert (await client.get('/health/live',headers={'Host':'evil.example.org'})).status_code==400
        assert (await client.post('/oauth/token',headers={'Origin':'https://evil.example.org'},data={})).status_code==403
        rt.settings.max_request_bytes=1024
        assert (await client.post('/oauth/token',content=b'a'*1025)).status_code==413

async def test_admin_token_cannot_confirm_and_unknown_fields_forbidden(rt,human,enterprise_app_body):
    from test_operations import request
    from test_operations import member_oauth
    _,c,p,sp=await seed(rt,human,enterprise_app_body)
    await member_oauth(rt,c)
    token=await issue(rt,human,['meeting.create.self'],rt.settings.rest_resource_uri)
    async with await client_for(rt) as client:
        body=request(c).model_dump(mode='json')
        headers={'Authorization':'Bearer '+token,'Idempotency-Key':'http-1'}
        bad=await client.post('/api/v1/meetings',headers=headers,json={**body,'confirmed':True})
        assert bad.status_code==422
        response=await client.post('/api/v1/meetings',headers=headers,json=body);assert response.status_code==202
        op=response.json()['data']
        denied=await client.post(f"/api/v1/portal/operations/{op['id']}/confirm",headers=headers,json={'request_hash':op['request_hash']})
        assert denied.status_code==401
        approved=await client.post(f"/api/v1/portal/operations/{op['id']}/confirm",headers={'Authorization':'Bearer backend-m1'},json={'request_hash':op['request_hash']})
        assert approved.status_code==200

async def test_portal_bootstrap_and_no_implicit_read(rt,human,enterprise_app_body):
    async with await client_for(rt) as client:
        headers={'Authorization':'Bearer backend-m1'}
        assert (await client.post('/api/v1/admin/bootstrap',headers=headers)).status_code==200
        home=(await client.get('/api/v1/portal/context',headers=headers)).json()['data']
        assert 'meeting.application.manage' in home['actions'] and 'meeting.content.read' not in home['actions']
        assert (await client.post('/api/v1/admin/bootstrap',headers=headers)).status_code==409

async def test_http_oauth_token_grants_and_code_flow(rt,human,enterprise_app_body):
    from app.core.security import pkce_challenge
    await seed(rt,human,enterprise_app_body)
    c=await rt.admin.create_client(human,ClientCreate(name='MCP native',client_type='PUBLIC_MCP',allowed_scopes=['meeting.read'],
        redirect_uris=['https://client.example.org/callback'],owner_member_id='m1',reason='Test authorization'))
    async with await client_for(rt) as client:
        params={'response_type':'code','client_id':c['id'],'redirect_uri':'https://client.example.org/callback',
            'resource':rt.settings.mcp_resource_uri,'scope':'meeting.read','state':'browser-state',
            'code_challenge':pkce_challenge('x'*64),'code_challenge_method':'S256'}
        res=await client.get('/oauth/authorize',params=params,follow_redirects=False)
        assert res.status_code==302 and '/meeting/authorize?' in res.headers['location']
        from urllib.parse import urlsplit,parse_qs
        txn=parse_qs(urlsplit(res.headers['location']).query)['transaction_id'][0]
        auth={'Authorization':'Bearer backend-m1'}
        approved=(await client.post('/api/v1/portal/authorization/'+txn+'/approve',headers=auth,json={})).json()['data']
        code=parse_qs(urlsplit(approved['redirect_uri']).query)['code'][0]
        data={'grant_type':'authorization_code','client_id':c['id'],'code':code,'code_verifier':'x'*64,
            'redirect_uri':params['redirect_uri'],'resource':params['resource']}
        res=await client.post('/oauth/token',data=data)
        assert res.status_code==200 and res.json()['token_type']=='Bearer'
        assert 'Cache-Control' in res.headers
        assert (await client.post('/oauth/token',data=data)).status_code==400
