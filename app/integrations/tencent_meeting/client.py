"""Fixed Tencent Meeting transport. Never expose an arbitrary URL, operator or signing endpoint.

Upstream contracts are recorded in docs/upstream-contracts.md. Requests are never
retried here, especially POST /meetings: a network timeout may already have created it.
"""
import json
import secrets
import time
from urllib.parse import quote
import httpx
from sqlalchemy import select
from app.core.errors import MeetingError, UpstreamError
from app.core.security import canonical
from app.core.types import Operator
from app.models import Connection, Application, IdentityBinding
from app.integrations.tencent_meeting.signing import sign_request

API_ORIGIN='https://api.meeting.qq.com'
OAUTH_ORIGIN='https://meeting.tencent.com/wemeet-webapi/v2/oauth2/oauth/'
OPERATIONS=frozenset({'upcoming','history','records','corp_records','record_detail','transcript','minutes','create','sts','meeting','participants','user_basic'})
QUERY_FIELDS={
 'upcoming':{'pos','cursory'},'history':{'start_time','end_time','page','page_size'},
 'records':{'start_time','end_time','page','page_size','meeting_id'},
 'corp_records':{'start_time','end_time','page','page_size'},
 'record_detail':set(),'transcript':{'pid','limit','meeting_id'},
 'minutes':{'llm','minute_type','text_type','lang'},'create':set(),'sts':set(),'meeting':set(),
 'participants':{'pos','size','sub_meeting_id','start_time','end_time'},
 'user_basic':{'operator_id'},
}


def _external(value):
    if not isinstance(value,str) or not 1<=len(value)<=128:raise MeetingError('INVALID_REQUEST',422)
    return quote(value,safe='')


class TencentClient:
    def __init__(self,runtime):self.rt=runtime

    def _raise_upstream(self,code,status,*,credential_channel,write):
        if code in {'190311','190312'}:
            raise UpstreamError('UPSTREAM_DAILY_QUOTA',upstream_code=code,budgeted=True)
        if code=='190310' or status==429:
            raise UpstreamError('RATE_LIMITED',upstream_code=code,retry_after=60)
        if code=='190300':
            raise UpstreamError('UPSTREAM_CLOCK_SKEW',upstream_code=code,budgeted=False)
        if code=='190325':
            raise UpstreamError('UPSTREAM_CAPABILITY_UNAVAILABLE',upstream_code=code,budgeted=False)
        if code=='190303':
            reason='UPSTREAM_REAUTH_REQUIRED' if credential_channel else 'UPSTREAM_CREDENTIAL_INVALID'
            raise UpstreamError(reason,upstream_code=code,budgeted=False)
        if code=='30003':
            raise UpstreamError('CONTENT_NOT_READY',upstream_code=code)
        if code in {'30001','30002'}:
            raise UpstreamError('CONTENT_ABSENT',upstream_code=code,budgeted=False)
        if code in {'4051','4049'} or status==404:
            raise UpstreamError('SOURCE_REMOVED',upstream_code=code,budgeted=False)
        if code in {'500014','9042','403','9100','9099'} or status==403:
            raise UpstreamError('UPSTREAM_PERMISSION_DENIED',upstream_code=code,budgeted=False)
        if status>=500:
            raise UpstreamError('UPSTREAM_UNAVAILABLE',upstream_code=code,budgeted=False,
                                uncertain=write or code in {'41','960000'})
        if status==401:
            reason='UPSTREAM_REAUTH_REQUIRED' if credential_channel else 'UPSTREAM_CREDENTIAL_INVALID'
            raise UpstreamError(reason,upstream_code=code,budgeted=False)
        raise UpstreamError('UPSTREAM_UNAVAILABLE',upstream_code=code,uncertain=write and code in {'41','960000'})

    async def _send(self,method,url,headers,body,*,envelope=False,credential_channel=False,write=False):
        try:
            async with self.rt.upstream_http.stream(method,url,headers=headers,content=body) as response:
                if 300<=response.status_code<400:raise UpstreamError('UPSTREAM_CONTRACT_ERROR',uncertain=write)
                data=bytearray()
                async for chunk in response.aiter_bytes():
                    data.extend(chunk)
                    if len(data)>self.rt.settings.max_upstream_json_bytes:
                        raise UpstreamError('UPSTREAM_CONTRACT_ERROR',uncertain=write)
                try:result=json.loads(data)
                except (ValueError,UnicodeError) as exc:raise UpstreamError('UPSTREAM_CONTRACT_ERROR',uncertain=write) from exc
                if not isinstance(result,dict):raise UpstreamError('UPSTREAM_CONTRACT_ERROR',uncertain=write)
                error=result.get('error_info')
                error=error if isinstance(error,dict) else {}
                code=str(error.get('error_code',result.get('code',0)))
                if response.status_code>=400 or code not in {'0','None',''}:
                    self._raise_upstream(code,response.status_code,credential_channel=credential_channel,write=write)
                if envelope:
                    if not isinstance(result.get('data'),dict):raise UpstreamError('UPSTREAM_CONTRACT_ERROR')
                    return result['data']
                return result
        except (httpx.TimeoutException,httpx.NetworkError,httpx.RemoteProtocolError) as exc:
            raise UpstreamError('UPSTREAM_UNAVAILABLE',uncertain=write) from exc

    async def oauth(self,operation,payload):
        allowed={
            'access_token':{'sdk_id','secret','auth_code'},
            'refresh_token':{'sdk_id','open_id','refresh_token'},
            'user_info':{'open_id','access_token'},
        }
        if operation not in allowed or set(payload)!=allowed[operation]:raise MeetingError('INVALID_REQUEST',422)
        return await self._send('POST',OAUTH_ORIGIN+operation,{'Content-Type':'application/json'},canonical(payload),
                                 envelope=True,credential_channel=True)

    async def admit(self,connection_id,operation,*,heartbeat=None):
        async with self.rt.db.session() as s:
            c=await s.get(Connection,connection_id)
            if not c:raise MeetingError('UPSTREAM_REAUTH_REQUIRED',409)
            app_id=c.application_id
        await self.rt.rate.acquire('tencent-app:'+app_id,self.rt.settings.upstream_min_interval_seconds,heartbeat=heartbeat)
        if operation=='corp_records':
            await self.rt.rate.acquire('tencent-corp-records:'+app_id,self.rt.settings.corp_records_min_interval_seconds,heartbeat=heartbeat)

    async def call(self,connection_id,operation,operator:Operator,*,query=None,body=None,file_id=None,heartbeat=None,admitted=False):
        if operation not in OPERATIONS:raise MeetingError('INVALID_REQUEST',422)
        query=dict(query or {})
        if set(query)-QUERY_FIELDS[operation]:raise MeetingError('INVALID_REQUEST',422)
        async with self.rt.db.session() as s:
            c=await s.get(Connection,connection_id)
            if not c or c.deleted_at is not None or c.status not in {'ACTIVE','DEGRADED'} or not c.corporate_verified:
                raise MeetingError('UPSTREAM_REAUTH_REQUIRED',409)
            app=await s.get(Application,c.application_id)
            if not app or not app.enabled or app.deleted_at is not None or c.kind!=app.application_type:
                raise MeetingError('UPSTREAM_REAUTH_REQUIRED',409)
            if c.kind=='THIRD_PARTY_OAUTH':
                if operator.type!=2 or operator.id!=c.external_id:raise MeetingError('PERMISSION_DENIED',403)
                if operation in {'corp_records','sts'}:raise MeetingError('UPSTREAM_CAPABILITY_UNAVAILABLE',409)
                material=None
            else:
                if operation=='user_basic':raise MeetingError('UPSTREAM_CAPABILITY_UNAVAILABLE',409)
                if operator.type!=1:raise MeetingError('IDENTITY_UNBOUND',409)
                mapping=await s.scalar(select(IdentityBinding).where(IdentityBinding.application_id==app.id,
                    IdentityBinding.org_id==c.org_id,IdentityBinding.external_id==operator.id,
                    IdentityBinding.identity_type=='userid',IdentityBinding.enabled.is_(True),IdentityBinding.deleted_at.is_(None)))
                if mapping is None:raise MeetingError('IDENTITY_UNBOUND',409)
                await self.rt.identity.require_member(c.org_id,mapping.member_id)
                _,material=await self.rt.admin.read_secret(s,app,'AKSK')
        method='POST' if operation in {'create','sts'} else 'GET'
        if operation=='upcoming':path='/v1/meetings';query.update(userid=operator.id,instanceid=1)
        elif operation=='history':path='/v1/history/meetings/'+_external(operator.id)
        elif operation=='records':path='/v1/records';query.update(operator_id=operator.id,operator_id_type=operator.type)
        elif operation=='corp_records':path='/v1/corp/records';query.update(operator_id=operator.id,operator_id_type=operator.type)
        elif operation=='record_detail':path='/v1/addresses/'+_external(file_id);query.update(operator_id=operator.id,operator_id_type=operator.type)
        elif operation=='transcript':path='/v1/records/transcripts/details';query.update(record_file_id=file_id,operator_id=operator.id,operator_id_type=operator.type)
        elif operation=='minutes':path='/v1/smart/minutes/'+_external(file_id);query.update(operator_id=operator.id,operator_id_type=operator.type)
        elif operation=='meeting':
            path='/v1/meetings/'+_external(file_id);query.update(userid=operator.id,instanceid=1)
        elif operation=='participants':
            path='/v1/meetings/'+_external(file_id)+'/participants';query.update(userid=operator.id)
        elif operation=='user_basic':
            # GET /v1/users/info/basic — OAuth only; needs VIEW_USER_BASIC_INFO.
            # operator_id is the target open_id (not the caller).
            path='/v1/users/info/basic'
            target=str(query.get('operator_id') or '')
            if not 1<=len(target)<=128:raise MeetingError('INVALID_REQUEST',422)
            query={'operator_id':target,'operator_id_type':2}
        elif operation=='create':
            path='/v1/meetings'
            if not isinstance(body,dict) or body.get('userid')!=operator.id:raise MeetingError('INVALID_REQUEST',422)
        elif operation=='sts':
            path='/v1/app/sts-token'
            if not isinstance(body,dict) or body.get('operator_id')!=operator.id or body.get('operator_id_type')!=operator.type:
                raise MeetingError('INVALID_REQUEST',422)
        else:
            raise MeetingError('INVALID_REQUEST',422)
        if file_id is not None:_external(file_id)
        url=httpx.URL(API_ORIGIN+path,params=query)
        raw=canonical(body) if method=='POST' else b''
        nonce=str(secrets.randbelow(2**31-1)+1);timestamp=str(int(time.time()))
        headers={'Content-Type':'application/json','X-TC-Timestamp':timestamp,'X-TC-Nonce':nonce,'X-TC-Registered':'1'}
        if material:
            headers.update({'X-TC-Key':material['secret_id'],'AppId':app.tencent_corp_id,'SdkId':app.sdk_id,
                'X-TC-Signature':sign_request(material['secret_id'],material['secret_key'],method,
                                            url.raw_path.decode('ascii'),raw,nonce,timestamp)})
            if operation in {'record_detail','transcript'}:
                headers['STS-Token']=await self.rt.connections.sts_token(c.id)
        else:
            token=await self.rt.connections.oauth_credentials(c.id)
            headers.update({'AccessToken':token['access_token'],'OpenId':c.external_id})
        if not admitted:await self.admit(connection_id,operation,heartbeat=heartbeat)
        self.rt.metrics['upstream_calls']+=1
        return await self._send(method,url,headers,raw,credential_channel=c.kind=='THIRD_PARTY_OAUTH',write=operation=='create')
