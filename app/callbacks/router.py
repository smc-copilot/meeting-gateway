"""Tencent callbacks intentionally have raw protocol responses, not the REST business envelope."""
import asyncio
from urllib.parse import urlencode
from fastapi import APIRouter,Request,Query
from fastapi.responses import Response,RedirectResponse
from sqlalchemy import select
from app.api.deps import runtime
from app.core.errors import MeetingError
from app.models import Application
from app.schemas.requests import StrictModel
from pydantic import Field

router=APIRouter(tags=['tencent-callbacks'])

async def env_application(rt, ref):
    """Map the configured numeric sdk_id alias to the ENV application. Other refs stay UUID routes."""
    if not ref or ref != rt.settings.tencent_meeting_app_id:
        return None
    async with rt.db.session() as session:
        app = await session.scalar(select(Application).where(Application.sdk_id == ref,
            Application.enabled.is_(True), Application.deleted_at.is_(None)))
        if app is None or (app.settings_data or {}).get("owner") != "ENV":
            raise MeetingError("RESOURCE_NOT_ACCESSIBLE", 404)
        return app.id, app.receiver_id

class CallbackBody(StrictModel):
    data:str=Field(min_length=1,max_length=1048576)

def callback_headers(request):
    return {key:request.headers.get(key,'') for key in ('timestamp','nonce','signature')}

@router.get('/callbacks/tencent/events/{receiver_id}')
async def challenge(request:Request,receiver_id:str,check_str:str=Query(min_length=1,max_length=1048576)):
    rt=runtime(request)
    app=await env_application(rt,receiver_id)
    try:
        value=await asyncio.wait_for(rt.events.challenge(app[1] if app else receiver_id,check_str,callback_headers(request)),timeout=2.7)
    except TimeoutError:raise MeetingError('UPSTREAM_UNAVAILABLE',503)
    return Response(value,media_type='text/plain',headers={'Cache-Control':'no-store'})

@router.post('/callbacks/tencent/events/{receiver_id}')
async def event(request:Request,receiver_id:str,body:CallbackBody):
    rt=runtime(request)
    app=await env_application(rt,receiver_id)
    try:
        await asyncio.wait_for(rt.events.receive(app[1] if app else receiver_id,body.data,callback_headers(request)),timeout=4.5)
    except TimeoutError:raise MeetingError('UPSTREAM_UNAVAILABLE',503)
    return Response(b'successfully received callback',media_type='text/plain',headers={'Cache-Control':'no-store'})

@router.get('/callbacks/tencent/oauth/{application_id}')
async def oauth(request:Request,application_id:str,state:str=Query(min_length=1,max_length=64),
                auth_code:str|None=Query(None,max_length=2048),code:str|None=Query(None,max_length=2048)):
    if not (auth_code or code) or (auth_code and code and auth_code!=code):raise MeetingError('STATE_INVALID',400)
    rt=runtime(request)
    app=await env_application(rt,application_id)
    value=await rt.connections.oauth_callback(app[0] if app else application_id,state,auth_code or code)
    target=value.get('return_to') or rt.settings.public_base_url+'/oauth/tencent/result'
    separator='&' if '?' in target else '?'
    return RedirectResponse(target+separator+urlencode({'connection_id':value['connection_id']}),
        status_code=303,headers={'Cache-Control':'no-store','Referrer-Policy':'no-referrer'})

@router.get('/oauth/tencent/result')
async def oauth_result():
    page = '<!doctype html><meta charset="utf-8"><title>授权结果</title><p>授权已返回网关。请回到原业务系统查看结果。本页不包含令牌。</p>'
    return Response(page, media_type='text/html', headers={'Cache-Control':'no-store','Referrer-Policy':'no-referrer'})
