"""Human portal projections. They never accept an employee identity supplied in a tool argument."""
from sqlalchemy import select
from app.core.errors import MeetingError
from app.models import (Application,Connection,IdentityBinding,AgentGrant,AccessToken,Client,PolicyVersion,AccessGrant)
from app.services.admin_service import safe_row,FIELDS
from app.services.permission_service import live,BUSINESS_ACTIONS
from app.core.types import utcnow
from app.services.audit_service import record


class PortalService:
    def __init__(self,runtime):self.rt=runtime

    async def context(self,p):
        member=await self.rt.admin.human(p)
        async with self.rt.db.session() as s:
            actions=await self.rt.policy.action_ceiling(s,p)
            version=await self.rt.policy.policy_version(s,p.org_id)
            return {'member':member.model_dump(),'actions':sorted(actions),'policy_version':version,
                'can_bootstrap':not version and member.member_role=='admin',
                'features':{'meeting':self.rt.settings.meeting_enabled,'mcp':self.rt.settings.meeting_mcp_enabled,
                    'create':self.rt.settings.meeting_create_enabled,'corp_sync':self.rt.settings.meeting_corp_sync_enabled,
                    'media_download':self.rt.settings.meeting_media_download_enabled}}

    async def applications(self,p):
        await self.rt.admin.human(p)
        async with self.rt.db.session() as s:
            rows=(await s.execute(select(Application).where(Application.org_id==p.org_id,Application.enabled.is_(True),
                Application.application_type=='THIRD_PARTY_OAUTH',Application.deleted_at.is_(None)))).scalars()
            return {'items':[{'id':a.id,'name':a.name,'application_type':a.application_type} for a in rows]}

    async def connections(self,p):
        if p.portal:await self.rt.admin.human(p)
        else:p=await self.rt.auth.revalidate(p)
        async with self.rt.db.session() as s:
            rows=list((await s.execute(select(Connection).where(Connection.org_id==p.org_id,
                Connection.deleted_at.is_(None)))).scalars())
            result=[]
            for c in rows:
                app=await s.get(Application,c.application_id)
                if not app or not app.enabled or app.deleted_at:continue
                allowed=c.kind=='THIRD_PARTY_OAUTH' and c.member_id==p.member_id and p.actor_type!='SERVICE'
                if c.kind=='ENTERPRISE_AKSK':
                    allowed=any([await self.rt.policy.allowed(s,p,a,connection_id=c.id) for a in BUSINESS_ACTIONS])
                if allowed:
                    result.append({'id':c.id,'application_id':app.id,'name':app.name,'kind':c.kind,'status':c.status,
                        'owner_member_id':c.member_id,'last_synced_at':c.last_synced_at,'sync_coverage':c.sync_coverage,
                        'capabilities':c.capabilities if p.portal and c.member_id==p.member_id else {},
                        'last_reason':c.last_reason})
            return {'items':result}

    async def agents(self,p):
        await self.rt.admin.human(p)
        async with self.rt.db.session() as s:
            rows=(await s.execute(select(AgentGrant).where(AgentGrant.org_id==p.org_id,AgentGrant.member_id==p.member_id,
                AgentGrant.deleted_at.is_(None)).order_by(AgentGrant.created_at.desc()).limit(100))).scalars()
            return {'items':[safe_row(r,FIELDS['agent-grants'][2]) for r in rows]}

    async def agent_clients(self,p):
        await self.rt.admin.human(p)
        async with self.rt.db.session() as s:
            rows=(await s.execute(select(Client).where(Client.org_id==p.org_id,Client.enabled.is_(True),
                Client.agent_id.is_not(None),Client.deleted_at.is_(None)))).scalars()
            return {'items':[{'id':c.id,'name':c.name,'agent_id':c.agent_id,'allowed_scopes':c.allowed_scopes} for c in rows]}

    async def revoke_agent(self,p,ident,reason):
        await self.rt.admin.human(p)
        async with self.rt.db.lock('policy:'+p.org_id),self.rt.db.transaction() as s:
            row=await self.rt.admin._get(s,AgentGrant,p.org_id,ident)
            if row.member_id!=p.member_id:raise MeetingError('RESOURCE_NOT_ACCESSIBLE',404)
            row.enabled=False
            for t in (await s.execute(select(AccessToken).where(AccessToken.agent_grant_id==row.id))).scalars():t.revoked_at=utcnow()
            await self.rt.policy.bump(s,p.org_id);record(s,p,'agent_grant.revoked',resource_id=row.id)
            return {'id':row.id,'enabled':False}

    async def permissions(self,p):
        async with self.rt.db.session() as s:
            grants=[g for g in await self.rt.policy.grants(s,p) if live(g) and g.purpose!='INGESTION']
            actions=await self.rt.policy.action_ceiling(s,p)
            if p.actor_type=='AGENT':
                ag=await s.get(AgentGrant,p.agent_grant_id)
                actions=actions&set(ag.actions) if live(ag) else set()
            return {'actions':sorted(actions),'policy_version':await self.rt.policy.policy_version(s,p.org_id),
                'grant_summaries':[{'actions':g.actions,'effect':g.effect,'scope_type':g.scope_type,'resource_ids':g.resource_ids,
                    'connection_ids':g.connection_ids,'asset_types':g.asset_types,'expires_at':g.expires_at} for g in grants]}
