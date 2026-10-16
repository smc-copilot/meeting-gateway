"""The single permission decision path used by REST, MCP, workers and downloads."""
from dataclasses import dataclass
from datetime import datetime
from sqlalchemy import select, or_
from app.core.types import Principal, utcnow
from app.core.errors import MeetingError
from app.models import (AccessGrant, AgentGrant, Application, Connection, ResourceACL, ResourceOrigin,
                        Meeting, Asset, Participant, PolicyVersion, Client, OrganizationPolicy)

BUSINESS_ACTIONS = frozenset({"meeting.read", "meeting.content.read", "meeting.content.download",
                            "meeting.create.self", "meeting.create.on_behalf", "meeting.sync.manage"})
MANAGEMENT_ACTIONS = frozenset({"meeting.acl.manage", "meeting.application.manage", "meeting.client.manage",
                              "meeting.agent_grant.manage", "meeting.audit.read", "meeting.diagnostics.run", "meeting.sync.manage"})
ALL_ACTIONS = BUSINESS_ACTIONS | MANAGEMENT_ACTIONS


@dataclass(frozen=True)
class ResourceContext:
    org_id: str
    meeting_id: str
    connection_id: str
    host_member_id: str | None = None
    asset_id: str | None = None
    source_kind: str = "ENTERPRISE_AKSK"
    source_owner_id: str | None = None
    source_active: bool = False
    ingestion_active: bool = False
    participant_member_ids: tuple[str, ...] = ()
    user_origin_owner_ids: tuple[str, ...] = ()


def live(row, now=None) -> bool:
    return row is not None and getattr(row, "deleted_at", None) is None and getattr(row, "enabled", True) is not False and (
        getattr(row, "expires_at", None) is None or row.expires_at > (now or utcnow()))


def _scope(grant, principal: Principal, resource: ResourceContext | None, target_member_id=None, connection_id=None) -> bool:
    connections = getattr(grant, "connection_ids", []) or []
    chosen = resource.connection_id if resource else connection_id
    if connections and chosen not in connections:
        return False
    if target_member_id and target_member_id != principal.member_id:
        if target_member_id not in (getattr(grant, "target_member_ids", []) or []):
            return False
    scope = getattr(grant, "scope_type", "")
    if scope not in {"ORG_APPROVED", "SELF_CREATED", "EXPLICIT", "PARTICIPATED"}:
        return False
    if resource is None:
        return scope != "PARTICIPATED"
    if scope == "ORG_APPROVED":
        return True
    if scope == "SELF_CREATED":
        return principal.member_id is not None and resource.host_member_id == principal.member_id
    if scope == "PARTICIPATED":
        return principal.member_id in resource.participant_member_ids
    ids = getattr(grant, "resource_ids", []) or []
    return resource.meeting_id in ids or (resource.asset_id is not None and resource.asset_id in ids)


def _action_matches(grant, action, asset_type):
    types = getattr(grant, "asset_types", []) or []
    return action in (getattr(grant, "actions", []) or []) and (not types or asset_type is None or asset_type in types)


def evaluate(principal: Principal, grants, resource: ResourceContext | None, *, action: str,
             asset_type: str | None = None, agent=None, acls=(), target_member_id=None, connection_id=None) -> bool:
    if action not in principal.scopes:
        return False
    if resource is not None:
        if resource.org_id != principal.org_id or not resource.source_active:
            return False
        if resource.source_kind == "THIRD_PARTY_OAUTH":
            if principal.actor_type == "SERVICE" or resource.source_owner_id != principal.member_id:
                return False
        elif not resource.ingestion_active and (principal.actor_type == 'SERVICE' or principal.member_id not in resource.user_origin_owner_ids):
            return False
    relevant = [g for g in grants if live(g) and g.org_id == principal.org_id
                and g.subject_type == principal.subject_type and g.subject_id == principal.subject_id
                and getattr(g, "purpose", "ACCESS") != "INGESTION"
                and _action_matches(g, action, asset_type)
                and _scope(g, principal, resource, target_member_id, connection_id)]
    if any(g.effect == "DENY" for g in relevant) or not any(g.effect == "ALLOW" for g in relevant):
        return False
    if resource:
        for acl in acls:
            if (live(acl) and acl.org_id == principal.org_id and acl.subject_type == principal.subject_type
                and acl.subject_id == principal.subject_id and acl.resource_id in {resource.meeting_id, resource.asset_id}
                and acl.effect == "DENY" and _action_matches(acl, action, asset_type)):
                return False
    if principal.actor_type == "AGENT":
        if not live(agent) or agent.org_id != principal.org_id or not _action_matches(agent, action, asset_type):
            return False
        if not _scope(agent, principal, resource, target_member_id, connection_id):
            return False
    return True


class PermissionService:
    def __init__(self, runtime):
        self.runtime = runtime

    async def policy_version(self, session, org_id: str) -> int:
        row = await session.scalar(select(PolicyVersion).where(PolicyVersion.org_id == org_id, PolicyVersion.deleted_at.is_(None)))
        return row.counter if row else 0

    async def bump(self, session, org_id):
        row = await session.scalar(select(PolicyVersion).where(PolicyVersion.org_id == org_id, PolicyVersion.deleted_at.is_(None)).with_for_update())
        if row is None:
            row = PolicyVersion(org_id=org_id, counter=1); session.add(row)
        else:
            row.counter += 1
        await session.flush()
        return row.counter

    async def grants(self, session, principal):
        result = await session.execute(select(AccessGrant).where(AccessGrant.org_id == principal.org_id,
            AccessGrant.subject_type == principal.subject_type, AccessGrant.subject_id == principal.subject_id,
            AccessGrant.deleted_at.is_(None)))
        return list(result.scalars())

    async def context(self, session, meeting: Meeting, asset: Asset | None = None, asset_type: str | None = None) -> ResourceContext:
        connection = await session.get(Connection, meeting.connection_id)
        application = await session.get(Application, connection.application_id) if connection else None
        origins = list((await session.execute(select(ResourceOrigin).where(ResourceOrigin.org_id == meeting.org_id,
            ResourceOrigin.meeting_id == meeting.id, ResourceOrigin.deleted_at.is_(None),
            ResourceOrigin.asset_id == (asset.id if asset else None)))).scalars())
        if not origins and asset:
            origins = list((await session.execute(select(ResourceOrigin).where(ResourceOrigin.org_id == meeting.org_id,
                ResourceOrigin.meeting_id == meeting.id, ResourceOrigin.asset_id.is_(None), ResourceOrigin.deleted_at.is_(None)))).scalars())
        ingestion_active = False
        user_owners = set()
        origin_active = False
        for origin in origins:
            if not origin.enabled or origin.connection_id != meeting.connection_id:
                continue
            origin_active = True
            if origin.purpose == 'USER' and origin.owner_member_id:
                user_owners.add(origin.owner_member_id)
            if origin.purpose == "CREATED" and origin.owner_member_id == meeting.created_by_member_id:
                ingestion_active = True
            if origin.ingestion_grant_id:
                grant = await session.get(AccessGrant, origin.ingestion_grant_id)
                if (live(grant) and grant.org_id == meeting.org_id and grant.purpose == "INGESTION"
                    and grant.effect == "ALLOW" and meeting.connection_id in (grant.connection_ids or [])
                    and (not grant.asset_types or (asset.asset_type if asset else asset_type) is None
                         or (asset.asset_type if asset else asset_type) in grant.asset_types)):
                    # A later negative acquisition policy also invalidates previously cached sources.
                    negatives = list((await session.execute(select(AccessGrant).where(
                        AccessGrant.org_id == meeting.org_id, AccessGrant.subject_type == 'SERVICE',
                        AccessGrant.subject_id == grant.subject_id, AccessGrant.purpose == 'INGESTION',
                        AccessGrant.effect == 'DENY', AccessGrant.deleted_at.is_(None)))).scalars())
                    selected_type = asset.asset_type if asset else asset_type
                    denied = any(live(g) and 'meeting.sync.manage' in g.actions
                        and (not g.connection_ids or meeting.connection_id in g.connection_ids)
                        and (not g.asset_types or selected_type is None or selected_type in g.asset_types) for g in negatives)
                    source_client = await session.get(Client, grant.subject_id)
                    org_policy = await session.scalar(select(OrganizationPolicy).where(
                        OrganizationPolicy.org_id == meeting.org_id, OrganizationPolicy.deleted_at.is_(None)))
                    if not denied and live(source_client) and source_client.allow_service and org_policy and org_policy.retention_confirmed:
                        ingestion_active = True
        participants = tuple((await session.execute(select(Participant.member_id).where(Participant.meeting_id == meeting.id,
            Participant.org_id == meeting.org_id, Participant.verified.is_(True), Participant.deleted_at.is_(None)))).scalars())
        active = bool(connection and application and application.enabled and application.deleted_at is None
                      and connection.deleted_at is None and connection.status in {"ACTIVE", "DEGRADED"}
                      and connection.corporate_verified and origin_active)
        if asset and (asset.deleted_at is not None or asset.state in {"BLOCKED", "SOURCE_REMOVED"}):
            active = False
        return ResourceContext(meeting.org_id, meeting.id, meeting.connection_id, meeting.created_by_member_id,
            asset.id if asset else None, connection.kind if connection else "", connection.member_id if connection else None,
            active, ingestion_active, participants, tuple(user_owners))

    async def allowed(self, session, principal, action, *, meeting=None, asset=None, asset_type=None,
                      target_member_id=None, connection_id=None):
        grants = await self.grants(session, principal)
        context = await self.context(session, meeting, asset, asset_type) if meeting else None
        acls = []
        if context:
            acls = list((await session.execute(select(ResourceACL).where(ResourceACL.org_id == principal.org_id,
                ResourceACL.subject_type == principal.subject_type, ResourceACL.subject_id == principal.subject_id,
                ResourceACL.resource_id.in_([context.meeting_id] + ([context.asset_id] if context.asset_id else [])),
                ResourceACL.deleted_at.is_(None)))).scalars())
            # Explicit resource ACL ALLOW is meaningful only inside an action-grant's EXPLICIT envelope.
            # It never supplies missing action authority or overrides a denied origin.
            for g in grants:
                if g.scope_type == "EXPLICIT" and g.effect == "ALLOW":
                    allowed_ids = [a.resource_id for a in acls if live(a) and a.effect == "ALLOW" and _action_matches(a, action, asset_type)]
                    if allowed_ids:
                        from types import SimpleNamespace
                        clone = SimpleNamespace(**{col.name: getattr(g, col.name) for col in g.__table__.columns})
                        clone.resource_ids = list(set((g.resource_ids or []) + allowed_ids))
                        grants = [clone if value is g else value for value in grants]
        agent = await session.get(AgentGrant, principal.agent_grant_id) if principal.agent_grant_id else None
        return evaluate(principal, grants, context, action=action, asset_type=asset_type or (asset.asset_type if asset else None),
                        agent=agent, acls=acls, target_member_id=target_member_id, connection_id=connection_id)

    async def require(self, session, principal, action, **kwargs):
        if not await self.allowed(session, principal, action, **kwargs):
            raise MeetingError("RESOURCE_NOT_ACCESSIBLE" if kwargs.get("meeting") else "PERMISSION_DENIED",
                               404 if kwargs.get("meeting") else 403)

    async def action_ceiling(self, session, principal):
        grants = await self.grants(session, principal)
        allows, denies = set(), set()
        for grant in grants:
            if not live(grant) or grant.purpose == "INGESTION":
                continue
            if grant.effect == "ALLOW":
                allows.update(grant.actions)
            elif grant.scope_type == "ORG_APPROVED" and not grant.connection_ids and not grant.asset_types:
                denies.update(grant.actions)
        return (allows - denies) & set(principal.scopes)
