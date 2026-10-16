"""Complete, source-bound Tencent text content. Never substitute a model-generated summary."""
import json
from datetime import timedelta
from sqlalchemy import select
from app.core.types import utcnow
from app.core.errors import MeetingError,UpstreamError
from app.core.security import canonical,digest
from app.models import Asset,Recording,Meeting,ResourceOrigin,OrganizationPolicy,Connection,SyncJob
from app.integrations.tencent_meeting.mapper import TranscriptCollector,normalize_minutes
from app.services.audit_service import record


class ContentService:
    def __init__(self,runtime):self.rt=runtime

    def info(self,a):
        return {'id':a.id,'recording_id':a.recording_id,'asset_type':a.asset_type,'state':a.state,'is_complete':a.is_complete,
                'content_version':a.content_hash,'asset_version':a.content_hash,'content_state':a.state,'fetched_at':a.fetched_at,'expires_at':a.expires_at}

    async def _source(self,principal,rec):
        c,app=await self.rt.connections.owned(principal,rec.connection_id)
        # Enterprise ingestion sources deliberately use the approved acquisition operator, not impersonated employee IDs.
        operator=await self.rt.connections.operator(c,for_ingestion=c.kind=='ENTERPRISE_AKSK',
                                                    member_id=principal.member_id if c.kind=='THIRD_PARTY_OAUTH' else None)
        return c,operator

    async def verify_source(self,principal,asset,*,force=False,for_download=False):
        if not force and asset.source_health_at and asset.source_health_at>utcnow()-timedelta(seconds=self.rt.settings.source_health_seconds):return
        async with self.rt.db.session() as s:
            rec,m=await self.rt.meetings.recording(s,principal,asset.recording_id,
                'meeting.content.download' if for_download else 'meeting.content.read',asset_type=asset.asset_type)
            await self.rt.policy.require(s,principal,'meeting.content.download' if for_download else 'meeting.content.read',meeting=m,asset=asset)
        c,op=await self._source(principal,rec)
        try:
            if asset.asset_type=='minutes' and not for_download:
                raw=await self.rt.tencent.call(c.id,'minutes',op,file_id=rec.external_file_id,
                     query={'llm':3,'minute_type':2,'text_type':2,'lang':'default'})
                normalize_minutes(raw)
            elif asset.asset_type=='transcript' and not for_download:
                raw=await self.rt.tencent.call(c.id,'transcript',op,file_id=rec.external_file_id,
                     query={'meeting_id':m.external_id,'pid':'0','limit':2})
                if not isinstance(raw.get('minutes',{}).get('paragraphs'),list):raise MeetingError('UPSTREAM_CONTRACT_ERROR',502)
            else:
                await self.rt.tencent.call(c.id,'record_detail',op,file_id=rec.external_file_id)
        except MeetingError as exc:
            if exc.reason in {'SOURCE_REMOVED','UPSTREAM_PERMISSION_DENIED','UPSTREAM_REAUTH_REQUIRED'}:
                async with self.rt.db.transaction() as s:
                    row=await s.get(Asset,asset.id);row.state='SOURCE_REMOVED' if exc.reason=='SOURCE_REMOVED' else 'BLOCKED'
                self.rt.metrics['source_access_revoked']+=1
            raise
        async with self.rt.db.transaction() as s:
            row=await s.get(Asset,asset.id);row.source_health_at=utcnow()

    async def _authorize_fetch(self, s, principal, recording_id, kind, ingestion_grant_id=None):
        if ingestion_grant_id is None:
            return await self.rt.meetings.recording(s, principal, recording_id, 'meeting.content.read', asset_type=kind)
        # Only private Worker paths supply this parameter. It is never accepted by HTTP/MCP schemas.
        rec = await self.rt.admin._get(s, Recording, principal.org_id, recording_id)
        c, app = await self.rt.connections.get(principal.org_id, rec.connection_id)
        await self.rt.policy.require(s, principal, 'meeting.sync.manage', connection_id=c.id)
        grant = await self.rt.sync.ingestion(s, principal, c, ingestion_grant_id)
        if grant.asset_types and kind not in grant.asset_types:
            raise MeetingError('SOURCE_GRANT_INVALID', 403)
        m = await self.rt.admin._get(s, Meeting, principal.org_id, rec.meeting_id)
        origin = await s.scalar(select(ResourceOrigin).where(ResourceOrigin.meeting_id == m.id,
            ResourceOrigin.connection_id == c.id, ResourceOrigin.ingestion_grant_id == grant.id,
            ResourceOrigin.enabled.is_(True), ResourceOrigin.deleted_at.is_(None)))
        if not origin:
            raise MeetingError('SOURCE_GRANT_INVALID', 403)
        return rec, m

    async def fetch_ingestion(self, job, lease_token):
        from app.core.types import Principal
        if job.kind != 'INGEST_CONTENT' or not job.ingestion_grant_id:
            raise MeetingError('PERMISSION_DENIED', 403)
        return await self.fetch(Principal.model_validate(job.principal_data), job.payload['recording_id'],
            job.payload['content_type'], job_id=job.id, lease_token=lease_token,
            _ingestion_grant_id=job.ingestion_grant_id)

    async def fetch(self,principal,recording_id,kind,*,job_id=None,lease_token=None,_ingestion_grant_id=None):
        if kind not in {'transcript','minutes'}:raise MeetingError('INVALID_REQUEST',422)
        principal=await self.rt.auth.revalidate(principal)
        async with self.rt.db.session() as s:
            rec,m=await self._authorize_fetch(s,principal,recording_id,kind,_ingestion_grant_id)
        c,operator=await self._source(principal,rec)
        async with self.rt.db.lock('content:'+rec.id+':'+kind):
            checkpoint_key=None
            if kind=='minutes':
                raw=await self.rt.tencent.call(c.id,'minutes',operator,file_id=rec.external_file_id,
                    query={'llm':3,'minute_type':2,'text_type':2,'lang':'default'})
                payload=normalize_minutes(raw)
                if not payload['minute'].strip():raise MeetingError('CONTENT_NOT_READY',409)
            else:
                collector=TranscriptCollector();pid='0';total_bytes=0;checkpoint_key=None
                if job_id:
                    async with self.rt.db.session() as s:
                        job=await s.get(SyncJob,job_id)
                        checkpoint_key=(job.progress or {}).get('checkpoint_key') if job else None
                    if checkpoint_key:
                        collector=TranscriptCollector.restore(json.loads(await self.rt.storage.get(checkpoint_key,principal.org_id,job_id)))
                        pid=collector.resume_pid()
                async def pulse():
                    if job_id and lease_token:await self.rt.jobs.heartbeat(job_id,lease_token)
                for page_index in range(self.rt.settings.transcript_max_pages):
                    if collector.complete:break
                    principal=await self.rt.auth.revalidate(principal)
                    async with self.rt.db.session() as s:
                        await self._authorize_fetch(s,principal,recording_id,kind,_ingestion_grant_id)
                        if job_id:await self.rt.jobs.fence(s,job_id,lease_token)
                    raw=await self.rt.tencent.call(c.id,'transcript',operator,file_id=rec.external_file_id,
                        query={'meeting_id':m.external_id,'pid':pid,'limit':self.rt.settings.transcript_page_size},heartbeat=pulse)
                    total_bytes+=len(canonical(raw))
                    if total_bytes>self.rt.settings.max_upstream_json_bytes:raise MeetingError('UPSTREAM_CONTRACT_ERROR',502)
                    pid=collector.add(raw)
                    if job_id and lease_token and not collector.complete:
                        blob=canonical(collector.snapshot())
                        new_key=await self.rt.storage.put(principal.org_id,job_id,blob)
                        if checkpoint_key and checkpoint_key!=new_key:await self.rt.storage.remove(checkpoint_key)
                        checkpoint_key=new_key
                        await self.rt.jobs.checkpoint(job_id,lease_token,{'checkpoint_key':checkpoint_key,
                            'checkpoint_version':digest(blob),'pid':collector.last_pid,'pages':collector.pages})
                    if pid is None:break
                payload=collector.finish()
            value=canonical(payload)
            if len(value)>self.rt.settings.max_upstream_json_bytes:raise MeetingError('UPSTREAM_CONTRACT_ERROR',502)
            fingerprint=digest(value);object_key=None
            try:
                async with self.rt.db.transaction() as s:
                    principal=await self.rt.auth.revalidate(principal)
                    rec,m=await self._authorize_fetch(s,principal,recording_id,kind,_ingestion_grant_id)
                    if job_id:await self.rt.jobs.fence(s,job_id,lease_token)
                    existing=await s.scalar(select(Asset).where(Asset.recording_id==rec.id,Asset.asset_type==kind,
                        Asset.content_hash==fingerprint,Asset.deleted_at.is_(None)))
                    if existing and existing.object_key and existing.state=='READY' and existing.expires_at>utcnow():
                        existing.source_health_at=utcnow();return self.info(existing)
                    policy=await s.scalar(select(OrganizationPolicy).where(OrganizationPolicy.org_id==principal.org_id))
                    retention=policy.content_days if policy else self.rt.settings.content_retention_days
                    asset=existing or Asset(org_id=m.org_id,meeting_id=m.id,recording_id=rec.id,connection_id=c.id,
                        asset_type=kind,content_hash=fingerprint,content_type='application/json')
                    if existing is None:s.add(asset)
                    old_key=asset.object_key
                    object_key=await self.rt.storage.put(m.org_id,asset.id,value)
                    asset.object_key=object_key;asset.state='READY';asset.is_complete=True;asset.fetched_at=utcnow()
                    asset.source_health_at=utcnow();asset.expires_at=utcnow()+timedelta(days=retention)
                    asset.details={'provider':'tencent_meeting','llm':3 if kind=='minutes' else None,'source_page_count':payload.get('source_page_count')}
                    await s.flush();record(s,principal,'content.imported',resource_id=asset.id)
                    result=self.info(asset)
                    await self.rt.events.publish('meeting.asset.ready',m.org_id,asset.id,{'asset_type':kind,'version':fingerprint},session=s)
                # Only remove an obsolete object after a successful database commit.
                if old_key and old_key!=object_key:await self.rt.storage.remove(old_key)
                if checkpoint_key:await self.rt.storage.remove(checkpoint_key)
                return result
            except BaseException:
                # An orphan encrypted object is safe to leave for reconciliation; never delete an object after a committed row references it.
                raise

    async def read(self,principal,recording_id,kind,*,limit=100,cursor=None,fetch='cache'):
        if kind not in {'transcript','minutes'} or not 1<=limit<=500:raise MeetingError('INVALID_REQUEST',422)
        async with self.rt.db.session() as s:
            rec,m=await self.rt.meetings.recording(s,principal,recording_id,'meeting.content.read',asset_type=kind)
            asset=await s.scalar(select(Asset).where(Asset.recording_id==rec.id,Asset.asset_type==kind,
                Asset.deleted_at.is_(None)).order_by(Asset.fetched_at.desc().nullslast(),Asset.created_at.desc()).limit(1))
            if not asset or not asset.is_complete or not asset.object_key or asset.state!='READY' or asset.expires_at<=utcnow():
                if fetch!='ensure':
                    raise MeetingError('CONTENT_NOT_READY',409)
                async with self.rt.db.transaction() as tx:
                    job=await self.rt.jobs.enqueue(tx,'CONTENT',principal,{'recording_id':recording_id,'content_type':kind},
                        connection_id=rec.connection_id,dedup_key='ensure-content:'+recording_id+':'+kind)
                return {'accepted':True,'job_id':job.id}
            await self.rt.policy.require(s,principal,'meeting.content.read',meeting=m,asset=asset)
            version=await self.rt.policy.policy_version(s,principal.org_id)
        await self.verify_source(principal,asset)
        try:content=json.loads(await self.rt.storage.get(asset.object_key,principal.org_id,asset.id))
        except (FileNotFoundError,ValueError):raise MeetingError('CONTENT_NOT_READY',409)
        binding=f'{principal.binding}:{asset.id}:{asset.content_hash}:{version}'
        offset=int(self.rt.cursors.decode(cursor,binding=binding)['offset']) if cursor else 0
        next_cursor=None
        if kind=='transcript':
            all_paragraphs=content['paragraphs']
            if offset<0 or offset>len(all_paragraphs):raise MeetingError('CURSOR_INVALID',400)
            content={**content,'paragraphs':all_paragraphs[offset:offset+limit]}
            if offset+limit<len(all_paragraphs):next_cursor=self.rt.cursors.encode({'offset':offset+limit},binding=binding)
        elif cursor:raise MeetingError('CURSOR_INVALID',400)
        # Last authorization check after storage/network work prevents a revocation during I/O from becoming a read bypass.
        async with self.rt.db.transaction() as s:
            principal=await self.rt.auth.revalidate(principal)
            current=await s.get(Asset,asset.id)
            await self.rt.policy.require(s,principal,'meeting.content.read',meeting=m,asset=current)
            record(s,principal,'content.read',resource_id=asset.id)
        return {**self.info(asset),'content':content,'next_cursor':next_cursor}
