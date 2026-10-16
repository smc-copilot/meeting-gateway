"""Tencent callbacks intentionally have raw protocol responses, not the REST business envelope."""
import asyncio
from urllib.parse import urlencode
from fastapi import APIRouter,Request,Query
from fastapi.responses import Response,RedirectResponse
from app.api.deps import runtime
from app.core.errors import MeetingError
from app.schemas.requests import StrictModel
from pydantic import Field

router=APIRouter(tags=['tencent-callbacks'])

class CallbackBody(StrictModel):
    data:str=Field(min_length=1,max_length=1048576)

def callback_headers(request):
    return {key:request.headers.get(key,'') for key in ('timestamp','nonce','signature')}

@router.get('/callbacks/tencent/events/{receiver_id}')
async def challenge(request:Request,receiver_id:str,check_str:str=Query(min_length=1,max_length=1048576)):
    try:
        value=await asyncio.wait_for(runtime(request).events.challenge(receiver_id,check_str,callback_headers(request)),timeout=2.7)
    except TimeoutError:raise MeetingError('UPSTREAM_UNAVAILABLE',503)
    return Response(value,media_type='text/plain',headers={'Cache-Control':'no-store'})

@router.post('/callbacks/tencent/events/{receiver_id}')
async def event(request:Request,receiver_id:str,body:CallbackBody):
    try:
        await asyncio.wait_for(runtime(request).events.receive(receiver_id,body.data,callback_headers(request)),timeout=4.5)
    except TimeoutError:raise MeetingError('UPSTREAM_UNAVAILABLE',503)
    return Response(b'successfully received callback',media_type='text/plain',headers={'Cache-Control':'no-store'})

@router.get('/callbacks/tencent/oauth/{application_id}')
async def oauth(request:Request,application_id:str,state:str=Query(min_length=1,max_length=64),
                auth_code:str|None=Query(None,max_length=2048),code:str|None=Query(None,max_length=2048)):
    if not (auth_code or code) or (auth_code and code and auth_code!=code):raise MeetingError('STATE_INVALID',400)
    rt=runtime(request)
    value=await rt.connections.oauth_callback(application_id,state,auth_code or code)
    target=value.get('return_to') or rt.settings.portal_base_url+'/meeting/connections'
    separator='&' if '?' in target else '?'
    return RedirectResponse(target+separator+urlencode({'connection_id':value['connection_id']}),
        status_code=303,headers={'Cache-Control':'no-store','Referrer-Policy':'no-referrer'})
