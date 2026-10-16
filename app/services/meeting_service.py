"""Local resource catalogue. Authorization precedes projection and pagination."""
from datetime import datetime
from sqlalchemy import select
from app.core.errors import MeetingError
from app.core.security import canonical,digest
from app.core.types import utcnow
from app.models import Meeting,Recording,Asset,ResourceOrigin,Participant,Connection
from app.integrations.tencent_meeting.mapper import seconds,milliseconds
from app.services.audit_service import record


class MeetingService:
    def __init__(self,runtime):self.rt=runtime

    def info(self,m):
        return {'id':m.id,'subject':m.subject,'meeting_code':m.meeting_code,'connection_ref':m.connection_id,
                'host_member_id':m.host_member_id,'created_by_member_id':m.created_by_member_id,'start_at':m.start_at,'end_at':m.end_at,'state':m.state,
                'synced_at':m.synced_at,'version':m.version}

    async def row(self,s,principal,meeting_id,action='meeting.read',**kwargs):
        row=await self.rt.admin._get(s,Meeting,principal.org_id,meeting_id)
        await self.rt.policy.require(s,principal,action,meeting=row,**kwargs)
        return row

    async def recording(self,s,principal,recording_id,action='meeting.read',asset_type=None):
        rec=await self.rt.admin._get(s,Recording,principal.org_id,recording_id)
        m=await self.row(s,principal,rec.meeting_id,action,asset_type=asset_type)
        return rec,m

    async def get(self,principal,meeting_id,*,fetch='cache'):
        if fetch not in {'cache','ensure'}:raise MeetingError('INVALID_REQUEST',422)
        if fetch=='ensure':
            job_id=await self.rt.queries.ensure_meeting(principal,meeting_id)
            if job_id:return {'accepted':True,'job_id':job_id}
        async with self.rt.db.transaction() as s:
            m=await self.row(s,principal,meeting_id)
            record(s,principal,'meeting.read',resource_id=m.id)
            return self.info(m)

    async def list(self,principal,*,limit=20,cursor=None,query='',connection_ref=None):
        if not 1<=limit<=100 or len(query)>200:raise MeetingError('INVALID_REQUEST',422)
        async with self.rt.db.transaction() as s:
            version=await self.rt.policy.policy_version(s,principal.org_id)
            binding=principal.binding+':meetings:'+str(version)+':'+digest(canonical([query,connection_ref]))
            state=self.rt.cursors.decode(cursor,binding=binding) if cursor else {'last':'','as_of':utcnow().isoformat()}
            last=state['last'];as_of=datetime.fromisoformat(state['as_of']);items=[];scanned=0;more=False
            while len(items)<limit+1 and scanned<10000:
                statement=select(Meeting).where(Meeting.org_id==principal.org_id,Meeting.deleted_at.is_(None),
                    Meeting.id>last,Meeting.created_at<=as_of)
                if query:statement=statement.where(Meeting.subject.contains(query,autoescape=True))
                if connection_ref:statement=statement.where(Meeting.connection_id==connection_ref)
                batch=list((await s.execute(statement.order_by(Meeting.id).limit(100))).scalars())
                if not batch:break
                for m in batch:
                    last=m.id;scanned+=1
                    if await self.rt.policy.allowed(s,principal,'meeting.read',meeting=m):
                        items.append(self.info(m))
                        if len(items)==limit+1:break
                if len(batch)<100:break
            if len(items)>limit:
                items=items[:limit];last=items[-1]['id'];more=True
            elif scanned>=10000:more=True
            coverage=[]
            for cid in {item['connection_ref'] for item in items}:
                conn=await s.get(Connection,cid)
                coverage.append({'connection_ref':cid,'last_synced_at':conn.last_synced_at,'sync_coverage':conn.sync_coverage})
            record(s,principal,'meeting.list')
            return {'items':items,'next_cursor':self.rt.cursors.encode({'last':last,'as_of':state['as_of']},binding=binding) if more else None,
                    'catalogue_as_of':as_of,'policy_version':version,'sync_coverage':coverage,'coverage_is_partial':True}

    async def recordings(self,principal,meeting_id):
        async with self.rt.db.transaction() as s:
            m=await self.row(s,principal,meeting_id)
            rows=(await s.execute(select(Recording).where(Recording.meeting_id==m.id,Recording.deleted_at.is_(None)).order_by(Recording.id))).scalars()
            items=[]
            for r in rows:
                assets=(await s.execute(select(Asset).where(Asset.recording_id==r.id,Asset.deleted_at.is_(None)).order_by(Asset.created_at.desc()))).scalars()
                # Metadata permission may see availability but never URLs, content, hashes or private storage keys.
                latest={}
                for a in assets:
                    if a.asset_type not in latest:latest[a.asset_type]={'id':a.id,'asset_type':a.asset_type,'state':a.state,'is_complete':a.is_complete}
                items.append({'id':r.id,'meeting_id':m.id,'recording_group_id':r.recording_group_id,'state':r.state,
                    'start_at':r.start_at,'end_at':r.end_at,'size_bytes':r.size_bytes,'assets':list(latest.values())})
            record(s,principal,'recording.list',resource_id=m.id)
            return {'items':items}

    async def upsert(self,s,connection,raw,*,purpose,owner_member_id=None,ingestion_grant_id=None,history=False,created_host=None):
        external=str(raw.get('meeting_id') or '')
        if not external or len(external)>128 or not isinstance(raw.get('subject',''),str):raise MeetingError('UPSTREAM_CONTRACT_ERROR',502)
        row=await s.scalar(select(Meeting).where(Meeting.org_id==connection.org_id,Meeting.external_namespace==connection.id,
            Meeting.external_id==external,Meeting.deleted_at.is_(None)))
        if row is None:
            row=Meeting(org_id=connection.org_id,connection_id=connection.id,external_namespace=connection.id,
                external_id=external,subject=raw.get('subject',''),state='UNKNOWN');s.add(row);await s.flush()
        row.subject=raw.get('subject',row.subject)[:512];row.meeting_code=str(raw.get('meeting_code') or row.meeting_code or '') or None
        row.start_at=seconds(raw.get('start_time')) or row.start_at or milliseconds(raw.get('media_start_time'))
        row.end_at=seconds(raw.get('end_time')) or row.end_at
        row.state='ENDED' if history else str(raw.get('status') or ('ENDED' if 'record_files' in raw else row.state))[:32]
        host=raw.get('host_user_id',raw.get('userid'))
        if not host and isinstance(raw.get('hosts'),list) and raw['hosts']:host=raw['hosts'][0].get('userid')
        row.host_member_id=created_host or await self.rt.connections.member_from_external(s,connection,host) or row.host_member_id
        if purpose == 'CREATED':
            # Creation is established by our confirmed write journal, never inferred from a host field.
            row.created_by_member_id = owner_member_id
        row.synced_at=utcnow();row.version+=1
        origin=await s.scalar(select(ResourceOrigin).where(ResourceOrigin.meeting_id==row.id,ResourceOrigin.asset_id.is_(None),
            ResourceOrigin.connection_id==connection.id,ResourceOrigin.purpose==purpose,
            ResourceOrigin.owner_member_id==owner_member_id,ResourceOrigin.ingestion_grant_id==ingestion_grant_id,
            ResourceOrigin.deleted_at.is_(None)))
        if not origin:
            origin=ResourceOrigin(org_id=connection.org_id,meeting_id=row.id,connection_id=connection.id,purpose=purpose,
                owner_member_id=owner_member_id,ingestion_grant_id=ingestion_grant_id,enabled=True);s.add(origin)
        origin.last_verified_at=utcnow()
        if history and owner_member_id:
            participant=await s.scalar(select(Participant).where(Participant.meeting_id==row.id,Participant.member_id==owner_member_id,
                Participant.deleted_at.is_(None)))
            if participant is None:s.add(Participant(org_id=row.org_id,meeting_id=row.id,member_id=owner_member_id,
                verified=True,source='HISTORY_MEMBERSHIP'))
        for file in raw.get('record_files',[]):
            if not isinstance(file,dict) or file.get('record_file_id') is None:raise MeetingError('UPSTREAM_CONTRACT_ERROR',502)
            external_file=str(file['record_file_id'])
            rec=await s.scalar(select(Recording).where(Recording.connection_id==connection.id,
                Recording.external_file_id==external_file,Recording.deleted_at.is_(None)))
            if rec and rec.meeting_id!=row.id:raise MeetingError('UPSTREAM_CONTRACT_ERROR',502)
            if rec is None:
                rec=Recording(org_id=row.org_id,meeting_id=row.id,connection_id=connection.id,external_file_id=external_file,
                    recording_group_id=str(raw.get('meeting_record_id') or row.external_id));s.add(rec);await s.flush()
            rec.external_record_id=str(raw.get('meeting_record_id') or '') or None
            rec.start_at=milliseconds(file.get('record_start_time'));rec.end_at=milliseconds(file.get('record_end_time'))
            rec.size_bytes=int(file['record_size']) if file.get('record_size') is not None else None
            rec.state={1:'RECORDING',2:'PROCESSING',3:'READY'}.get(raw.get('state'),'UNKNOWN');rec.synced_at=utcnow()
            for kind in ('video','audio'):
                key=digest(canonical([external_file,kind,file.get('record_size'),file.get('record_end_time')]))
                asset=await s.scalar(select(Asset).where(Asset.recording_id==rec.id,Asset.asset_type==kind,Asset.content_hash==key,Asset.deleted_at.is_(None)))
                if asset is None:
                    s.add(Asset(org_id=row.org_id,meeting_id=row.id,recording_id=rec.id,connection_id=connection.id,
                        asset_type=kind,content_hash=key,state='METADATA',is_complete=False,content_type='application/octet-stream',
                        details={'allow_download_observed':file.get('allow_download') is True}))
        await s.flush()
        return row
