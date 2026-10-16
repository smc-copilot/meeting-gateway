"""Permission-bound backfill and durable incremental pagination. OAuth never scans enterprise data."""
from datetime import datetime,timedelta
from sqlalchemy import select
from app.core.types import Principal,utcnow
from app.core.errors import MeetingError
from app.models import AccessGrant,Connection,Meeting,OrganizationPolicy,SyncPolicy,Client,Recording,Asset
from app.schemas.requests import SyncRequest
from app.services.permission_service import live,BUSINESS_ACTIONS
from app.services.audit_service import record


def windows(start,end,days):
    current=start
    while current<end:
        stop=min(end,current+timedelta(days=days))
        yield int(current.timestamp()),int(stop.timestamp())
        current=stop


class SyncService:
    def __init__(self,runtime):self.rt=runtime

    async def ingestion(self,s,principal,connection,grant_id=None):
        if principal.actor_type!='SERVICE' or connection.kind!='ENTERPRISE_AKSK':
            raise MeetingError('PERMISSION_DENIED',403)
        policy=await s.scalar(select(OrganizationPolicy).where(OrganizationPolicy.org_id==principal.org_id,
            OrganizationPolicy.deleted_at.is_(None)))
        if not policy or not policy.retention_confirmed:raise MeetingError('RETENTION_UNCONFIRMED',409)
        grants=(await s.execute(select(AccessGrant).where(AccessGrant.org_id==principal.org_id,
            AccessGrant.subject_type=='SERVICE',AccessGrant.subject_id==principal.client_id,
            AccessGrant.purpose=='INGESTION',AccessGrant.deleted_at.is_(None)))).scalars()
        candidates=[g for g in grants if live(g) and connection.id in g.connection_ids and 'meeting.sync.manage' in g.actions]
        if any(g.effect=='DENY' for g in candidates):raise MeetingError('SOURCE_GRANT_INVALID',403)
        candidates=[g for g in candidates if g.effect=='ALLOW' and (grant_id is None or g.id==grant_id)]
        if not candidates:raise MeetingError('SOURCE_GRANT_INVALID',403)
        return sorted(candidates,key=lambda g:g.id)[0]

    async def request(self,principal,body:SyncRequest):
        principal=await self.rt.auth.revalidate(principal)
        c,app=await self.rt.connections.owned(principal,body.connection_ref)
        async with self.rt.db.transaction() as s:
            ingestion_id=None
            if body.kind=='CONTENT':
                rec,m=await self.rt.meetings.recording(s,principal,body.recording_id,'meeting.content.read',asset_type=body.content_type)
                if rec.connection_id!=c.id:raise MeetingError('RESOURCE_NOT_ACCESSIBLE',404)
            else:
                await self.rt.policy.require(s,principal,'meeting.sync.manage',connection_id=c.id)
                if body.kind=='CORP_RECORDS':
                    if not self.rt.settings.meeting_corp_sync_enabled:raise MeetingError('FEATURE_DISABLED',409)
                    ingestion_id=(await self.ingestion(s,principal,c)).id
                elif principal.actor_type=='SERVICE':
                    raise MeetingError('PERMISSION_DENIED',403)
                if body.meeting_id:
                    m=await self.rt.meetings.row(s,principal,body.meeting_id)
                    if m.connection_id!=c.id:raise MeetingError('RESOURCE_NOT_ACCESSIBLE',404)
            job=await self.rt.jobs.enqueue(s,'CONTENT' if body.kind=='CONTENT' else 'SYNC',principal,body.model_dump(mode='json'),
                                          connection_id=c.id,ingestion_grant_id=ingestion_id)
            return self.rt.jobs.info(job)

    async def _check(self,job,lease_token):
        p=await self.rt.auth.revalidate(Principal.model_validate(job.principal_data))
        c,app=await self.rt.connections.owned(p,job.connection_id)
        async with self.rt.db.session() as s:
            await self.rt.jobs.fence(s,job.id,lease_token)
            await self.rt.policy.require(s,p,'meeting.sync.manage',connection_id=c.id)
            grant=await self.ingestion(s,p,c,job.ingestion_grant_id) if job.ingestion_grant_id else None
            if p.actor_type=='SERVICE' and not grant:raise MeetingError('SOURCE_GRANT_INVALID',403)
        op=await self.rt.connections.operator(c,member_id=p.member_id,for_ingestion=grant is not None)
        return p,c,op,grant

    async def run(self,job,lease_token):
        data=SyncRequest.model_validate(job.payload)
        async with self.rt.db.lock('sync-connection:'+job.connection_id):
            p,c,op,grant=await self._check(job,lease_token)
            if data.kind=='CORP_RECORDS' and not self.rt.settings.meeting_corp_sync_enabled:raise MeetingError('FEATURE_DISABLED',409)
            progress=dict(job.progress or {});completed=int(progress.get('processed_rows',0))
            if data.kind=='USER_UPCOMING':
                pos=int(progress.get('pos',0));cursory=int(progress.get('cursory',0));seen_cursors=set()
                for _ in range(10000):
                    p,c,op,grant=await self._check(job,lease_token)
                    raw=await self.rt.tencent.call(c.id,'upcoming',op,query={'pos':pos,'cursory':cursory})
                    rows=raw.get('meeting_info_list')
                    if not isinstance(rows,list):raise MeetingError('UPSTREAM_CONTRACT_ERROR',502)
                    remaining=int(raw.get('remaining',0));nextpos=int(raw.get('next_pos',0));nextcursory=int(raw.get('next_cursory',0))
                    if remaining and (not rows or (nextpos,nextcursory)==(pos,cursory) or (nextpos,nextcursory) in seen_cursors):
                        raise MeetingError('UPSTREAM_CONTRACT_ERROR',502)
                    async with self.rt.db.transaction() as s:
                        current=await self.rt.jobs.fence(s,job.id,lease_token)
                        for row in rows:await self.rt.meetings.upsert(s,c,row,purpose='USER',owner_member_id=p.member_id)
                        completed+=len(rows);current.progress={**progress,'processed_rows':completed,'pos':nextpos,'cursory':nextcursory}
                    if not remaining:break
                    seen_cursors.add((pos,cursory));pos,cursory=nextpos,nextcursory
                else:raise MeetingError('UPSTREAM_CONTRACT_ERROR',502)
            else:
                start,end=data.start_at,data.end_at;external_meeting=None
                if data.kind=='MEETING_RECORDS':
                    async with self.rt.db.session() as s:
                        m=await self.rt.meetings.row(s,p,data.meeting_id)
                        if not m.start_at:raise MeetingError('INVALID_REQUEST',422)
                        start=start or m.start_at-timedelta(days=1)
                        end=end or (m.end_at or utcnow())+timedelta(days=1);external_meeting=m.external_id
                if start is None or end is None or start>=end:raise MeetingError('INVALID_REQUEST',422)
                intervals=list(windows(start,end,90 if data.kind=='USER_HISTORY' else 31))
                if len(intervals)>120:raise MeetingError('INVALID_REQUEST',422)
                first=int(progress.get('window_index',0))
                for index in range(first,len(intervals)):
                    begin,stop=intervals[index]
                    page=int(progress.get('page',1)) if index==first else 1
                    for _ in range(100000):
                        p,c,op,grant=await self._check(job,lease_token)
                        query={'start_time':begin,'end_time':stop,'page':page,'page_size':20}
                        if external_meeting:query['meeting_id']=external_meeting
                        operation={'CORP_RECORDS':'corp_records','USER_HISTORY':'history'}.get(data.kind,'records')
                        raw=await self.rt.tencent.call(c.id,operation,op,query=query,heartbeat=lambda:self.rt.jobs.heartbeat(job.id,lease_token))
                        rows=raw.get('meeting_info_list' if operation=='history' else 'record_meetings')
                        if not isinstance(rows,list) or not isinstance(raw.get('total_page'),int):raise MeetingError('UPSTREAM_CONTRACT_ERROR',502)
                        if raw.get('current_page',page)!=page or (not rows and page<raw['total_page']):raise MeetingError('UPSTREAM_CONTRACT_ERROR',502)
                        final=page>=raw['total_page']
                        async with self.rt.db.transaction() as s:
                            current=await self.rt.jobs.fence(s,job.id,lease_token)
                            if grant:await self.ingestion(s,p,c,grant.id)
                            for row in rows:
                                imported = await self.rt.meetings.upsert(s,c,row,purpose='INGESTION' if grant else 'USER',
                                    owner_member_id=None if grant else p.member_id,ingestion_grant_id=grant.id if grant else None,
                                    history=data.kind=='USER_HISTORY')
                                await self._queue_contents(s,p,c,imported,grant,job.id)
                            completed+=len(rows)
                            current.progress={**progress,'window_index':index+1 if final else index,'page':1 if final else page+1,'processed_rows':completed}
                        if final:break
                        page+=1
                    else:raise MeetingError('UPSTREAM_CONTRACT_ERROR',502)
            async with self.rt.db.transaction() as s:
                current=await self.rt.jobs.fence(s,job.id,lease_token)
                connection=await s.get(Connection,c.id);connection.last_synced_at=utcnow()
                policy_id=(job.progress or {}).get('sync_policy_id')
                if policy_id:
                    policy=await s.get(SyncPolicy,policy_id)
                    if policy and policy.connection_id==c.id:policy.last_success_at=data.end_at or utcnow()
                coverage={'kind':data.kind,'start_at':data.start_at.isoformat() if data.start_at else None,
                          'end_at':data.end_at.isoformat() if data.end_at else None,'completed_at':utcnow().isoformat()}
                connection.sync_coverage=((connection.sync_coverage or [])+[coverage])[-100:]
                current.progress={**(current.progress or {}),'complete':True,'processed_rows':completed}
                record(s,p,'sync.completed',resource_id=c.id,details={'job_id':job.id})

    async def _queue_contents(self, s, p, connection, meeting, grant, parent_id):
        records = list((await s.execute(select(Recording).where(Recording.meeting_id == meeting.id,
            Recording.deleted_at.is_(None), Recording.state.in_(['READY','UNKNOWN'])))).scalars())
        for rec in records:
            for kind in ('transcript','minutes'):
                if grant:
                    if grant.asset_types and kind not in grant.asset_types:
                        continue
                elif not await self.rt.policy.allowed(s,p,'meeting.content.read',meeting=meeting,asset_type=kind):
                    continue
                existing = await s.scalar(select(Asset).where(Asset.recording_id == rec.id,
                    Asset.asset_type == kind,Asset.deleted_at.is_(None)).order_by(Asset.created_at.desc()).limit(1))
                if (existing and existing.state == 'READY' and existing.is_complete and existing.expires_at
                    and existing.expires_at > utcnow() and existing.source_health_at):
                    continue
                await self.rt.jobs.enqueue(s,'INGEST_CONTENT' if grant else 'CONTENT',p,
                    {'recording_id':rec.id,'content_type':kind},connection_id=connection.id,
                    ingestion_grant_id=grant.id if grant else None,dedup_key=f'content:{parent_id}:{rec.id}:{kind}')

    async def admin_request(self,human,service_client_id,body):
        async with self.rt.db.session() as s:
            await self.rt.admin.require(s,human,'meeting.sync.manage')
            client=await self.rt.admin._get(s,Client,human.org_id,service_client_id)
            if not live(client) or not client.allow_service:raise MeetingError('PERMISSION_DENIED',403)
        p=Principal(org_id=human.org_id,actor_type='SERVICE',client_id=client.id,
            scopes=frozenset(client.allowed_scopes),audience=self.rt.settings.rest_resource_uri,trace_id=human.trace_id)
        result=await self.request(p,body)
        async with self.rt.db.transaction() as s:record(s,human,'sync.admin_requested',resource_id=result['id'])
        return result

    async def create_policy(self,human,body):
        if set(body)-{'connection_ref','client_id','ingestion_grant_id','interval_seconds','overlap_seconds','reason'}:
            raise MeetingError('INVALID_REQUEST',422)
        interval=int(body.get('interval_seconds',900));overlap=int(body.get('overlap_seconds',3600))
        if not 300<=interval<=86400 or not 60<=overlap<=31*86400:raise MeetingError('INVALID_REQUEST',422)
        c,app=await self.rt.connections.get(human.org_id,body['connection_ref'])
        async with self.rt.db.transaction() as s:
            await self.rt.admin.require(s,human,'meeting.sync.manage')
            client=await self.rt.admin._get(s,Client,human.org_id,body['client_id'])
            p=Principal(org_id=human.org_id,actor_type='SERVICE',client_id=client.id,scopes=frozenset(client.allowed_scopes),audience=self.rt.settings.rest_resource_uri)
            await self.rt.policy.require(s,p,'meeting.sync.manage',connection_id=c.id)
            await self.ingestion(s,p,c,body['ingestion_grant_id'])
            row=SyncPolicy(org_id=human.org_id,connection_id=c.id,client_id=client.id,ingestion_grant_id=body['ingestion_grant_id'],
                interval_seconds=interval,overlap_seconds=overlap,next_run_at=utcnow(),enabled=True)
            s.add(row);await s.flush();record(s,human,'sync_policy.created',resource_id=row.id)
            return {'id':row.id,'enabled':True}

    async def schedule_due(self):
        if not self.rt.settings.meeting_corp_sync_enabled:return
        async with self.rt.db.lock('sync:scheduler'),self.rt.db.transaction() as s:
            due=(await s.execute(select(SyncPolicy).where(SyncPolicy.enabled.is_(True),SyncPolicy.deleted_at.is_(None),
                SyncPolicy.next_run_at<=utcnow()).limit(100).with_for_update(skip_locked=True))).scalars()
            for policy in due:
                client=await s.get(Client,policy.client_id)
                if not live(client) or not client.allow_service:policy.enabled=False;continue
                p=Principal(org_id=policy.org_id,actor_type='SERVICE',client_id=client.id,scopes=frozenset(client.allowed_scopes),
                    audience=self.rt.settings.rest_resource_uri)
                try:
                    c,app=await self.rt.connections.get(policy.org_id,policy.connection_id)
                    await self.rt.policy.require(s,p,'meeting.sync.manage',connection_id=c.id)
                    await self.ingestion(s,p,c,policy.ingestion_grant_id)
                except MeetingError:policy.enabled=False;continue
                end=utcnow();start=(policy.last_success_at or policy.next_run_at)-timedelta(seconds=policy.overlap_seconds)
                payload=SyncRequest(connection_ref=c.id,kind='CORP_RECORDS',start_at=start,end_at=end).model_dump(mode='json')
                payload_job=await self.rt.jobs.enqueue(s,'SYNC',p,payload,connection_id=c.id,ingestion_grant_id=policy.ingestion_grant_id,
                    dedup_key='schedule:'+policy.id+':'+str(int(policy.next_run_at.timestamp())))
                # Schedule checkpoint is not a success watermark. Only the finished job advances last_success_at.
                payload_job.progress={**(payload_job.progress or {}),'sync_policy_id':policy.id}
                policy.next_run_at=end+timedelta(seconds=policy.interval_seconds)
