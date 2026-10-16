from fastapi import APIRouter,Request,Depends,Query
from sqlalchemy import select
from app.api.deps import runtime,envelope,human
from app.schemas.requests import Reason,AgentGrantCreate
from app.schemas.control import Approval,Consent,Reconciliation
from app.services.portal_service import PortalService
from app.models import AuthTransaction
from app.core.errors import MeetingError
from app.services.audit_service import record

router=APIRouter(prefix='/portal',tags=['meeting-portal'])

@router.get('/context')
async def context(request:Request,p=Depends(human)):
    return envelope(request,await PortalService(runtime(request)).context(p))

@router.post('/session')
async def session(request:Request,p=Depends(human)):
    return envelope(request,await runtime(request).auth.portal_exchange(p))

@router.get('/applications')
async def applications(request:Request,p=Depends(human)):
    return envelope(request,await PortalService(runtime(request)).applications(p))

@router.get('/connections')
async def connections(request:Request,p=Depends(human)):
    return envelope(request,await PortalService(runtime(request)).connections(p))

@router.post('/applications/{application_id}/authorize')
async def authorize(request:Request,application_id:str,p=Depends(human)):
    return envelope(request,await runtime(request).connections.oauth_start(p,application_id))

@router.post('/connections/{connection_id}/confirm')
async def confirm_connection(request:Request,connection_id:str,p=Depends(human)):
    return envelope(request,await runtime(request).connections.confirm_oauth(p,connection_id))

@router.post('/connections/{connection_id}/revoke')
async def revoke_connection(request:Request,connection_id:str,body:Reason,p=Depends(human)):
    return envelope(request,await runtime(request).connections.revoke_own(p,connection_id))

@router.get('/agent-clients')
async def agent_clients(request:Request,p=Depends(human)):
    return envelope(request,await PortalService(runtime(request)).agent_clients(p))

@router.get('/agent-grants')
async def agents(request:Request,p=Depends(human)):
    return envelope(request,await PortalService(runtime(request)).agents(p))

@router.post('/agent-grants',status_code=201)
async def agent_grant(request:Request,body:AgentGrantCreate,p=Depends(human)):
    return envelope(request,await runtime(request).admin.create_agent_grant(p,body))

@router.post('/agent-grants/{grant_id}/revoke')
async def revoke_agent(request:Request,grant_id:str,body:Reason,p=Depends(human)):
    return envelope(request,await PortalService(runtime(request)).revoke_agent(p,grant_id,body.reason))

@router.get('/operations')
async def operations(request:Request,limit:int=Query(50,ge=1,le=100),p=Depends(human)):
    return envelope(request,await runtime(request).operations.list(p,limit))

@router.get('/operations/{operation_id}')
async def operation(request:Request,operation_id:str,p=Depends(human)):
    return envelope(request,await runtime(request).operations.get(p,operation_id))

@router.post('/operations/{operation_id}/confirm')
async def confirm(request:Request,operation_id:str,body:Approval,p=Depends(human)):
    return envelope(request,await runtime(request).operations.confirm(p,operation_id,body.request_hash))

@router.post('/operations/{operation_id}/reject')
async def reject(request:Request,operation_id:str,body:Reason,p=Depends(human)):
    return envelope(request,await runtime(request).operations.reject(p,operation_id,body.reason))

@router.post('/operations/{operation_id}/reconcile')
async def reconcile(request:Request,operation_id:str,body:Reconciliation,p=Depends(human)):
    return envelope(request,await runtime(request).operations.reconcile(p,operation_id,**body.model_dump()))

@router.get('/authorization/{transaction_id}')
async def details(request:Request,transaction_id:str,p=Depends(human)):
    return envelope(request,await runtime(request).auth.authorization_details(transaction_id,p))

@router.post('/authorization/{transaction_id}/approve')
async def consent(request:Request,transaction_id:str,body:Consent,p=Depends(human)):
    return envelope(request,await runtime(request).auth.approve_authorization(transaction_id,p,body.agent_grant_id))

@router.post('/authorization/{transaction_id}/deny')
async def deny(request:Request,transaction_id:str,p=Depends(human)):
    rt=runtime(request)
    async with rt.db.lock('consent:'+transaction_id),rt.db.transaction() as s:
        row=await rt.admin._get(s,AuthTransaction,p.org_id,transaction_id)
        if row.purpose!='DOWNSTREAM_REQUEST' or row.status!='PENDING':raise MeetingError('STATE_INVALID',400)
        row.status='DENIED';row.member_id=p.member_id
        record(s,p,'auth.consent.denied',resource_id=row.id)
    return envelope(request,{'status':'DENIED'})

@router.get('/members')
async def members(request:Request,q:str=Query('',max_length=100),p=Depends(human)):
    return envelope(request,{'items':await runtime(request).backend.search(p.org_id,q)})
