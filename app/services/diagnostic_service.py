"""Explicit, read-only diagnostics. No arbitrary signed URL/body replay and no response body exposure."""
import time
from urllib.parse import urlsplit
from sqlalchemy import select
from app.core.errors import MeetingError,UpstreamError
from app.core.types import utcnow
from app.models import Credential,STSRequest,EventInbox
from app.services.audit_service import record

PROBES=('configuration','oauth_user_info','upcoming','history','records','corp_records','record_detail','transcript','minutes')
CONTENT_PROBES={'record_detail','transcript','minutes'}


class DiagnosticService:
    def __init__(self,runtime):self.rt=runtime

    def _chain(self,connection,current,status):
        stored=(connection.capabilities or {})
        items=[]
        for name in PROBES:
            if name==current:items.append({'probe':name,'status':status})
            elif name in stored:items.append({'probe':name,'status':stored[name].get('status','NOT_RUN')})
            else:items.append({'probe':name,'status':'NOT_RUN'})
        return items

    async def run(self,human,connection_id,probe,recording_id=None):
        if probe not in PROBES:raise MeetingError('INVALID_REQUEST',422)
        c,app=await self.rt.connections.get(human.org_id,connection_id,allow_inactive=probe=='configuration')
        started=time.monotonic();operation=probe;rec=m=None
        async with self.rt.db.session() as s:
            await self.rt.admin.require(s,human,'meeting.diagnostics.run')
            if probe in CONTENT_PROBES:
                if not recording_id:raise MeetingError('INVALID_REQUEST',422)
                action='meeting.content.read'
                asset_type=None if probe=='record_detail' else ('minutes' if probe=='minutes' else 'transcript')
                rec,m=await self.rt.meetings.recording(s,human,recording_id,action,asset_type=asset_type)
                if rec.connection_id!=c.id:raise MeetingError('RESOURCE_NOT_ACCESSIBLE',404)
                rec_file,meeting_external=rec.external_file_id,m.external_id
            else:
                rec_file=meeting_external=None
            if probe in {'upcoming','history','records','corp_records'}:
                await self.rt.policy.require(s,human,'meeting.sync.manage',connection_id=c.id)
            elif probe=='oauth_user_info' and (c.kind!='THIRD_PARTY_OAUTH' or c.member_id!=human.member_id):
                raise MeetingError('PERMISSION_DENIED',403)
            if probe=='corp_records' and c.kind!='ENTERPRISE_AKSK':
                raise MeetingError('UPSTREAM_CAPABILITY_UNAVAILABLE',409)
        result={'probe':probe,'status':'PASSED','observed_at':utcnow().isoformat(),'reason':None,'upstream_code':None,
                'operation':operation,'elapsed_ms':0,'proves_resource_access':probe!='configuration','resource_specific':probe in CONTENT_PROBES}
        try:
            if probe=='configuration':
                async with self.rt.db.session() as s:
                    creds=list((await s.execute(select(Credential).where(Credential.application_id==app.id,
                        Credential.active.is_(True),Credential.deleted_at.is_(None)))).scalars())
                    latest=await s.scalar(select(STSRequest).where(STSRequest.connection_id==c.id)
                        .order_by(STSRequest.created_at.desc()).limit(1))
                result.update({'application_type':app.application_type,'configured_purposes':sorted({x.purpose for x in creds}),
                    'webhook_verified':app.webhook_verified_at is not None,'last_callback_at':app.last_callback_at,
                    'sts_request_status':latest.status if latest else 'NOT_REQUESTED','proves_resource_access':False})
            elif probe=='oauth_user_info':
                token=await self.rt.connections.oauth_credentials(c.id)
                raw=await self.rt.tencent.oauth('user_info',{'access_token':token['access_token'],'open_id':c.external_id})
                result['identity_matches']=raw.get('open_id',c.external_id)==c.external_id
                if not result['identity_matches']:raise MeetingError('IDENTITY_CONFLICT',409)
            else:
                operator=await self.rt.connections.operator(c,member_id=human.member_id,
                    for_ingestion=c.kind=='ENTERPRISE_AKSK' and probe not in {'upcoming','history'})
                if probe=='upcoming':
                    raw=await self.rt.tencent.call(c.id,'upcoming',operator,query={'pos':0,'cursory':0})
                    if not isinstance(raw.get('meeting_info_list'),list):raise MeetingError('UPSTREAM_CONTRACT_ERROR',502)
                    result['returned_count']=len(raw['meeting_info_list'])
                elif probe=='history':
                    end=int(utcnow().timestamp());start=end-86400
                    raw=await self.rt.tencent.call(c.id,'history',operator,query={'start_time':start,'end_time':end,'page':1,'page_size':20})
                    rows=raw.get('meeting_info_list')
                    if not isinstance(rows,list):raise MeetingError('UPSTREAM_CONTRACT_ERROR',502)
                    result['returned_count']=len(rows)
                elif probe in {'records','corp_records'}:
                    end=int(utcnow().timestamp());start=end-86400
                    raw=await self.rt.tencent.call(c.id,probe,operator,query={'start_time':start,'end_time':end,'page':1,'page_size':20})
                    rows=raw.get('record_meetings')
                    if not isinstance(rows,list):raise MeetingError('UPSTREAM_CONTRACT_ERROR',502)
                    result['returned_count']=len(rows)
                elif probe=='record_detail':
                    raw=await self.rt.tencent.call(c.id,'record_detail',operator,file_id=rec_file)
                    result['media_hosts']=self._hosts(raw)
                    result['resource_specific']=True
                elif probe=='minutes':
                    raw=await self.rt.tencent.call(c.id,'minutes',operator,file_id=rec_file,
                        query={'llm':3,'minute_type':2,'text_type':2,'lang':'default'})
                    from app.integrations.tencent_meeting.mapper import normalize_minutes
                    result['content_present']=bool(normalize_minutes(raw)['minute'].strip())
                    result['resource_specific']=True
                else:
                    raw=await self.rt.tencent.call(c.id,'transcript',operator,file_id=rec_file,
                        query={'meeting_id':meeting_external,'pid':'0','limit':2})
                    rows=raw.get('minutes',{}).get('paragraphs')
                    if not isinstance(rows,list):raise MeetingError('UPSTREAM_CONTRACT_ERROR',502)
                    result['returned_count']=len(rows);result['resource_specific']=True
        except MeetingError as exc:
            waiting=exc.reason=='CONTENT_NOT_READY'
            result.update({'status':'WAITING' if waiting else 'FAILED','reason':exc.reason,
                           'upstream_code':exc.upstream_code if isinstance(exc,UpstreamError) else None})
        result['elapsed_ms']=int((time.monotonic()-started)*1000)
        result['chain']=self._chain(c,probe,result['status'])
        async with self.rt.db.transaction() as s:
            row=await s.get(type(c),c.id)
            row.capabilities={**(row.capabilities or {}),probe:{'status':result['status'],'observed_at':result['observed_at'],
                'reason':result['reason'],'upstream_code':result['upstream_code'],'resource_specific':result['resource_specific']}}
            row.last_verified_at=utcnow();row.last_reason=result['reason']
            record(s,human,'diagnostics.completed',resource_id=c.id,decision='ALLOW' if result['status']=='PASSED' else 'DENY',reason=result['reason'])
        return result

    def _hosts(self,raw):
        allowed={item.lower().rstrip('.') for item in self.rt.settings.media_allowed_hosts}
        found=[]
        seen=set()
        for key in ('download_address','audio_address'):
            self._add_host(raw.get(key),allowed,found,seen)
        for collection in ('meeting_summary','ai_topic_minutes','ai_ds_minutes'):
            entries=raw.get(collection) or []
            if isinstance(entries,list):
                for item in entries:
                    if isinstance(item,dict):self._add_host(item.get('download_address'),allowed,found,seen)
        return found

    @staticmethod
    def _add_host(address,allowed,found,seen):
        if not isinstance(address,str) or not address:return
        host=(urlsplit(address).hostname or '').lower().rstrip('.')
        if not host or host in seen:return
        seen.add(host)
        found.append({'host':host,'allowed':host in allowed})

    async def events(self,human,limit=50):
        async with self.rt.db.session() as s:
            await self.rt.admin.require(s,human,'meeting.diagnostics.run')
            rows=(await s.execute(select(EventInbox).where(EventInbox.org_id==human.org_id,EventInbox.deleted_at.is_(None))
                .order_by(EventInbox.created_at.desc()).limit(min(max(limit,1),100)))).scalars()
            return {'items':[{'id':r.id,'application_id':r.application_id,'event_type':r.event_type,'state':r.state,
                'created_at':r.created_at,'processed_at':r.processed_at,'last_reason':r.last_reason,'summary':r.safe_summary} for r in rows]}
