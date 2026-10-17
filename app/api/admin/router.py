from fastapi import APIRouter,Request,Depends,Query
from sqlalchemy import select
from app.api.deps import runtime,envelope,human
from app.schemas.requests import ApplicationCreate,EnterpriseConnectionCreate,IdentityBind,GrantCreate,ClientCreate,ACLCreate,Reason
from app.schemas.control import Retention,STSGenerate,Diagnostic,AdminSync,PolicyCreate,SubscriptionCreate
from app.services.diagnostic_service import DiagnosticService
from app.models import Application,Connection,Client,AccessGrant,AgentGrant,SyncPolicy,SyncJob
from app.core.errors import MeetingError
from app.services.audit_service import record

router=APIRouter(prefix='/admin',tags=['meeting-admin'])

@router.post('/bootstrap')
async def bootstrap(request:Request,p=Depends(human)):
    return envelope(request,await runtime(request).admin.bootstrap(p))

@router.post('/applications',status_code=201)
async def application(request:Request,body:ApplicationCreate,p=Depends(human)):
    return envelope(request,await runtime(request).admin.create_application(p,body))

@router.put('/applications/{application_id}/credentials')
async def rotate_application(request:Request,application_id:str,body:ApplicationCreate,p=Depends(human)):
    return envelope(request,await runtime(request).admin.rotate_application(p,application_id,body))

@router.get('/applications/{application_id}/setup')
async def setup(request:Request,application_id:str,p=Depends(human)):
    rt=runtime(request)
    async with rt.db.session() as s:
        await rt.admin.require(s,p,'meeting.application.manage')
        app=await rt.admin._get(s,Application,p.org_id,application_id)
        env_alias=(app.settings_data or {}).get('owner')=='ENV' and bool(app.sdk_id)
        oauth_ref=app.sdk_id if env_alias else app.id
        event_ref=app.sdk_id if env_alias else app.receiver_id
        webhook=rt.settings.public_base_url+'/callbacks/tencent/events/'+event_ref
        return envelope(request,{'webhook_url':webhook,'webhook_callback_url':webhook,
            'oauth_callback_url':rt.settings.public_base_url+'/callbacks/tencent/oauth/'+oauth_ref,
            'configure_egress_ip_in_tencent_console':True,'official_debug_configuration_is_manual':True,
            'webhook_verified_at':app.webhook_verified_at,'last_callback_at':app.last_callback_at})

@router.post('/connections/enterprise',status_code=201)
async def enterprise(request:Request,body:EnterpriseConnectionCreate,p=Depends(human)):
    return envelope(request,await runtime(request).connections.create_enterprise(p,body))

@router.post('/connections/{connection_id}/sts',status_code=202)
async def sts(request:Request,connection_id:str,body:STSGenerate,p=Depends(human)):
    return envelope(request,await runtime(request).connections.request_sts(p,connection_id,body.valid_hours))

@router.post('/connections/{connection_id}/diagnostics')
async def diagnostics(request:Request,connection_id:str,body:Diagnostic,p=Depends(human)):
    return envelope(request,await DiagnosticService(runtime(request)).run(p,connection_id,body.probe,body.recording_id))

@router.get('/events')
async def events(request:Request,limit:int=Query(50,ge=1,le=100),p=Depends(human)):
    return envelope(request,await DiagnosticService(runtime(request)).events(p,limit))

@router.post('/identity-bindings',status_code=201)
async def identity(request:Request,body:IdentityBind,p=Depends(human)):
    return envelope(request,await runtime(request).admin.bind_identity(p,body))

@router.post('/grants',status_code=201)
async def grant(request:Request,body:GrantCreate,p=Depends(human)):
    return envelope(request,await runtime(request).admin.create_grant(p,body))

@router.post('/resource-acl',status_code=201)
async def acl(request:Request,body:ACLCreate,p=Depends(human)):
    return envelope(request,await runtime(request).admin.create_acl(p,body))

@router.post('/retention-policy')
async def retention(request:Request,body:Retention,p=Depends(human)):
    return envelope(request,await runtime(request).admin.approve_retention(p,body.model_dump()))

@router.post('/clients',status_code=201)
async def client(request:Request,body:ClientCreate,p=Depends(human)):
    return envelope(request,await runtime(request).admin.create_client(p,body))

@router.post('/clients/{client_id}/rotate-secret')
async def rotate(request:Request,client_id:str,body:Reason,p=Depends(human)):
    return envelope(request,await runtime(request).admin.rotate_client(p,client_id))

@router.post('/sync-jobs',status_code=202)
async def sync(request:Request,body:AdminSync,p=Depends(human)):
    return envelope(request,await runtime(request).sync.admin_request(p,body.service_client_id,body.request))

@router.get('/jobs')
async def jobs(request:Request,limit:int=Query(50,ge=1,le=100),p=Depends(human)):
    rt=runtime(request)
    async with rt.db.session() as s:
        await rt.admin.require(s,p,'meeting.sync.manage')
        rows=(await s.execute(select(SyncJob).where(SyncJob.org_id==p.org_id,SyncJob.deleted_at.is_(None))
            .order_by(SyncJob.created_at.desc()).limit(limit))).scalars()
        return envelope(request,{'items':[rt.jobs.info(r) for r in rows]})

@router.get('/jobs/{job_id}')
async def job(request:Request,job_id:str,p=Depends(human)):
    return envelope(request,await runtime(request).jobs.get(p,job_id))

@router.post('/jobs/{job_id}/retry')
async def retry(request:Request,job_id:str,body:Reason,p=Depends(human)):
    return envelope(request,await runtime(request).jobs.retry(p,job_id))

@router.post('/sync-policies',status_code=201)
async def sync_policy(request:Request,body:PolicyCreate,p=Depends(human)):
    return envelope(request,await runtime(request).sync.create_policy(p,body.model_dump()))

@router.post('/subscriptions',status_code=201)
async def subscription(request:Request,body:SubscriptionCreate,p=Depends(human)):
    return envelope(request,await runtime(request).events.create_subscription(p,body.model_dump()))

@router.get('/{kind}')
async def list_resources(request:Request,kind:str,limit:int=Query(50,ge=1,le=100),cursor:str|None=Query(None,max_length=4096),p=Depends(human)):
    return envelope(request,await runtime(request).admin.list_rows(p,kind,limit,cursor))

@router.post('/{kind}/{resource_id}/disable')
async def disable(request:Request,kind:str,resource_id:str,body:Reason,p=Depends(human)):
    return envelope(request,await runtime(request).admin.disable(p,kind,resource_id,body.reason))
