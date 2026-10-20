"""Private registered-client OAuth facade over Backend identity. No employee passwords are stored here."""
import base64
from urllib.parse import unquote_plus
from fastapi import APIRouter,Request,Query
from fastapi.responses import JSONResponse,RedirectResponse,Response
from pydantic import ValidationError
from app.api.deps import runtime,envelope
from app.schemas.control import TokenForm,ExchangeRequest
from app.core.errors import MeetingError
from app.services.permission_service import BUSINESS_ACTIONS

router=APIRouter(tags=['meeting-authorization'])
NO_STORE={'Cache-Control':'no-store','Pragma':'no-cache','Referrer-Policy':'no-referrer'}

async def throttle(request):
    rt=runtime(request)
    if rt.settings.environment!='test':
        await rt.rate.acquire('auth-ip:'+(request.client.host if request.client else 'unknown'),0.05)

def client_auth(request,data):
    header=request.headers.get('authorization','')
    client_id,secret=data.get('client_id'),data.get('client_secret')
    if header:
        if not header.lower().startswith('basic ') or client_id or secret:
            raise MeetingError('TOKEN_INVALID',401)
        try:
            raw=base64.b64decode(header[6:],validate=True).decode('utf-8')
            client_id,secret=map(unquote_plus,raw.split(':',1))
        except (ValueError,UnicodeError):raise MeetingError('TOKEN_INVALID',401)
    if not client_id or len(client_id)>64 or (secret and len(secret)>512):raise MeetingError('TOKEN_INVALID',401)
    return client_id,secret

def oauth_error(error):
    status=400
    reason={'TOKEN_INVALID':'invalid_client','AUTH_REQUIRED':'invalid_client','PERMISSION_DENIED':'invalid_scope',
        'AUDIENCE_MISMATCH':'invalid_target','STATE_INVALID':'invalid_grant','REFRESH_REUSE':'invalid_grant',
        'MEMBER_INACTIVE':'invalid_grant','RATE_LIMITED':'temporarily_unavailable',
        'IDENTITY_SERVICE_UNAVAILABLE':'temporarily_unavailable'}.get(error.reason,'invalid_request')
    if reason=='invalid_client':status=401
    elif reason=='temporarily_unavailable':status=503
    return JSONResponse({'error':reason,'error_description':error.reason},status_code=status,headers=NO_STORE)

@router.get('/.well-known/oauth-authorization-server')
async def metadata(request:Request):
    cfg=runtime(request).settings;base=cfg.public_base_url
    return {'issuer':base,'authorization_endpoint':base+'/oauth/authorize','token_endpoint':base+'/oauth/token',
        'revocation_endpoint':base+'/oauth/revoke','response_types_supported':['code'],
        'grant_types_supported':['authorization_code','refresh_token','client_credentials'],
        'token_endpoint_auth_methods_supported':['client_secret_basic','client_secret_post','none'],
        'code_challenge_methods_supported':['S256'],'scopes_supported':sorted(BUSINESS_ACTIONS)}

@router.get('/.well-known/oauth-protected-resource')
@router.get('/.well-known/oauth-protected-resource/mcp')
async def mcp_resource(request:Request):
    cfg=runtime(request).settings
    return {'resource':cfg.mcp_resource_uri,'authorization_servers':[cfg.public_base_url],
        'scopes_supported':sorted(BUSINESS_ACTIONS),'bearer_methods_supported':['header']}

@router.get('/.well-known/oauth-protected-resource/api/v1')
async def rest_resource(request:Request):
    cfg=runtime(request).settings
    return {'resource':cfg.rest_resource_uri,'authorization_servers':[cfg.public_base_url],
        'scopes_supported':sorted(BUSINESS_ACTIONS),'bearer_methods_supported':['header']}

@router.get('/oauth/authorize')
async def authorize(request:Request,client_id:str=Query(max_length=64),redirect_uri:str=Query(max_length=1024),
    resource:str=Query(max_length=512),scope:str=Query(max_length=1024),state:str=Query(max_length=512),
    code_challenge:str=Query(max_length=128),code_challenge_method:str=Query(max_length=16),response_type:str=Query(max_length=16)):
    try:
        await throttle(request)
        result=await runtime(request).auth.begin_authorization(client_id=client_id,redirect_uri=redirect_uri,
            resource=resource,scope=scope,state=state,code_challenge=code_challenge,
            code_challenge_method=code_challenge_method,response_type=response_type)
        return RedirectResponse(result['consent_uri'],status_code=302,headers=NO_STORE)
    except MeetingError as exc:return oauth_error(exc)

@router.post('/oauth/token')
async def token(request:Request):
    try:
        await throttle(request)
        if request.headers.get('content-type','').split(';')[0]!='application/x-www-form-urlencoded':
            raise MeetingError('INVALID_REQUEST',400)
        form=await request.form()
        if any(len(form.getlist(key))!=1 for key in form):raise MeetingError('INVALID_REQUEST',400)
        body=TokenForm.model_validate(dict(form))
        client_id,secret=client_auth(request,body.model_dump())
        auth=runtime(request).auth
        if body.grant_type=='authorization_code':
            if not all([body.code,body.code_verifier,body.redirect_uri]):raise MeetingError('INVALID_REQUEST',400)
            value=await auth.authorization_code(client_id,secret,body.code,body.code_verifier,body.redirect_uri,body.resource)
        elif body.grant_type=='refresh_token':
            if not body.refresh_token:raise MeetingError('INVALID_REQUEST',400)
            value=await auth.refresh(client_id,secret,body.refresh_token,body.resource)
        else:
            value=await auth.client_credentials(client_id,secret,body.scope.split(),body.resource)
        return JSONResponse(value,headers=NO_STORE)
    except ValidationError:return oauth_error(MeetingError('INVALID_REQUEST',400))
    except MeetingError as exc:return oauth_error(exc)

@router.post('/oauth/revoke')
async def revoke(request:Request):
    try:
        await throttle(request)
        form=await request.form()
        if set(form)-{'token','client_id','client_secret','token_type_hint'} or any(len(form.getlist(k))!=1 for k in form):
            raise MeetingError('INVALID_REQUEST',400)
        client_id,secret=client_auth(request,dict(form))
        value=form.get('token','')
        if not isinstance(value,str) or not 1<=len(value)<=256:raise MeetingError('INVALID_REQUEST',400)
        await runtime(request).auth.revoke(client_id,secret,value)
        return Response(status_code=200,headers=NO_STORE)
    except MeetingError as exc:return oauth_error(exc)

@router.post('/api/v1/auth/exchange')
async def exchange(request:Request,body:ExchangeRequest):
    await throttle(request)
    raise MeetingError('AUTH_EXCHANGE_DISABLED',410)
