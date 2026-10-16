"""Authenticated inbox and transactional outbox. Callbacks enqueue work, never run AI or OA writes."""
import asyncio
from datetime import timedelta
import hashlib
import hmac
import json
import secrets
import uuid
from sqlalchemy import select
from app.core.types import Principal,utcnow
from app.core.errors import MeetingError
from app.core.security import canonical,digest,random_token
from app.models import (Application,Connection,Client,AgentGrant,AccessGrant,EventInbox,EventOutbox,Subscription,
    DeliveredResource,Meeting,Recording,Asset,Operation,SyncPolicy,SyncJob)
from app.services.permission_service import live
from app.services.audit_service import record
from app.storage.safe_http import SafeHTTP,validate_url
from app.integrations.tencent_meeting.webhook import verify_callback,decrypt_message

EVENT_TYPES=frozenset({'meeting.synced','meeting.asset.ready','meeting.create.succeeded','meeting.create.unknown',
                       'meeting.resource.invalidated','meeting.authorization.revoked'})
TENCENT_EVENTS=frozenset({'common.sts-token','recording.completed','recording.failed','smart.transcripts','smart.minutes',
                         'meeting.created','meeting.ended','recording.deleted'})


class EventService:
    def __init__(self,runtime):self.rt=runtime

    async def _callback(self,receiver_id,encrypted,headers):
        if not isinstance(encrypted,str) or len(encrypted)>self.rt.settings.max_request_bytes:
            raise MeetingError('INVALID_REQUEST',413)
        if any(not isinstance(headers.get(k),str) or not headers[k] or len(headers[k])>256 for k in ('timestamp','nonce','signature')):
            raise MeetingError('AUTH_REQUIRED',401)
        async with self.rt.db.session() as s:
            app=await s.scalar(select(Application).where(Application.receiver_id==receiver_id,
                Application.enabled.is_(True),Application.deleted_at.is_(None)))
            if not app:raise MeetingError('RESOURCE_NOT_ACCESSIBLE',404)
            _,credential=await self.rt.admin.read_secret(s,app,'WEBHOOK')
        if not verify_callback(credential['token'],headers['timestamp'],headers['nonce'],encrypted,headers['signature']):
            raise MeetingError('AUTH_REQUIRED',401)
        try:plain=decrypt_message(encrypted,credential['encoding_key'])
        except ValueError:raise MeetingError('AUTH_REQUIRED',401)
        return app,plain

    async def challenge(self,receiver_id,check_str,headers):
        app,plain=await self._callback(receiver_id,check_str,headers)
        async with self.rt.db.transaction() as s:
            current=await s.get(Application,app.id);current.webhook_verified_at=utcnow()
        return plain

    async def receive(self,receiver_id,encrypted,headers):
        app,plain=await self._callback(receiver_id,encrypted,headers)
        try:payload=json.loads(plain)
        except (ValueError,UnicodeError):raise MeetingError('INVALID_REQUEST',422)
        if (not isinstance(payload,dict) or not isinstance(payload.get('event'),str) or len(payload['event'])>64
            or not isinstance(payload.get('payload'),list) or len(payload['payload'])>1000):
            raise MeetingError('INVALID_REQUEST',422)
        fingerprint=digest(canonical([app.id,payload]))
        async with self.rt.db.lock('inbox:'+fingerprint),self.rt.db.transaction() as s:
            old=await s.scalar(select(EventInbox).where(EventInbox.fingerprint==fingerprint))
            if old:return old.id
            inbox=EventInbox(org_id=app.org_id,application_id=app.id,event_type=payload['event'],fingerprint=fingerprint,
                safe_summary={'event':payload['event'],'payload_count':len(payload['payload'])},
                state='PENDING' if payload['event'] in TENCENT_EVENTS else 'IGNORED')
            # The encrypted payload is not an admin-readable diagnostics field. STS payload is wiped after processing.
            inbox.encrypted_payload=self.rt.keys.encrypt(payload,'inbox:'+app.id+':'+inbox.id)
            s.add(inbox);await s.flush()
            if inbox.state=='PENDING':
                internal=Principal(org_id=app.org_id,actor_type='SERVICE',client_id='event-internal',trace_id=inbox.id)
                await self.rt.jobs.enqueue(s,'INBOX',internal,{'inbox_id':inbox.id},dedup_key='inbox:'+inbox.id)
            current=await s.get(Application,app.id);current.last_callback_at=utcnow()
            return inbox.id

    async def process_inbox(self,job,lease_token):
        async with self.rt.db.session() as s:
            await self.rt.jobs.fence(s,job.id,lease_token)
            inbox=await s.get(EventInbox,job.payload['inbox_id'])
            if not inbox or inbox.state in {'PROCESSED','IGNORED'}:return
            app=await s.get(Application,inbox.application_id)
            if not app or not app.enabled or app.deleted_at is not None:raise MeetingError('SOURCE_GRANT_INVALID',403)
            payload=self.rt.keys.decrypt(inbox.encrypted_payload,'inbox:'+app.id+':'+inbox.id)
        if inbox.event_type=='common.sts-token':
            for entry in payload['payload']:
                if not isinstance(entry,dict):raise MeetingError('INVALID_REQUEST',422)
                await self.rt.connections.receive_sts(app.id,entry.get('token_info',{}),
                    operator_id=entry.get('operator',{}).get('userid'),operate_time_ms=int(entry.get('operate_time',0)))
        else:
            failed=self._event_failed(inbox.event_type,payload)
            async with self.rt.db.transaction() as s:
                await self.rt.jobs.fence(s,job.id,lease_token)
                conn_ids=list((await s.execute(select(Connection.id).where(Connection.application_id==app.id,
                    Connection.status.in_(['ACTIVE','DEGRADED']),Connection.deleted_at.is_(None)))).scalars())
                if not failed:
                    await self._dispatch_known_files(s,app,inbox,payload,conn_ids)
                policies=(await s.execute(select(SyncPolicy).where(SyncPolicy.connection_id.in_(conn_ids or ['']),
                    SyncPolicy.enabled.is_(True),SyncPolicy.deleted_at.is_(None)))).scalars()
                for policy in policies:policy.next_run_at=min(policy.next_run_at,utcnow())
            if not failed and inbox.event_type not in {'recording.deleted','recording.failed'}:
                await self._schedule_personal(app,inbox.id)
        async with self.rt.db.transaction() as s:
            await self.rt.jobs.fence(s,job.id,lease_token)
            row=await s.get(EventInbox,inbox.id);row.state='PROCESSED';row.processed_at=utcnow()
            if inbox.event_type=='common.sts-token':row.encrypted_payload=None
            result=payload.get('result') if isinstance(payload.get('result'),(int,bool,type(None))) else None
            if self._event_failed(inbox.event_type,payload):result=2
            row.safe_summary={**row.safe_summary,'result':result,'outcome':'FAILED' if result==2 else 'HANDLED'}

    async def _schedule_personal(self,app,event_id):
        if app.application_type!='THIRD_PARTY_OAUTH':return
        last=''
        while True:
            async with self.rt.db.session() as s:
                rows=list((await s.execute(select(Connection).where(Connection.application_id==app.id,
                    Connection.status=='ACTIVE',Connection.deleted_at.is_(None),Connection.id>last).order_by(Connection.id).limit(100))).scalars())
                client=await s.scalar(select(Client).where(Client.org_id==app.org_id,Client.client_type=='PORTAL',Client.enabled.is_(True)))
            if not client or not rows:return
            for c in rows:
                last=c.id
                try:
                    member=await self.rt.backend.resolve(c.org_id,c.member_id)
                    p=Principal(org_id=c.org_id,actor_type='MEMBER',client_id=client.id,member_id=member.member_id,user_id=member.user_id,
                        scopes=frozenset(client.allowed_scopes),audience=self.rt.settings.rest_resource_uri)
                    async with self.rt.db.transaction() as s:
                        await self.rt.policy.require(s,p,'meeting.sync.manage',connection_id=c.id)
                        end=utcnow();start=end-timedelta(days=2)
                        from app.schemas.requests import SyncRequest
                        data=SyncRequest(kind='USER_RECORDS',connection_ref=c.id,start_at=start,end_at=end)
                        await self.rt.jobs.enqueue(s,'SYNC',p,data.model_dump(mode='json'),connection_id=c.id,
                                                   dedup_key='event-user-sync:'+event_id+':'+c.id)
                except MeetingError as exc:
                    if exc.reason=='IDENTITY_SERVICE_UNAVAILABLE':raise
                    continue
            if len(rows)<100:return

    @staticmethod
    def _event_failed(event_type,payload):
        if event_type in {'recording.failed'}:return True
        if payload.get('result') in {2,'2'}:return True
        return any(isinstance(entry,dict) and entry.get('result') in {2,'2'} for entry in payload.get('payload') or [])

    def _file_ids(self,entry):
        found=[]
        if entry.get('record_file_id') is not None:found.append(str(entry['record_file_id']))
        files=entry.get('recording_files',entry.get('record_files',[]))
        if isinstance(files,list):
            found.extend(str(item['record_file_id']) for item in files if isinstance(item,dict) and item.get('record_file_id') is not None)
        return found

    async def _dispatch_known_files(self,s,app,inbox,payload,conn_ids):
        if not conn_ids:return
        grants=list((await s.execute(select(AccessGrant).where(AccessGrant.org_id==app.org_id,AccessGrant.purpose=='INGESTION',
            AccessGrant.effect=='ALLOW',AccessGrant.enabled.is_(True),AccessGrant.deleted_at.is_(None)))).scalars())
        for entry in payload['payload']:
            if not isinstance(entry,dict):raise MeetingError('INVALID_REQUEST',422)
            if entry.get('result') in {2,'2'}:continue
            file_ids=self._file_ids(entry)
            if not file_ids:continue
            recordings=list((await s.execute(select(Recording).where(Recording.connection_id.in_(conn_ids),
                Recording.external_file_id.in_(file_ids),Recording.deleted_at.is_(None)))).scalars())
            for recording in recordings:
                if inbox.event_type=='recording.deleted':
                    recording.state='SOURCE_REMOVED'
                    for asset in (await s.execute(select(Asset).where(Asset.recording_id==recording.id,Asset.deleted_at.is_(None)))).scalars():
                        asset.state='SOURCE_REMOVED';asset.source_health_at=None;asset.is_complete=False
                    continue
                for asset in (await s.execute(select(Asset).where(Asset.recording_id==recording.id,Asset.deleted_at.is_(None)))).scalars():
                    asset.source_health_at=None
                connection=await s.get(Connection,recording.connection_id)
                meeting=await s.get(Meeting,recording.meeting_id)
                grant=next((item for item in grants if connection and connection.id in (item.connection_ids or [])),None)
                if grant is None or connection is None or meeting is None:continue
                principal=Principal(org_id=app.org_id,actor_type='SERVICE',client_id=grant.subject_id,
                    scopes=frozenset(grant.actions or []),audience=self.rt.settings.rest_resource_uri,trace_id=inbox.id)
                await self.rt.sync._queue_contents(s,principal,connection,meeting,grant,inbox.id)

    async def publish(self,event_type,org_id,resource_id,details=None,*,session=None):
        if event_type not in EVENT_TYPES:raise ValueError('Unknown internal event type')
        if session is None:
            async with self.rt.db.transaction() as s:
                return await self.publish(event_type,org_id,resource_id,details,session=s)
        event_id=str(uuid.uuid4())
        safe={k:v for k,v in (details or {}).items() if k in {'version','state','asset_type','trace_id'} and isinstance(v,(str,int,bool,type(None)))}
        payload={'event_id':event_id,'event_type':event_type,'resource_id':resource_id,'occurred_at':utcnow().isoformat(),**safe}
        subscriptions=(await session.execute(select(Subscription).where(Subscription.org_id==org_id,
            Subscription.enabled.is_(True),Subscription.deleted_at.is_(None)))).scalars()
        for sub in subscriptions:
            if event_type not in sub.event_types:continue
            row=EventOutbox(org_id=org_id,event_id=event_id,subscription_id=sub.id,event_type=event_type,
                resource_id=resource_id,payload=payload,state='PENDING',run_after=utcnow())
            session.add(row);await session.flush()
            internal=Principal(org_id=org_id,actor_type='SERVICE',client_id='event-internal')
            await self.rt.jobs.enqueue(session,'OUTBOX',internal,{'outbox_id':row.id},dedup_key='outbox:'+row.id)
        return event_id

    async def recipient(self,s,sub):
        client=await s.get(Client,sub.client_id)
        if not live(client) or client.org_id!=sub.org_id:raise MeetingError('PERMISSION_DENIED',403)
        if sub.member_id:
            member=await self.rt.backend.resolve(sub.org_id,sub.member_id)
            actor='AGENT' if sub.agent_grant_id else 'MEMBER'
            p=Principal(org_id=sub.org_id,client_id=client.id,actor_type=actor,member_id=member.member_id,user_id=member.user_id,
                scopes=frozenset(client.allowed_scopes),agent_id=client.agent_id if actor=='AGENT' else None,
                agent_grant_id=sub.agent_grant_id,audience=self.rt.settings.rest_resource_uri)
            if client.agent_id and actor!='AGENT':raise MeetingError('PERMISSION_DENIED',403)
        else:
            if not client.allow_service:raise MeetingError('PERMISSION_DENIED',403)
            p=Principal(org_id=sub.org_id,client_id=client.id,actor_type='SERVICE',scopes=frozenset(client.allowed_scopes),
                audience=self.rt.settings.rest_resource_uri)
        return await self.rt.auth.revalidate(p)

    async def can_deliver(self,s,sub,event_type,resource_id):
        if not live(sub):return False
        client=await s.get(Client,sub.client_id)
        if not live(client) or client.org_id!=sub.org_id:return False
        if event_type in {'meeting.resource.invalidated','meeting.authorization.revoked'}:
            previous=await s.scalar(select(DeliveredResource).where(DeliveredResource.subscription_id==sub.id,
                DeliveredResource.resource_id==resource_id,DeliveredResource.deleted_at.is_(None)))
            return previous is not None
        try:p=await self.recipient(s,sub)
        except MeetingError as exc:
            if exc.reason=='IDENTITY_SERVICE_UNAVAILABLE':raise
            return False
        if event_type.startswith('meeting.create.'):
            op=await s.get(Operation,resource_id)
            return bool(op and op.org_id==p.org_id and op.client_id==p.client_id and op.owner_member_id==p.member_id
                        and op.agent_grant_id==p.agent_grant_id)
        if event_type=='meeting.asset.ready':
            asset=await s.get(Asset,resource_id)
            if not asset or asset.org_id!=p.org_id or asset.deleted_at:return False
            meeting=await s.get(Meeting,asset.meeting_id)
            return bool(meeting and await self.rt.policy.allowed(s,p,'meeting.content.read',meeting=meeting,asset=asset))
        meeting=await s.get(Meeting,resource_id)
        return bool(meeting and meeting.org_id==p.org_id and meeting.deleted_at is None
                    and await self.rt.policy.allowed(s,p,'meeting.read',meeting=meeting))

    async def deliver(self,job,lease_token):
        async with self.rt.db.session() as s:
            await self.rt.jobs.fence(s,job.id,lease_token)
            row=await s.get(EventOutbox,job.payload['outbox_id'])
            if not row or row.state=='DELIVERED':return
            sub=await s.get(Subscription,row.subscription_id)
            if not sub or not await self.can_deliver(s,sub,row.event_type,row.resource_id):
                async with self.rt.db.transaction() as write:
                    current=await write.get(EventOutbox,row.id);current.state='SUPPRESSED';current.last_reason='PERMISSION_DENIED'
                return
            secret=self.rt.keys.decrypt(sub.secret_ciphertext,'subscription:'+sub.org_id+':'+sub.id)
            payload=canonical(row.payload)
        safe=SafeHTTP(self.rt.settings.notification_allowed_hosts,allowed_networks=self.rt.settings.notification_allowed_networks)
        safe.check(sub.destination)
        timestamp=str(int(utcnow().timestamp()));nonce=secrets.token_hex(16)
        signature=hmac.new(secret.encode(),timestamp.encode()+b'.'+nonce.encode()+b'.'+payload,hashlib.sha256).hexdigest()
        headers={'Content-Type':'application/json','X-Meeting-Event-ID':row.event_id,
            'X-Meeting-Timestamp':timestamp,'X-Meeting-Nonce':nonce,'X-Meeting-Signature':'sha256='+signature}
        try:
            async with asyncio.timeout(10),safe.session() as http:
                async with http.post(sub.destination,data=payload,headers=headers,allow_redirects=False) as response:
                    # Never log/read arbitrary response content from a consumer endpoint.
                    if not 200<=response.status<300:raise MeetingError('UPSTREAM_UNAVAILABLE',503)
        except (OSError,TimeoutError) as exc:raise MeetingError('UPSTREAM_UNAVAILABLE',503) from exc
        async with self.rt.db.transaction() as s:
            await self.rt.jobs.fence(s,job.id,lease_token)
            current=await s.get(EventOutbox,row.id);current.state='DELIVERED';current.delivered_at=utcnow();current.attempts=job.attempts
            previous=await s.scalar(select(DeliveredResource).where(DeliveredResource.subscription_id==sub.id,
                DeliveredResource.resource_id==row.resource_id,DeliveredResource.deleted_at.is_(None)))
            if previous:previous.last_delivered_at=utcnow()
            else:s.add(DeliveredResource(org_id=sub.org_id,subscription_id=sub.id,resource_id=row.resource_id,last_delivered_at=utcnow()))

    async def create_subscription(self,human,data):
        if set(data)-{'client_id','destination','event_types','member_id','agent_grant_id','reason'}:raise MeetingError('INVALID_REQUEST',422)
        if not data.get('event_types') or not set(data['event_types'])<=EVENT_TYPES or len(data.get('reason',''))<3:
            raise MeetingError('INVALID_REQUEST',422)
        validate_url(data['destination'],self.rt.settings.notification_allowed_hosts)
        secret=random_token('webhook')
        async with self.rt.db.transaction() as s:
            await self.rt.admin.require(s,human,'meeting.client.manage')
            client=await self.rt.admin._get(s,Client,human.org_id,data['client_id'])
            row=Subscription(org_id=human.org_id,client_id=client.id,destination=data['destination'],
                event_types=data['event_types'],member_id=data.get('member_id'),agent_grant_id=data.get('agent_grant_id'),secret_ciphertext='',enabled=True)
            await self.recipient(s,row)
            row.secret_ciphertext=self.rt.keys.encrypt(secret,'subscription:'+row.org_id+':'+row.id)
            s.add(row);await s.flush();record(s,human,'subscription.created',resource_id=row.id)
            return {'id':row.id,'signing_secret':secret,'event_types':row.event_types}

    async def invalidate_delivery_access(self):
        """Revoke cached delivery permission without disclosing IDs to a new consumer."""
        async with self.rt.db.lock('events:invalidation'):
            last=''
            while True:
                async with self.rt.db.transaction() as s:
                    seen=list((await s.execute(select(DeliveredResource).where(DeliveredResource.deleted_at.is_(None),
                        DeliveredResource.id>last).order_by(DeliveredResource.id).limit(50))).scalars())
                    if not seen:return
                    for previous in seen:
                        last=previous.id;sub=await s.get(Subscription,previous.subscription_id)
                        if not live(sub):continue
                        if await s.get(Operation,previous.resource_id):continue
                        asset=await s.get(Asset,previous.resource_id)
                        event='meeting.asset.ready' if asset else 'meeting.synced'
                        if await self.can_deliver(s,sub,event,previous.resource_id):continue
                        if 'meeting.resource.invalidated' not in sub.event_types:continue
                        # The previous-delivery tombstone remains through retries. Dedup once per entitlement version.
                        pv=await self.rt.policy.policy_version(s,sub.org_id)
                        key=f'invalidate:{sub.id}:{previous.resource_id}:{pv}'
                        old=await s.scalar(select(SyncJob).where(SyncJob.dedup_key==key))
                        if old:continue
                        eid=str(uuid.uuid4())
                        out=EventOutbox(org_id=sub.org_id,event_id=eid,subscription_id=sub.id,event_type='meeting.resource.invalidated',
                            resource_id=previous.resource_id,payload={'event_id':eid,'event_type':'meeting.resource.invalidated',
                            'resource_id':previous.resource_id,'occurred_at':utcnow().isoformat()},state='PENDING',run_after=utcnow())
                        s.add(out);await s.flush()
                        internal=Principal(org_id=sub.org_id,actor_type='SERVICE',client_id='event-internal')
                        await self.rt.jobs.enqueue(s,'OUTBOX',internal,{'outbox_id':out.id},dedup_key=key)
                if len(seen)<50:return
