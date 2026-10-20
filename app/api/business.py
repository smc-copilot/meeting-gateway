from fastapi import APIRouter,Request,Depends,Query,Header
from starlette.responses import StreamingResponse
from starlette.background import BackgroundTask
from app.api.deps import business,runtime,envelope
from app.core.errors import MeetingError
from fastapi.responses import JSONResponse
from app.schemas.requests import (MeetingCreate,SyncRequest,DownloadRequest,MeetingQuery,OperationConfirm,
                                  OperationReject,OAuthSession)
from app.services.portal_service import PortalService
from app.authorization.router import client_auth,throttle

router=APIRouter(tags=['meeting-business'])

@router.get('/me/permissions')
async def permissions(request:Request,p=Depends(business)):
    return envelope(request,await PortalService(runtime(request)).permissions(p))

@router.get('/me/connections')
async def connections(request:Request,p=Depends(business)):
    return envelope(request,await PortalService(runtime(request)).connections(p))

@router.get('/meetings')
async def meetings(request:Request,limit:int=Query(20,ge=1,le=100),cursor:str|None=Query(None,max_length=4096),
                   q:str=Query('',max_length=200),connection_ref:str|None=Query(None,max_length=64),p=Depends(business)):
    return envelope(request,await runtime(request).meetings.list(p,limit=limit,cursor=cursor,query=q,connection_ref=connection_ref))

def maybe_accepted(request,result):
    if isinstance(result,dict) and result.get('accepted'):
        return JSONResponse(envelope(request,result),status_code=202)
    return envelope(request,result)

@router.get('/meetings/{meeting_id}')
async def meeting(request:Request,meeting_id:str,fetch:str=Query('ensure'),p=Depends(business)):
    if fetch not in {'ensure','cache'}:raise MeetingError('INVALID_REQUEST',422)
    return maybe_accepted(request,await runtime(request).meetings.get(p,meeting_id,fetch=fetch))

@router.post('/meetings',status_code=202)
async def create(request:Request,body:MeetingCreate,idempotency_key:str=Header(alias='Idempotency-Key',min_length=1,max_length=128),p=Depends(business)):
    return envelope(request,await runtime(request).operations.prepare(p,body,idempotency_key))

@router.post('/meeting-queries',status_code=202)
async def meeting_queries(request:Request,body:MeetingQuery,p=Depends(business)):
    return envelope(request,await runtime(request).queries.submit(p,body))

@router.get('/oauth/authorizations')
async def oauth_authorization(request:Request,continue_to:str|None=Query(None,max_length=2048),
                              return_to:str|None=Query(None,max_length=2048),
                              application_id:str=Query('',max_length=64)):
    await throttle(request)
    host=request.client.host if request.client else ''
    return envelope(request,await runtime(request).connections.oauth_start_public(
        application_id or '',continue_to or return_to,client_host=host))

@router.post('/oauth/sessions',status_code=201)
async def oauth_sessions(request:Request,body:OAuthSession):
    await throttle(request)
    client_id,secret=client_auth(request,body.model_dump())
    return envelope(request,await runtime(request).auth.oauth_session(
        client_id,secret,body.authorization_code,body.scopes or None))

@router.post('/connections/{connection_id}/confirm')
async def confirm_connection(request:Request,connection_id:str,p=Depends(business)):
    return envelope(request,await runtime(request).connections.confirm_oauth_member(p,connection_id))

@router.get('/meetings/{meeting_id}/recordings')
async def recordings(request:Request,meeting_id:str,fetch:str=Query('ensure'),p=Depends(business)):
    if fetch not in {'ensure','cache'}:raise MeetingError('INVALID_REQUEST',422)
    if fetch=='ensure':
        job_id=await runtime(request).queries.ensure_recordings(p,meeting_id)
        if job_id:
            return JSONResponse(envelope(request,{'accepted':True,'job_id':job_id,'resource':'recordings'}),status_code=202)
    result=await runtime(request).meetings.recordings(p,meeting_id)
    result['upstream_checked']=fetch=='ensure'
    return envelope(request,result)

@router.get('/recordings/{recording_id}/transcript')
async def transcript(request:Request,recording_id:str,limit:int=Query(100,ge=1,le=500),cursor:str|None=Query(None,max_length=4096),
                     fetch:str=Query('ensure'),p=Depends(business)):
    if fetch not in {'ensure','cache'}:raise MeetingError('INVALID_REQUEST',422)
    return maybe_accepted(request,await runtime(request).content.read(p,recording_id,'transcript',limit=limit,cursor=cursor,fetch=fetch))

@router.get('/recordings/{recording_id}/minutes')
async def minutes(request:Request,recording_id:str,fetch:str=Query('ensure'),p=Depends(business)):
    if fetch not in {'ensure','cache'}:raise MeetingError('INVALID_REQUEST',422)
    return maybe_accepted(request,await runtime(request).content.read(p,recording_id,'minutes',fetch=fetch))

@router.post('/assets/{asset_id}/download-tickets',status_code=201)
async def download_ticket(request:Request,asset_id:str,body:DownloadRequest,p=Depends(business)):
    return envelope(request,await runtime(request).downloads.issue(p,asset_id,body.purpose))

@router.get('/downloads/{ticket}')
async def download(request:Request,ticket:str,p=Depends(business)):
    stream=await runtime(request).downloads.open(p,ticket,request.headers.get('range'))
    return StreamingResponse(stream.iterate(),status_code=stream.status,headers=stream.headers,
        media_type=stream.media_type,background=BackgroundTask(stream.close))

@router.post('/sync-jobs',status_code=202)
async def sync_job(request:Request,body:SyncRequest,p=Depends(business)):
    return envelope(request,await runtime(request).sync.request(p,body))

@router.get('/jobs/{job_id}')
async def job(request:Request,job_id:str,p=Depends(business)):
    return envelope(request,await runtime(request).jobs.get(p,job_id))

@router.get('/operations/{operation_id}')
async def operation(request:Request,operation_id:str,p=Depends(business)):
    return envelope(request,await runtime(request).operations.get(p,operation_id))

@router.post('/operations/{operation_id}/confirm')
async def confirm_operation(request:Request,operation_id:str,body:OperationConfirm,p=Depends(business)):
    return envelope(request,await runtime(request).operations.confirm_business(p,operation_id,body.request_hash))

@router.post('/operations/{operation_id}/reject')
async def reject_operation(request:Request,operation_id:str,body:OperationReject,p=Depends(business)):
    if p.actor_type!='MEMBER':raise MeetingError('PERMISSION_DENIED',403)
    return envelope(request,await runtime(request).operations.reject_business(p,operation_id,body.reason))
