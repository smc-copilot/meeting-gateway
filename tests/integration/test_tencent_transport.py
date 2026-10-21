import httpx
import pytest
from datetime import timedelta
from sqlalchemy import select
from app.core.errors import MeetingError, UpstreamError
from app.core.types import Operator, utcnow
from app.models import Credential, Connection, Application
from app.integrations.tencent_meeting.signing import sign_request
from test_admin_connections import prepare


async def actual_transport(rt, handler):
    from app.integrations.tencent_meeting.client import TencentClient
    await rt.upstream_http.aclose()
    rt.upstream_http=httpx.AsyncClient(transport=httpx.MockTransport(handler),follow_redirects=False)
    rt._provider=None
    rt.__dict__.pop('tencent',None)
    return rt.tencent


async def test_oauth_http_500_stays_unavailable(rt):
    def handler(request):
        return httpx.Response(500, json={"code": 500, "message": "SECRET-BODY"})
    client = await actual_transport(rt, handler)
    with pytest.raises(UpstreamError, match="UPSTREAM_UNAVAILABLE"):
        await client.oauth("refresh_token", {"sdk_id": "sdk", "open_id": "open-1", "refresh_token": "refresh-1"})


async def test_resource_transport_signs_exact_wire_uri_and_bytes(rt,human,enterprise_app_body):
    a,c=await prepare(rt,human,enterprise_app_body)
    seen=[]
    def handler(request):
        seen.append(request)
        return httpx.Response(200,json={'meeting_info_list':[],'remaining':0})
    client=await actual_transport(rt,handler)
    await client.call(c['id'],'upcoming',Operator(id='external-m1',type=1),query={'pos':0,'cursory':0})
    request=seen[0]
    assert request.url.host=='api.meeting.qq.com' and request.url.path=='/v1/meetings'
    assert request.headers['AppId']=='corp' and request.headers['SdkId']=='sdk-enterprise'
    assert request.headers['X-TC-Registered']=='1' and 'AccessToken' not in request.headers
    expected=sign_request(method='GET',uri=request.url.raw_path.decode(),body=b'',secret_id='synthetic-id',
        secret_key='synthetic-key-never-live',timestamp=request.headers['X-TC-Timestamp'],nonce=request.headers['X-TC-Nonce'])
    assert request.headers['X-TC-Signature']==expected


async def test_sts_is_required_only_for_sensitive_endpoints(rt,human,enterprise_app_body):
    a,c=await prepare(rt,human,enterprise_app_body)
    seen=[]
    client=await actual_transport(rt,lambda request:(seen.append(request) or httpx.Response(200,json={})))
    with pytest.raises(MeetingError) as e:
        await client.call(c['id'],'record_detail',Operator(id='external-m1',type=1),file_id='file')
    assert e.value.reason=='STS_NOT_READY' and not seen
    await client.call(c['id'],'minutes',Operator(id='external-m1',type=1),file_id='file')
    assert '/v1/smart/minutes/file'==seen[0].url.path and 'STS-Token' not in seen[0].headers


async def test_transport_rejects_unmapped_operator_and_unknown_operation(rt,human,enterprise_app_body):
    a,c=await prepare(rt,human,enterprise_app_body)
    seen=[];client=await actual_transport(rt,lambda request:(seen.append(request) or httpx.Response(200,json={})))
    with pytest.raises(MeetingError):await client.call(c['id'],'upcoming',Operator(id='admin-not-mapped',type=1))
    with pytest.raises(MeetingError):await client.call(c['id'],'https://evil.example',Operator(id='external-m1',type=1))
    assert not seen


@pytest.mark.parametrize('response,reason',[
    (httpx.Response(302,headers={'Location':'https://evil.example'}),'UPSTREAM_CONTRACT_ERROR'),
    (httpx.Response(400,json={'error_info':{'error_code':500014,'message':'SECRET-UPSTREAM'}}),'UPSTREAM_PERMISSION_DENIED'),
    (httpx.Response(500,json={'error_info':{'error_code':190310}}),'RATE_LIMITED'),
    (httpx.Response(500,json={'error_info':{'error_code':4051}}),'SOURCE_REMOVED'),
    (httpx.Response(200,text='not json'),'UPSTREAM_CONTRACT_ERROR'),
])
async def test_upstream_errors_sanitized_no_redirect_or_fallback(rt,human,enterprise_app_body,response,reason):
    a,c=await prepare(rt,human,enterprise_app_body)
    seen=[];client=await actual_transport(rt,lambda request:(seen.append(request) or response))
    with pytest.raises(UpstreamError) as e:await client.call(c['id'],'upcoming',Operator(id='external-m1',type=1))
    assert e.value.reason==reason and len(seen)==1 and 'SECRET' not in str(e.value.payload('t'))


async def test_creation_transport_timeout_is_uncertain(rt,human,enterprise_app_body):
    a,c=await prepare(rt,human,enterprise_app_body)
    def handler(request):raise httpx.ReadTimeout('not exposed')
    client=await actual_transport(rt,handler)
    with pytest.raises(UpstreamError) as e:
        await client.call(c['id'],'create',Operator(id='external-m1',type=1),body={'userid':'external-m1','subject':'demo'})
    assert e.value.uncertain


async def test_oauth_raw_endpoint_and_explicit_body(rt):
    requests=[]
    client=await actual_transport(rt,lambda request:(requests.append(request) or httpx.Response(200,json={'code':0,'data':{'open_id':'x'}})))
    assert await client.oauth('user_info',{'access_token':'private','open_id':'x'})=={'open_id':'x'}
    assert requests[0].url.path=='/wemeet-webapi/v2/oauth2/oauth/user_info'
    assert 'private' not in str(requests[0].url)


async def test_participants_oauth_path_uses_userid_open_id(rt,human,enterprise_app_body):
    from app.schemas.requests import ApplicationCreate
    from urllib.parse import urlsplit, parse_qs
    await rt.admin.bootstrap(human)
    data=enterprise_app_body.model_dump()
    data.update(application_type='THIRD_PARTY_OAUTH',sdk_id='oauth-sdk',data_scope='user',secret_id=None,secret_key=None,
                oauth_secret='oauth-client-test-secret',allowed_open_corp_ids=['open-corp'])
    app=await rt.admin.create_application(human,ApplicationCreate(**data))
    start=await rt.connections.oauth_start(human,app['id'])
    state=parse_qs(urlsplit(start['authorization_url']).query)['state'][0]
    callback=await rt.connections.oauth_callback(app['id'],state,'auth-code')
    await rt.connections.confirm_oauth(human,callback['connection_id'])
    seen=[]
    client=await actual_transport(rt,lambda request:(seen.append(request) or httpx.Response(200,json={'participants':[],'has_remaining':False})))
    await client.call(callback['connection_id'],'participants',Operator(id='open-m1',type=2),file_id='mtg-1',query={'pos':0,'size':20})
    assert seen[0].url.path=='/v1/meetings/mtg-1/participants'
    assert seen[0].url.params['userid']=='open-m1'
    assert 'AccessToken' in seen[0].headers and 'OpenId' in seen[0].headers
    assert 'X-TC-Signature' not in seen[0].headers


async def test_user_basic_oauth_path_and_aksk_blocked(rt,human,enterprise_app_body):
    from app.schemas.requests import ApplicationCreate
    from urllib.parse import urlsplit, parse_qs
    a,c=await prepare(rt,human,enterprise_app_body)
    data=enterprise_app_body.model_dump()
    data.update(application_type='THIRD_PARTY_OAUTH',sdk_id='oauth-sdk-basic',data_scope='user',secret_id=None,secret_key=None,
                oauth_secret='oauth-client-test-secret',allowed_open_corp_ids=['open-corp'],name='OAuth basic info')
    app=await rt.admin.create_application(human,ApplicationCreate(**data))
    start=await rt.connections.oauth_start(human,app['id'])
    state=parse_qs(urlsplit(start['authorization_url']).query)['state'][0]
    callback=await rt.connections.oauth_callback(app['id'],state,'auth-code')
    await rt.connections.confirm_oauth(human,callback['connection_id'])
    seen=[]
    client=await actual_transport(rt,lambda request:(seen.append(request) or httpx.Response(200,json={'username':'nick'})))
    raw=await client.call(callback['connection_id'],'user_basic',Operator(id='open-m1',type=2),
                          query={'operator_id':'open-other'})
    assert raw['username']=='nick'
    assert seen[0].url.path=='/v1/users/info/basic'
    assert seen[0].url.params['operator_id']=='open-other'
    assert seen[0].url.params['operator_id_type']=='2'
    before=len(seen)
    with pytest.raises(MeetingError) as e:
        await client.call(c['id'],'user_basic',Operator(id='external-m1',type=1),query={'operator_id':'anyone'})
    assert e.value.reason=='UPSTREAM_CAPABILITY_UNAVAILABLE' and len(seen)==before



async def test_resource_body_size_limit(rt,human,enterprise_app_body):
    a,c=await prepare(rt,human,enterprise_app_body)
    rt.settings.max_upstream_json_bytes=1024
    client=await actual_transport(rt,lambda request:httpx.Response(200,content=b'{"padding":"'+b'x'*2048+b'"}'))
    with pytest.raises(UpstreamError) as e:await client.call(c['id'],'upcoming',Operator(id='external-m1',type=1))
    assert e.value.reason=='UPSTREAM_CONTRACT_ERROR'


async def test_corporate_rate_limiter_is_shared_in_database(rt):
    from app.services.rate_service import RateService
    one=RateService(rt);two=RateService(rt)
    await one.acquire('enterprise-records-test',6)
    with pytest.raises(MeetingError) as e:await two.acquire('enterprise-records-test',6)
    assert e.value.reason=='RATE_LIMITED' and e.value.retry_after>=1
