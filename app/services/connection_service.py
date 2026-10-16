"""Tencent app and employee connections. No fallback to another app, operator or credential."""
from datetime import UTC, datetime, timedelta
import secrets
import uuid
from urllib.parse import urlencode
from sqlalchemy import select
from app.core.errors import MeetingError, UpstreamError
from app.core.security import digest
from app.core.types import Operator, Principal, utcnow
from app.models import (Application, Connection, Credential, IdentityBinding, AuthTransaction, STSRequest, STSCallback)
from app.services.admin_service import safe_row, FIELDS
from app.services.audit_service import record
from app.services.permission_service import live


class ConnectionService:
    def __init__(self,runtime):self.rt=runtime

    async def get(self,org_id,connection_id,*,allow_inactive=False):
        async with self.rt.db.session() as s:
            connection=await self.rt.admin._get(s,Connection,org_id,connection_id)
            app=await self.rt.admin._get(s,Application,org_id,connection.application_id)
            if connection.status=='BLOCKED':
                raise MeetingError(connection.last_reason or 'UPSTREAM_CONTRACT_ERROR',409)
            if not app.enabled or (not allow_inactive and (connection.status not in {'ACTIVE','DEGRADED'} or not connection.corporate_verified)):
                raise MeetingError('UPSTREAM_REAUTH_REQUIRED',409)
            return connection,app

    async def owned(self,principal,connection_id):
        c,a=await self.get(principal.org_id,connection_id)
        if c.kind=='THIRD_PARTY_OAUTH' and (principal.actor_type=='SERVICE' or c.member_id!=principal.member_id):
            raise MeetingError('RESOURCE_NOT_ACCESSIBLE',404)
        return c,a

    async def create_enterprise(self,principal,body):
        await self.rt.backend.resolve(principal.org_id,body.admin_member_id)
        async with self.rt.db.lock('policy:'+principal.org_id),self.rt.db.transaction() as s:
            await self.rt.admin.require(s,principal,'meeting.application.manage')
            app=await self.rt.admin._get(s,Application,principal.org_id,body.application_id)
            if not app.enabled or app.application_type!='ENTERPRISE_AKSK' or app.data_scope!='enterprise':
                raise MeetingError('UPSTREAM_CAPABILITY_UNAVAILABLE',409)
            binding=await s.scalar(select(IdentityBinding).where(IdentityBinding.application_id==app.id,
                IdentityBinding.member_id==body.admin_member_id,IdentityBinding.external_id==body.admin_userid,
                IdentityBinding.identity_type=='userid',IdentityBinding.enabled.is_(True),IdentityBinding.deleted_at.is_(None)))
            if not binding:raise MeetingError('IDENTITY_UNBOUND',409)
            duplicate=await s.scalar(select(Connection).where(Connection.application_id==app.id,
                Connection.external_id==body.admin_userid,Connection.deleted_at.is_(None)))
            if duplicate:raise MeetingError('CONFLICT',409)
            row=Connection(org_id=principal.org_id,application_id=app.id,kind='ENTERPRISE_AKSK',
                member_id=body.admin_member_id,external_id=body.admin_userid,external_corp_id=app.tencent_corp_id,
                corporate_verified=True,status='ACTIVE',capabilities={},consent_confirmed_at=utcnow(),
                settings_data={'configuration_only':True})
            s.add(row);await s.flush();await self.rt.policy.bump(s,principal.org_id)
            record(s,principal,'connection.created',resource_id=row.id)
            return safe_row(row,FIELDS['connections'][2])

    async def invitee(self, connection, member_id):
        """Resolve an invitee, not an operator. An OAuth open_id is scoped to this same app and corporation."""
        if connection.kind == 'ENTERPRISE_AKSK':
            return await self.operator(connection, member_id=member_id)
        await self.rt.backend.resolve(connection.org_id, member_id)
        async with self.rt.db.session() as session:
            binding = await session.scalar(select(IdentityBinding).where(
                IdentityBinding.org_id == connection.org_id,
                IdentityBinding.application_id == connection.application_id,
                IdentityBinding.member_id == member_id, IdentityBinding.identity_type == 'openid',
                IdentityBinding.external_corp_id == connection.external_corp_id,
                IdentityBinding.enabled.is_(True), IdentityBinding.deleted_at.is_(None)))
            if binding is None or not binding.verified_at:
                raise MeetingError('IDENTITY_UNBOUND', 409)
            return Operator(id=binding.external_id, type=2)

    async def operator(self,connection,*,member_id=None,for_ingestion=False):
        if connection.kind=='THIRD_PARTY_OAUTH':
            if for_ingestion or (member_id is not None and member_id!=connection.member_id):
                raise MeetingError('PERMISSION_DENIED',403)
            return Operator(id=connection.external_id,type=2)
        target=connection.member_id if for_ingestion else member_id
        if target is None:raise MeetingError('IDENTITY_UNBOUND',409)
        await self.rt.backend.resolve(connection.org_id,target)
        async with self.rt.db.session() as s:
            binding=await s.scalar(select(IdentityBinding).where(IdentityBinding.application_id==connection.application_id,
                IdentityBinding.org_id==connection.org_id,IdentityBinding.member_id==target,IdentityBinding.identity_type=='userid',
                IdentityBinding.enabled.is_(True),IdentityBinding.deleted_at.is_(None)))
            if not binding or (for_ingestion and binding.external_id!=connection.external_id):
                raise MeetingError('IDENTITY_UNBOUND',409)
            return Operator(id=binding.external_id,type=1)

    async def member_from_external(self,s,connection,external_id):
        if external_id is None:return None
        if connection.kind=='THIRD_PARTY_OAUTH' and str(external_id)==connection.external_id:
            return connection.member_id
        row=await s.scalar(select(IdentityBinding).where(IdentityBinding.org_id==connection.org_id,
            IdentityBinding.application_id==connection.application_id,IdentityBinding.external_id==str(external_id),
            IdentityBinding.enabled.is_(True),IdentityBinding.deleted_at.is_(None)))
        return row.member_id if row else None

    async def oauth_start(self,principal,application_id,return_to=None):
        if getattr(principal,'portal',False):
            await self.rt.admin.human(principal)
        else:
            principal=await self.rt.auth.revalidate(principal)
            if principal.actor_type!='MEMBER' or not principal.member_id:
                raise MeetingError('PERMISSION_DENIED',403)
        async with self.rt.db.transaction() as s:
            app=await self.rt.admin._get(s,Application,principal.org_id,application_id)
            if not app.enabled or app.application_type!='THIRD_PARTY_OAUTH':raise MeetingError('INVALID_REQUEST',422)
            allowed=list((app.settings_data or {}).get('oauth_return_uris') or [])
            if return_to is not None and return_to not in allowed:
                raise MeetingError('INVALID_REQUEST',422)
            state=secrets.token_hex(24)
            tx=AuthTransaction(org_id=principal.org_id,purpose='TENCENT_OAUTH',secret_hash=digest(state),
                application_id=app.id,member_id=principal.member_id,status='PENDING',
                expires_at=utcnow()+timedelta(seconds=self.rt.settings.upstream_state_seconds),
                payload={'user_id':principal.user_id,'return_to':return_to})
            s.add(tx);record(s,principal,'oauth.started',resource_id=app.id)
            redirect=self.rt.settings.public_base_url+'/callbacks/tencent/oauth/'+app.id
            query=urlencode({'corp_id':app.tencent_corp_id,'sdk_id':app.sdk_id,'redirect_uri':redirect,'state':state})
            return {'authorization_url':'https://meeting.tencent.com/marketplace/authorize.html?'+query,
                    'transaction_id':tx.id,'expires_at':tx.expires_at}

    async def oauth_callback(self,application_id,state,code):
        if not state or not state.isalnum() or len(state)>64 or not code or len(code)>2048:
            raise MeetingError('STATE_INVALID',400)
        async with self.rt.db.lock('oauth-state:'+digest(state)):
            async with self.rt.db.transaction() as s:
                tx=await s.scalar(select(AuthTransaction).where(AuthTransaction.application_id==application_id,
                    AuthTransaction.secret_hash==digest(state),AuthTransaction.purpose=='TENCENT_OAUTH'))
                if not tx or tx.status!='PENDING' or tx.expires_at<=utcnow():raise MeetingError('STATE_INVALID',400)
                app=await self.rt.admin._get(s,Application,tx.org_id,application_id)
                if not app.enabled:raise MeetingError('UPSTREAM_REAUTH_REQUIRED',409)
                await self.rt.backend.resolve(tx.org_id,tx.member_id)
                _,secret=await self.rt.admin.read_secret(s,app,'OAUTH_APP')
                # Mark consumed before network. A timeout requires starting a new authorization, not replaying a code.
                tx.status='EXCHANGING';tx.used_at=utcnow()
                txid,org,member=tx.id,tx.org_id,tx.member_id
            try:
                token=await self.rt.tencent.oauth('access_token',{'sdk_id':app.sdk_id,'secret':secret['secret'],'auth_code':code})
                self._validate_oauth(token)
            except Exception:
                async with self.rt.db.transaction() as s:
                    tx=await s.get(AuthTransaction,txid);tx.status='FAILED'
                raise
            async with self.rt.db.lock('policy:'+org),self.rt.db.transaction() as s:
                tx=await s.get(AuthTransaction,txid);app=await self.rt.admin._get(s,Application,org,application_id)
                if not app.enabled:raise MeetingError('UPSTREAM_REAUTH_REQUIRED',409)
                external=str(token['open_id']);corp=str(token.get('open_corp_id') or '')
                existing=await s.scalar(select(Connection).where(Connection.application_id==app.id,
                    Connection.external_id==external,Connection.deleted_at.is_(None)))
                if existing and existing.member_id!=member:
                    tx.status='IDENTITY_CONFLICT';await s.commit();raise MeetingError('IDENTITY_CONFLICT',409)
                c=existing or Connection(org_id=org,application_id=app.id,kind='THIRD_PARTY_OAUTH',member_id=member,
                    external_id=external,external_corp_id=corp,scopes=token['scopes'])
                if not existing:s.add(c);await s.flush()
                c.external_corp_id=corp;c.scopes=token['scopes'];c.corporate_verified=bool(corp and corp in app.allowed_open_corp_ids)
                c.status='PENDING_CONFIRMATION' if c.corporate_verified else 'CORP_MISMATCH'
                c.consent_confirmed_at=None;c.capabilities={};c.source_health_at=None
                await self.rt.admin.save_secret(s,app,'OAUTH_TOKEN',token,connection_id=c.id,
                    expires_at=datetime.fromtimestamp(int(token['expires']),UTC))
                tx.status='RECEIVED';tx.payload={**(tx.payload or {}),'connection_id':c.id}
                await self.rt.policy.bump(s,org)
                stored=dict(tx.payload or {})
                return {'connection_id':c.id,'status':c.status,'return_to':stored.get('return_to'),
                    'confirmation_url':self.rt.settings.portal_base_url+'/meeting/connections?connection_id='+c.id}

    def _validate_oauth(self,token):
        try:
            if not isinstance(token,dict) or not all(isinstance(token[k],str) and token[k] for k in ('access_token','refresh_token','open_id')):
                raise ValueError('fields')
            if not isinstance(token.get('scopes'),list) or not all(isinstance(x,str) for x in token['scopes']):raise ValueError('scope')
            expires=int(token['expires'])
            if not int(utcnow().timestamp())<expires<int((utcnow()+timedelta(days=2)).timestamp()):raise ValueError('expiry')
        except (ValueError,KeyError,TypeError,OverflowError) as exc:
            raise UpstreamError('UPSTREAM_CONTRACT_ERROR') from exc

    async def confirm_oauth(self,principal,connection_id):
        await self.rt.admin.human(principal)
        async with self.rt.db.lock('policy:'+principal.org_id),self.rt.db.transaction() as s:
            c=await self.rt.admin._get(s,Connection,principal.org_id,connection_id)
            app=await self.rt.admin._get(s,Application,principal.org_id,c.application_id)
            if c.member_id!=principal.member_id or c.kind!='THIRD_PARTY_OAUTH' or c.status!='PENDING_CONFIRMATION':
                raise MeetingError('PERMISSION_DENIED',403)
            if not app.enabled or not c.corporate_verified or c.external_corp_id not in app.allowed_open_corp_ids:
                raise MeetingError('PERMISSION_DENIED',403)
            credential,_=await self.rt.admin.read_secret(s,app,'OAUTH_TOKEN',connection_id=c.id)
            if credential.expires_at<=utcnow():raise MeetingError('UPSTREAM_REAUTH_REQUIRED',409)
            binding=await s.scalar(select(IdentityBinding).where(IdentityBinding.application_id==app.id,
                IdentityBinding.identity_type=='openid',IdentityBinding.member_id==principal.member_id,
                IdentityBinding.deleted_at.is_(None)))
            if binding and binding.external_id!=c.external_id:raise MeetingError('IDENTITY_CONFLICT',409)
            if binding is None:
                binding=IdentityBinding(org_id=c.org_id,application_id=app.id,member_id=c.member_id,identity_type='openid',
                    external_id=c.external_id,external_corp_id=c.external_corp_id,verification_source='Tencent OAuth + employee confirmation',
                    verified_by=principal.member_id,verified_at=utcnow(),enabled=True);s.add(binding)
            else:binding.enabled=True;binding.verified_at=utcnow()
            c.status='ACTIVE';c.consent_confirmed_at=utcnow();c.version+=1
            await self.rt.policy.bump(s,c.org_id);record(s,principal,'oauth.confirmed',resource_id=c.id)
            return safe_row(c,FIELDS['connections'][2])

    async def oauth_credentials(self,connection_id):
        async with self.rt.db.lock('oauth-refresh:'+connection_id):
            async with self.rt.db.session() as s:
                c=await s.get(Connection,connection_id)
                if not c or c.kind!='THIRD_PARTY_OAUTH':raise MeetingError('UPSTREAM_REAUTH_REQUIRED',409)
                app=await self.rt.admin._get(s,Application,c.org_id,c.application_id)
                if not app.enabled or c.status not in {'ACTIVE','DEGRADED'} or not c.corporate_verified or c.external_corp_id not in app.allowed_open_corp_ids:
                    raise MeetingError('UPSTREAM_REAUTH_REQUIRED',409)
                await self.rt.backend.resolve(c.org_id,c.member_id)
                cred,token=await self.rt.admin.read_secret(s,app,'OAUTH_TOKEN',connection_id=c.id)
                if cred.expires_at>utcnow()+timedelta(seconds=120):return token
            try:
                fresh=await self.rt.tencent.oauth('refresh_token',{'sdk_id':app.sdk_id,'open_id':c.external_id,'refresh_token':token['refresh_token']})
                self._validate_oauth(fresh)
                if fresh['open_id']!=c.external_id:raise UpstreamError('UPSTREAM_CONTRACT_ERROR')
                fresh['open_corp_id']=c.external_corp_id
            except MeetingError as exc:
                await self._refresh_fault(c.id,exc)
                raise
            except Exception as exc:
                fault=UpstreamError('UPSTREAM_CONTRACT_ERROR')
                await self._refresh_fault(c.id,fault)
                raise fault from exc
            async with self.rt.db.transaction() as s:
                current=await s.get(Connection,c.id)
                if current.status not in {'ACTIVE','DEGRADED'}:raise MeetingError('UPSTREAM_REAUTH_REQUIRED',409)
                await self.rt.admin.save_secret(s,app,'OAUTH_TOKEN',fresh,connection_id=c.id,
                    expires_at=datetime.fromtimestamp(int(fresh['expires']),UTC))
                current.scopes=fresh['scopes'];current.last_verified_at=utcnow()
                if current.status=='DEGRADED':current.status='ACTIVE'
            return fresh

    async def _refresh_fault(self,connection_id,exc:MeetingError):
        reason=exc.reason
        async with self.rt.db.transaction() as s:
            row=await s.get(Connection,connection_id)
            if row is None:return
            if reason in {'UPSTREAM_UNAVAILABLE','RATE_LIMITED','UPSTREAM_DAILY_QUOTA','UPSTREAM_CLOCK_SKEW','IDENTITY_SERVICE_UNAVAILABLE'}:
                if row.status=='ACTIVE':row.status='DEGRADED'
                row.last_reason=reason
                return
            if reason in {'UPSTREAM_REAUTH_REQUIRED','UPSTREAM_CREDENTIAL_INVALID'}:
                row.status='REAUTH_REQUIRED';row.last_reason='UPSTREAM_REAUTH_REQUIRED'
                return
            row.status='BLOCKED';row.last_reason=reason

    async def request_sts(self,principal,connection_id,valid_hours=6):
        if valid_hours not in {6,12,24}:raise MeetingError('INVALID_REQUEST',422)
        c,app=await self.get(principal.org_id,connection_id)
        if c.kind!='ENTERPRISE_AKSK':raise MeetingError('UPSTREAM_CAPABILITY_UNAVAILABLE',409)
        async with self.rt.db.session() as s:await self.rt.admin.require(s,principal,'meeting.application.manage')
        return await self._generate_sts(principal, c, app, valid_hours)

    async def maintain_sts(self, connection_id):
        # Only a pre-approved enterprise connection is eligible; this cannot retrieve meeting content.
        async with self.rt.db.lock('sts-maintenance:' + connection_id):
            async with self.rt.db.session() as s:
                c=await s.get(Connection,connection_id)
                if not c or c.deleted_at or c.status not in {'ACTIVE','DEGRADED'} or not c.consent_confirmed_at:
                    return
                c,app=await self.get(c.org_id,c.id)
                if c.kind!='ENTERPRISE_AKSK':return
                current=await s.scalar(select(Credential).where(Credential.connection_id==c.id,
                    Credential.purpose=='STS',Credential.active.is_(True),Credential.deleted_at.is_(None))
                    .order_by(Credential.generation.desc()).limit(1))
                if current and current.expires_at and current.expires_at>utcnow()+timedelta(minutes=10):return
                pending=await s.scalar(select(STSRequest).where(STSRequest.connection_id==c.id,
                    STSRequest.status.in_(['REQUESTED','WAITING_CALLBACK']),STSRequest.requested_at>utcnow()-timedelta(minutes=5)))
                if pending:return
            p=Principal(org_id=c.org_id,actor_type='SERVICE',client_id='sts-internal')
            return await self._generate_sts(p,c,app,6)

    async def _generate_sts(self,principal,c,app,valid_hours):
        operator=await self.operator(c,for_ingestion=True)
        async with self.rt.db.lock('sts-generate:'+app.id):
            async with self.rt.db.transaction() as s:
                generation=int(utcnow().timestamp()*1_000_000)
                req=STSRequest(org_id=c.org_id,application_id=app.id,connection_id=c.id,requested_at=utcnow(),
                    valid_hours=valid_hours,generation=generation,status='REQUESTED');s.add(req);await s.flush();request_id=req.id
                record(s,principal,'sts.requested',resource_id=c.id)
            try:
                result=await self.rt.tencent.call(c.id,'sts',operator,body={'operator_id':operator.id,'operator_id_type':operator.type,'valid_time':valid_hours})
                if not isinstance(result.get('req_id'),str) or not result['req_id']:raise UpstreamError('UPSTREAM_CONTRACT_ERROR')
            except Exception:
                async with self.rt.db.transaction() as s:
                    row=await s.get(STSRequest,request_id);row.status='FAILED'
                raise
            async with self.rt.db.lock('sts-associate:'+app.id),self.rt.db.transaction() as s:
                req=await s.get(STSRequest,request_id);req.req_id=result['req_id'];req.status='WAITING_CALLBACK'
                await self._associate(s,app,req)
                return {'request_id':req.id,'status':req.status}

    async def _associate(self,s,app,req):
        callback=await s.scalar(select(STSCallback).where(STSCallback.application_id==app.id,STSCallback.req_id==req.req_id))
        if callback is None:return
        c=await s.get(Connection,req.connection_id)
        if callback.expires_at<=utcnow() or callback.operator_id!=c.external_id:
            req.status='REJECTED';return
        # A request's monotonic generation determines precedence, never callback arrival order.
        current=await s.scalar(select(Credential).where(Credential.application_id==app.id,Credential.purpose=='STS',
            Credential.connection_id==c.id,Credential.active.is_(True)).order_by(Credential.generation.desc()).limit(1))
        if current and current.generation>req.generation:
            req.status='SUPERSEDED';return
        token=self.rt.keys.decrypt(callback.token_ciphertext,f'sts:{app.id}:{callback.req_id}')
        await self.rt.admin.save_secret(s,app,'STS',{'sts_token':token},connection_id=c.id,
                                       expires_at=callback.expires_at,generation=req.generation)
        callback.associated_request_id=req.id;req.status='ACTIVE'

    async def receive_sts(self,application_id,token_info,*,operator_id,operate_time_ms):
        try:
            req_id=token_info['req_id'];token=token_info['sts_token'];expires=datetime.fromtimestamp(int(token_info['expire_ts']),UTC)
            if not isinstance(req_id,str) or not isinstance(token,str) or not token or len(token)>16384:raise ValueError('fields')
        except (KeyError,ValueError,TypeError,OverflowError) as exc:raise MeetingError('INVALID_REQUEST',422) from exc
        async with self.rt.db.lock('sts-associate:'+application_id),self.rt.db.transaction() as s:
            app=await s.get(Application,application_id)
            if not app or app.application_type!='ENTERPRISE_AKSK' or not app.enabled:raise MeetingError('INVALID_REQUEST',422)
            row=await s.scalar(select(STSCallback).where(STSCallback.application_id==app.id,STSCallback.req_id==req_id))
            if row is None:
                row=STSCallback(org_id=app.org_id,application_id=app.id,req_id=req_id,expires_at=expires,operator_id=operator_id,
                    operate_time_ms=operate_time_ms,token_ciphertext=self.rt.keys.encrypt(token,f'sts:{app.id}:{req_id}'))
                s.add(row);await s.flush()
            req=await s.scalar(select(STSRequest).where(STSRequest.application_id==app.id,STSRequest.req_id==req_id,
                STSRequest.status.in_(['WAITING_CALLBACK','ACTIVE'])))
            if req:await self._associate(s,app,req)

    async def sts_token(self,connection_id):
        async with self.rt.db.session() as s:
            c=await s.get(Connection,connection_id)
            if not c:raise MeetingError('STS_NOT_READY',409)
            app=await s.get(Application,c.application_id)
            row,data=await self.rt.admin.read_secret(s,app,'STS',connection_id=c.id)
            if row.expires_at<=utcnow()+timedelta(seconds=30):raise MeetingError('STS_NOT_READY',409)
            return data['sts_token']

    async def own_connections(self,principal):
        await self.rt.admin.human(principal)
        async with self.rt.db.session() as s:
            rows=(await s.execute(select(Connection).where(Connection.org_id==principal.org_id,
                Connection.member_id==principal.member_id,Connection.deleted_at.is_(None)))).scalars()
            return {'items':[safe_row(row,FIELDS['connections'][2]) for row in rows]}

    async def revoke_own(self,principal,connection_id):
        await self.rt.admin.human(principal)
        async with self.rt.db.lock('policy:'+principal.org_id),self.rt.db.transaction() as s:
            c=await self.rt.admin._get(s,Connection,principal.org_id,connection_id)
            if c.kind!='THIRD_PARTY_OAUTH' or c.member_id!=principal.member_id:raise MeetingError('PERMISSION_DENIED',403)
            c.status='REVOKED';c.version+=1
            for cr in (await s.execute(select(Credential).where(Credential.connection_id==c.id))).scalars():cr.active=False
            await self.rt.policy.bump(s,principal.org_id);record(s,principal,'oauth.revoked',resource_id=c.id)
            return {'id':c.id,'status':c.status}
