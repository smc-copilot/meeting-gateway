from fastapi import Request, Depends
from fastapi.security import HTTPBearer,HTTPAuthorizationCredentials
from app.core.errors import MeetingError

bearer=HTTPBearer(auto_error=False,scheme_name='MeetingBearer',description='Audience-bound Meeting access token')
human_bearer=HTTPBearer(auto_error=False,scheme_name='BackendBearer',description='Existing Backend employee session; not a Meeting token')

def runtime(request:Request):return request.app.state.runtime

def envelope(request:Request,data=None):
    return {'code':0,'error_code':0,'message_key':'common.success','message':'success','data':data,
            'trace_id':getattr(request.state,'trace_id','')}

async def business(request:Request,credentials:HTTPAuthorizationCredentials|None=Depends(bearer)):
    if not credentials:raise MeetingError('AUTH_REQUIRED',401)
    rt=runtime(request)
    p=await rt.auth.authenticate(credentials.credentials,rt.settings.rest_resource_uri,trace_id=request.state.trace_id)
    request.state.principal=p
    return p

async def mcp_principal(request:Request,credentials:HTTPAuthorizationCredentials|None=Depends(bearer)):
    if not credentials:raise MeetingError('AUTH_REQUIRED',401)
    rt=runtime(request)
    p=await rt.auth.authenticate(credentials.credentials,rt.settings.mcp_resource_uri,trace_id=request.state.trace_id)
    request.state.principal=p
    return p

async def human(request:Request,credentials:HTTPAuthorizationCredentials|None=Depends(human_bearer)):
    if not credentials:raise MeetingError('AUTH_REQUIRED',401)
    p=await runtime(request).auth.portal_principal(credentials.credentials,request.state.trace_id)
    request.state.principal=p
    return p
