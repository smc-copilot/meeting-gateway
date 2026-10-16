"""Human-only control plane. Configuration authority is never content authority."""
from datetime import timedelta
from urllib.parse import urlsplit, parse_qs
import uuid
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from app.core.errors import MeetingError
from app.core.security import digest, random_token
from app.core.types import utcnow
from app.models import (Application, Connection, Credential, IdentityBinding, Client, AccessGrant,
    AgentGrant, ResourceACL, Meeting, Asset, OrganizationPolicy, PolicyVersion, AuditLog, AccessToken,
    Subscription, SyncPolicy)
from app.schemas.requests import ApplicationCreate, GrantCreate, ClientCreate, IdentityBind, AgentGrantCreate, ACLCreate
from app.services.permission_service import ALL_ACTIONS, BUSINESS_ACTIONS, MANAGEMENT_ACTIONS, live
from app.services.audit_service import record

FIELDS = {
 'applications': (Application, 'meeting.application.manage', ('name','application_type','environment','tencent_corp_id','sdk_id','data_scope','enabled','receiver_id','allowed_open_corp_ids','webhook_verified_at','last_callback_at')),
 'connections': (Connection, 'meeting.application.manage', ('application_id','kind','member_id','external_id','external_corp_id','corporate_verified','status','scopes','capabilities','last_verified_at','last_reason','last_synced_at','sync_coverage','consent_confirmed_at')),
 'identity-bindings': (IdentityBinding, 'meeting.application.manage', ('application_id','member_id','identity_type','external_id','external_corp_id','verification_source','verified_by','verified_at','enabled')),
 'clients': (Client, 'meeting.client.manage', ('name','client_type','allowed_scopes','redirect_uris','owner_member_id','agent_id','enabled','allow_service')),
 'grants': (AccessGrant, 'meeting.acl.manage', ('subject_type','subject_id','actions','scope_type','resource_ids','connection_ids','asset_types','target_member_ids','effect','purpose','enabled','expires_at','issued_by','reason')),
 'agent-grants': (AgentGrant, 'meeting.agent_grant.manage', ('member_id','client_id','agent_id','actions','scope_type','resource_ids','connection_ids','asset_types','target_member_ids','expires_at','enabled','confirmation_required','reason')),
 'resource-acl': (ResourceACL, 'meeting.acl.manage', ('resource_type','resource_id','subject_type','subject_id','effect','actions','asset_types','expires_at','issued_by','reason')),
 'audit': (AuditLog, 'meeting.audit.read', ('actor_type','subject_id','client_id','agent_id','action','resource_id','decision','reason','trace_id','details')),
 'subscriptions': (Subscription, 'meeting.client.manage', ('client_id','destination','event_types','member_id','agent_grant_id','enabled')),
 'sync-policies': (SyncPolicy, 'meeting.sync.manage', ('connection_id','client_id','ingestion_grant_id','interval_seconds','overlap_seconds','next_run_at','last_success_at','enabled')),
}


def safe_row(row, fields):
    return {name: getattr(row, name) for name in ('id','org_id','version','created_at') + tuple(fields)}


class AdminService:
    def __init__(self, runtime): self.rt=runtime

    async def human(self, principal):
        if not principal.portal or principal.actor_type!='MEMBER' or not principal.member_id:
            raise MeetingError('PERMISSION_DENIED',403)
        current=await self.rt.backend.resolve(principal.org_id,principal.member_id)
        if current.user_id!=principal.user_id or not current.is_active:
            raise MeetingError('MEMBER_INACTIVE',403)
        return current

    async def require(self, session, principal, action):
        await self.human(principal)
        await self.rt.policy.require(session,principal,action)
        grants = await self.rt.policy.grants(session, principal)
        if not any(live(g) and g.effect == 'ALLOW' and g.purpose == 'MANAGE' and action in g.actions
                   and g.scope_type == 'ORG_APPROVED' and not g.resource_ids and not g.connection_ids
                   and not g.asset_types and not g.target_member_ids for g in grants):
            raise MeetingError('PERMISSION_DENIED', 403)

    async def bootstrap(self, principal):
        member=await self.human(principal)
        if member.member_role!='admin': raise MeetingError('PERMISSION_DENIED',403)
        async with self.rt.db.lock('policy:'+principal.org_id), self.rt.db.transaction() as s:
            exists=await s.scalar(select(PolicyVersion).where(PolicyVersion.org_id==principal.org_id))
            if exists: raise MeetingError('CONFLICT',409)
            s.add(AccessGrant(org_id=principal.org_id,subject_type='MEMBER',subject_id=principal.member_id,
                actions=sorted(MANAGEMENT_ACTIONS),scope_type='ORG_APPROVED',purpose='MANAGE',issued_by=principal.member_id,
                reason='Initial organization administrator, no content rights'))
            s.add(Client(org_id=principal.org_id,name='Meeting Portal',client_type='PORTAL',owner_member_id=principal.member_id,
                allowed_scopes=sorted(BUSINESS_ACTIONS),enabled=True,allow_service=False,redirect_uris=[]))
            await self.rt.policy.bump(s,principal.org_id)
            record(s,principal,'organization.bootstrap',details={})
        return {'bootstrapped':True}

    async def list_rows(self, principal, kind, limit=50, cursor=None):
        if kind not in FIELDS or not 1<=limit<=100: raise MeetingError('INVALID_REQUEST',422)
        model,action,fields=FIELDS[kind]
        async with self.rt.db.session() as s:
            await self.require(s,principal,action)
            version=await self.rt.policy.policy_version(s,principal.org_id)
            binding=f'admin:{principal.binding}:{kind}:{version}'
            last=self.rt.cursors.decode(cursor,binding=binding).get('last') if cursor else None
            query=select(model).where(model.org_id==principal.org_id,model.deleted_at.is_(None))
            if last: query=query.where(model.id>last)
            rows=list((await s.execute(query.order_by(model.id).limit(limit+1))).scalars())
            return {'items':[safe_row(r,fields) for r in rows[:limit]],
                    'next_cursor':self.rt.cursors.encode({'last':rows[limit-1].id},binding=binding) if len(rows)>limit else None}

    async def _get(self, s, model, org, ident):
        row=await s.get(model,ident)
        if row is None or row.org_id!=org or row.deleted_at is not None:
            raise MeetingError('RESOURCE_NOT_ACCESSIBLE',404)
        return row

    async def save_secret(self,s,app,purpose,value,*,connection_id=None,expires_at=None,generation=None):
        old=list((await s.execute(select(Credential).where(Credential.application_id==app.id,
            Credential.connection_id==connection_id,Credential.purpose==purpose,Credential.active.is_(True)))).scalars())
        next_generation=generation or (max([r.generation for r in old],default=0)+1)
        for row in old: row.active=False
        row=Credential(org_id=app.org_id,application_id=app.id,connection_id=connection_id,purpose=purpose,
            key_id=self.rt.keys.active,expires_at=expires_at,generation=next_generation,ciphertext='')
        row.ciphertext=self.rt.keys.encrypt(value,f'credential:{app.org_id}:{app.id}:{connection_id or "-"}:{purpose}:{row.id}')
        s.add(row); await s.flush(); return row

    async def read_secret(self,s,app,purpose,*,connection_id=None):
        row=await s.scalar(select(Credential).where(Credential.application_id==app.id,
            Credential.connection_id==connection_id,Credential.purpose==purpose,Credential.active.is_(True),
            Credential.deleted_at.is_(None)).order_by(Credential.generation.desc()).limit(1))
        if row is None: raise MeetingError('STS_NOT_READY' if purpose=='STS' else 'UPSTREAM_REAUTH_REQUIRED',409)
        data=self.rt.keys.decrypt(row.ciphertext,f'credential:{app.org_id}:{app.id}:{connection_id or "-"}:{purpose}:{row.id}')
        return row,data

    async def create_application(self,principal,body:ApplicationCreate):
        async with self.rt.db.lock('policy:'+principal.org_id), self.rt.db.transaction() as s:
            await self.require(s,principal,'meeting.application.manage')
            duplicate=await s.scalar(select(Application).where(Application.org_id==principal.org_id,
                Application.environment==body.environment,Application.sdk_id==body.sdk_id,Application.deleted_at.is_(None)))
            if duplicate: raise MeetingError('CONFLICT',409)
            app=Application(org_id=principal.org_id,name=body.name,application_type=body.application_type,
                environment=body.environment,tencent_corp_id=body.tencent_corp_id,sdk_id=body.sdk_id,data_scope=body.data_scope,
                receiver_id=str(uuid.uuid4()),allowed_open_corp_ids=body.allowed_open_corp_ids,enabled=True)
            s.add(app);await s.flush()
            value={'secret_id':body.secret_id,'secret_key':body.secret_key} if body.application_type=='ENTERPRISE_AKSK' else {'secret':body.oauth_secret}
            await self.save_secret(s,app,'AKSK' if body.application_type=='ENTERPRISE_AKSK' else 'OAUTH_APP',value)
            await self.save_secret(s,app,'WEBHOOK',{'token':body.webhook_token,'encoding_key':body.webhook_encoding_key})
            await self.rt.policy.bump(s,principal.org_id)
            record(s,principal,'application.created',resource_id=app.id)
            return safe_row(app,FIELDS['applications'][2])

    async def rotate_application(self,principal,application_id,body:ApplicationCreate):
        async with self.rt.db.lock('policy:'+principal.org_id), self.rt.db.transaction() as s:
            await self.require(s,principal,'meeting.application.manage')
            app=await self._get(s,Application,principal.org_id,application_id)
            if (app.application_type,app.sdk_id,app.tencent_corp_id,app.environment)!=(body.application_type,body.sdk_id,body.tencent_corp_id,body.environment):
                raise MeetingError('CONFLICT',409)
            app.name=body.name;app.allowed_open_corp_ids=body.allowed_open_corp_ids;app.version+=1
            value={'secret_id':body.secret_id,'secret_key':body.secret_key} if app.application_type=='ENTERPRISE_AKSK' else {'secret':body.oauth_secret}
            await self.save_secret(s,app,'AKSK' if app.application_type=='ENTERPRISE_AKSK' else 'OAUTH_APP',value)
            await self.save_secret(s,app,'WEBHOOK',{'token':body.webhook_token,'encoding_key':body.webhook_encoding_key})
            app.webhook_verified_at=None
            connections=list((await s.execute(select(Connection).where(Connection.application_id==app.id))).scalars())
            for c in connections:
                c.last_verified_at=None;c.source_health_at=None;c.capabilities={}
                if c.kind=='THIRD_PARTY_OAUTH' and c.external_corp_id not in app.allowed_open_corp_ids:
                    c.status='CORP_MISMATCH';c.corporate_verified=False
            await self.rt.policy.bump(s,principal.org_id)
            record(s,principal,'application.rotated',resource_id=app.id)
            return safe_row(app,FIELDS['applications'][2])

    async def bind_identity(self,principal,body:IdentityBind):
        await self.rt.backend.resolve(principal.org_id,body.member_id)
        async with self.rt.db.lock('policy:'+principal.org_id), self.rt.db.transaction() as s:
            await self.require(s,principal,'meeting.application.manage')
            app=await self._get(s,Application,principal.org_id,body.application_id)
            if app.application_type!='ENTERPRISE_AKSK' or app.tencent_corp_id!=body.external_corp_id:
                raise MeetingError('IDENTITY_CONFLICT',409)
            existing=list((await s.execute(select(IdentityBinding).where(IdentityBinding.application_id==app.id,
                IdentityBinding.deleted_at.is_(None)))).scalars())
            for row in existing:
                if row.external_id==body.external_id or row.member_id==body.member_id:
                    if row.external_id!=body.external_id or row.member_id!=body.member_id:
                        raise MeetingError('IDENTITY_CONFLICT',409)
                    row.enabled=True;row.verified_at=utcnow();row.verification_source=body.verification_source;row.version+=1
                    await self.rt.policy.bump(s,principal.org_id)
                    record(s,principal,'identity.reverified',resource_id=row.id)
                    return safe_row(row,FIELDS['identity-bindings'][2])
            row=IdentityBinding(org_id=principal.org_id,application_id=app.id,member_id=body.member_id,identity_type='userid',
                external_id=body.external_id,external_corp_id=body.external_corp_id,verification_source=body.verification_source,
                verified_by=principal.member_id,verified_at=utcnow(),enabled=True)
            s.add(row);await s.flush();await self.rt.policy.bump(s,principal.org_id)
            record(s,principal,'identity.bound',resource_id=row.id)
            return safe_row(row,FIELDS['identity-bindings'][2])

    async def _check_references(self,s,org,connections=(),resources=(),members=()):
        for ident in connections: await self._get(s,Connection,org,ident)
        for ident in resources:
            row=await s.get(Meeting,ident) or await s.get(Asset,ident)
            if not row or row.org_id!=org or row.deleted_at is not None: raise MeetingError('RESOURCE_NOT_ACCESSIBLE',404)
        for ident in members: await self.rt.backend.resolve(org,ident)

    async def create_grant(self,principal,body:GrantCreate):
        if not set(body.actions)<=ALL_ACTIONS or (body.expires_at and body.expires_at<=utcnow()):
            raise MeetingError('INVALID_REQUEST',422)
        async with self.rt.db.lock('policy:'+principal.org_id),self.rt.db.transaction() as s:
            await self.require(s,principal,'meeting.acl.manage')
            await self._check_references(s,principal.org_id,body.connection_ids,body.resource_ids,body.target_member_ids)
            if body.subject_type=='MEMBER': await self.rt.backend.resolve(principal.org_id,body.subject_id)
            else:
                client=await self._get(s,Client,principal.org_id,body.subject_id)
                if not client.allow_service: raise MeetingError('PERMISSION_DENIED',403)
            if body.purpose=='INGESTION':
                policy=await s.scalar(select(OrganizationPolicy).where(OrganizationPolicy.org_id==principal.org_id,
                    OrganizationPolicy.deleted_at.is_(None)))
                if not policy or not policy.retention_confirmed: raise MeetingError('RETENTION_UNCONFIRMED',409)
                if body.subject_type!='SERVICE' or not body.connection_ids or body.scope_type!='ORG_APPROVED' or set(body.actions)!={'meeting.sync.manage'}:
                    raise MeetingError('INVALID_REQUEST',422)
                for cid in body.connection_ids:
                    c=await self._get(s,Connection,principal.org_id,cid)
                    if c.kind!='ENTERPRISE_AKSK': raise MeetingError('PERMISSION_DENIED',403)
            if body.purpose=='MANAGE' and not set(body.actions)<=MANAGEMENT_ACTIONS:
                raise MeetingError('INVALID_REQUEST',422)
            if body.purpose=='ACCESS' and not set(body.actions)<=BUSINESS_ACTIONS:
                raise MeetingError('INVALID_REQUEST',422)
            row=AccessGrant(org_id=principal.org_id,issued_by=principal.member_id,**body.model_dump())
            s.add(row);await s.flush();await self.rt.policy.bump(s,principal.org_id)
            record(s,principal,'permission.created',resource_id=row.id)
            return safe_row(row,FIELDS['grants'][2])

    async def approve_retention(self,principal,data):
        days={k:int(data[k]) for k in ('metadata_days','content_days','audit_days')}
        if any(v<1 or v>3650 for v in days.values()) or not 3<=len(data.get('reason',''))<=500:
            raise MeetingError('INVALID_REQUEST',422)
        async with self.rt.db.lock('policy:'+principal.org_id),self.rt.db.transaction() as s:
            await self.require(s,principal,'meeting.acl.manage')
            row=await s.scalar(select(OrganizationPolicy).where(OrganizationPolicy.org_id==principal.org_id))
            if row is None:
                row=OrganizationPolicy(org_id=principal.org_id,approved_by=principal.member_id,reason=data['reason'],**days);s.add(row)
            else:
                for k,v in days.items():setattr(row,k,v)
                row.approved_by=principal.member_id;row.reason=data['reason'];row.version+=1
            row.retention_confirmed=True
            await self.rt.policy.bump(s,principal.org_id);record(s,principal,'retention.approved',resource_id=row.id)
            return {'id':row.id,**days,'retention_confirmed':True}

    async def create_client(self,principal,body:ClientCreate):
        if not set(body.allowed_scopes)<=BUSINESS_ACTIONS: raise MeetingError('INVALID_REQUEST',422)
        if body.client_type=='PUBLIC_MCP' and (not body.redirect_uris or body.allow_service):
            raise MeetingError('INVALID_REQUEST',422)
        for uri in body.redirect_uris:
            p=urlsplit(uri)
            if p.scheme!='https' or not p.hostname or p.username or p.password or p.fragment or '*' in uri or {'code','state'} & set(parse_qs(p.query)):
                raise MeetingError('INVALID_REQUEST',422)
        await self.rt.backend.resolve(principal.org_id,body.owner_member_id)
        secret=random_token('mc') if body.client_type=='CONFIDENTIAL' else None
        async with self.rt.db.lock('policy:'+principal.org_id),self.rt.db.transaction() as s:
            await self.require(s,principal,'meeting.client.manage')
            data=body.model_dump(exclude={'reason'})
            row=Client(org_id=principal.org_id,secret_hash=digest(secret) if secret else None,**data)
            s.add(row);await s.flush();await self.rt.policy.bump(s,principal.org_id)
            record(s,principal,'client.created',resource_id=row.id)
            result=safe_row(row,FIELDS['clients'][2])
            if secret:result['client_secret']=secret
            return result

    async def rotate_client(self,principal,client_id):
        secret=random_token('mc')
        async with self.rt.db.lock('policy:'+principal.org_id),self.rt.db.transaction() as s:
            await self.require(s,principal,'meeting.client.manage')
            row=await self._get(s,Client,principal.org_id,client_id)
            if row.client_type!='CONFIDENTIAL':raise MeetingError('INVALID_REQUEST',422)
            row.secret_hash=digest(secret);row.version+=1
            tokens=(await s.execute(select(AccessToken).where(AccessToken.client_id==row.id,AccessToken.revoked_at.is_(None)))).scalars()
            for token in tokens:token.revoked_at=utcnow()
            record(s,principal,'client.rotated',resource_id=row.id);await self.rt.policy.bump(s,principal.org_id)
            return {'id':row.id,'client_secret':secret}

    async def create_agent_grant(self,principal,body:AgentGrantCreate):
        await self.human(principal)
        if not body.expires_at or body.expires_at<=utcnow() or body.expires_at>utcnow()+timedelta(days=30):
            raise MeetingError('INVALID_REQUEST',422)
        async with self.rt.db.lock('policy:'+principal.org_id),self.rt.db.transaction() as s:
            client=await self._get(s,Client,principal.org_id,body.client_id)
            if not client.enabled or client.agent_id!=body.agent_id: raise MeetingError('PERMISSION_DENIED',403)
            ceiling=await self.rt.policy.action_ceiling(s,principal)
            if not set(body.actions)<=ceiling or not set(body.actions)<=BUSINESS_ACTIONS:
                raise MeetingError('PERMISSION_DENIED',403)
            await self._check_references(s,principal.org_id,body.connection_ids,body.resource_ids,body.target_member_ids)
            row=AgentGrant(org_id=principal.org_id,member_id=principal.member_id,issued_by=principal.member_id,
                confirmation_required=True,**body.model_dump())
            s.add(row);await s.flush();await self.rt.policy.bump(s,principal.org_id)
            record(s,principal,'agent_grant.created',resource_id=row.id)
            return safe_row(row,FIELDS['agent-grants'][2])

    async def create_acl(self,principal,body:ACLCreate):
        if not set(body.actions)<=BUSINESS_ACTIONS:raise MeetingError('INVALID_REQUEST',422)
        async with self.rt.db.lock('policy:'+principal.org_id),self.rt.db.transaction() as s:
            await self.require(s,principal,'meeting.acl.manage')
            model=Meeting if body.resource_type=='meeting' else Asset
            resource=await self._get(s,model,principal.org_id,body.resource_id)
            connection=await self._get(s,Connection,principal.org_id,resource.connection_id)
            if connection.kind=='THIRD_PARTY_OAUTH' and (body.subject_type!='MEMBER' or body.subject_id!=connection.member_id):
                raise MeetingError('PERMISSION_DENIED',403)
            if body.subject_type=='MEMBER':await self.rt.backend.resolve(principal.org_id,body.subject_id)
            else:await self._get(s,Client,principal.org_id,body.subject_id)
            row=ResourceACL(org_id=principal.org_id,issued_by=principal.member_id,**body.model_dump());s.add(row)
            await s.flush();await self.rt.policy.bump(s,principal.org_id);record(s,principal,'resource_acl.created',resource_id=row.id)
            return safe_row(row,FIELDS['resource-acl'][2])

    async def disable(self,principal,kind,ident,reason):
        if kind not in FIELDS or kind=='audit' or not 3<=len(reason)<=500:raise MeetingError('INVALID_REQUEST',422)
        model,action,fields=FIELDS[kind]
        async with self.rt.db.lock('policy:'+principal.org_id),self.rt.db.transaction() as s:
            await self.require(s,principal,action)
            row=await self._get(s,model,principal.org_id,ident)
            if isinstance(row,Connection):row.status='DISABLED'
            elif hasattr(row,'enabled'):row.enabled=False
            else:row.soft_delete()
            row.version+=1
            await self.rt.policy.bump(s,principal.org_id);record(s,principal,kind.replace('-','_')+'.disabled',resource_id=ident)
            return {'id':ident,'disabled':True}
