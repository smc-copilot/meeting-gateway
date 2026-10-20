"""Downstream authorization. It does not store employee passwords or Backend JWT keys."""
import hmac
import re
from datetime import datetime, timedelta
from urllib.parse import urlencode, urlsplit, urlunsplit, parse_qsl
from sqlalchemy import select, update, or_
from app.core.errors import MeetingError
from app.core.security import digest, random_token, verify_pkce
from app.core.types import Principal, utcnow
from app.models import Client, AccessGrant, AgentGrant, AccessToken, AuthTransaction, LocalMember, Connection, new_id
from app.services.permission_service import ALL_ACTIONS, live
from app.services.audit_service import record


class AuthService:
    def __init__(self, runtime):
        self.rt = runtime

    def _audience(self, value: str):
        if value not in {self.rt.settings.rest_resource_uri, self.rt.settings.mcp_resource_uri}:
            raise MeetingError("AUDIENCE_MISMATCH", 401)

    async def _client(self, session, client_id: str, secret: str | None, *, allow_public=False):
        client = await session.get(Client, client_id)
        if not live(client):
            raise MeetingError("TOKEN_INVALID", 401)
        if client.client_type == "PUBLIC_MCP" and allow_public:
            if secret:
                raise MeetingError("TOKEN_INVALID", 401)
        elif client.client_type == "CONFIDENTIAL":
            if not secret or not hmac.compare_digest(client.secret_hash or "", digest(secret)):
                raise MeetingError("TOKEN_INVALID", 401)
        else:
            raise MeetingError("TOKEN_INVALID", 401)
        return client

    async def portal_principal(self, backend_token: str, trace_id="") -> Principal:
        if not backend_token or backend_token.startswith(("mt_", "mr_", "mc_")):
            raise MeetingError("TOKEN_INVALID", 401)
        return await self.rt.identity.session_principal(backend_token, trace_id)

    async def _principal(self, session, row, client, *, trace_id=""):
        identity_expires = getattr(row, "identity_expires_at", None)
        identity_session_id = getattr(row, "identity_session_id", None)
        identity_version = getattr(row, "identity_version", None)
        auth_mode_epoch = getattr(row, "auth_mode_epoch", None)
        member_role = "member"
        if row.actor_type != "SERVICE":
            member = await self.rt.identity.require_member(row.org_id, row.member_id)
            member_role = member.member_role
            if row.user_id and member.user_id != row.user_id:
                raise MeetingError("TOKEN_INVALID", 401)
            if identity_session_id:
                from app.models import IdentitySession
                stored = await session.get(IdentitySession, identity_session_id)
                if stored is None or stored.revoked_at or stored.expires_at <= utcnow():
                    raise MeetingError("IDENTITY_REAUTH_REQUIRED", 401)
                identity_expires = stored.expires_at
        elif not client.allow_service:
            raise MeetingError("TOKEN_INVALID", 401)
        if row.actor_type == "AGENT":
            grant = await session.get(AgentGrant, row.agent_grant_id)
            if not live(grant) or grant.member_id != row.member_id or grant.client_id != client.id or grant.agent_id != row.agent_id or grant.org_id != row.org_id:
                raise MeetingError("TOKEN_INVALID", 401)
        return Principal(org_id=row.org_id, actor_type=row.actor_type, member_id=row.member_id, user_id=row.user_id,
            client_id=client.id, agent_id=row.agent_id, agent_grant_id=row.agent_grant_id, token_id=getattr(row, "id", None),
            audience=row.audience, scopes=frozenset(row.scopes) & frozenset(client.allowed_scopes),
            policy_version=await self.rt.policy.policy_version(session, row.org_id), trace_id=trace_id,
            member_role=member_role, is_super_admin=False, identity_expires_at=identity_expires,
            identity_session_id=identity_session_id, identity_version=identity_version, auth_mode_epoch=auth_mode_epoch)

    async def authenticate(self, token: str, audience: str, *, trace_id="") -> Principal:
        self._audience(audience)
        if not token.startswith("mt_") or len(token) > 256:
            raise MeetingError("TOKEN_INVALID", 401)
        async with self.rt.db.session() as session:
            row = await session.scalar(select(AccessToken).where(AccessToken.token_hash == digest(token), AccessToken.deleted_at.is_(None)))
            if not row or row.revoked_at or row.expires_at <= utcnow():
                raise MeetingError("TOKEN_INVALID", 401)
            if row.audience != audience:
                raise MeetingError("AUDIENCE_MISMATCH", 401)
            client = await session.get(Client, row.client_id)
            if not live(client) or client.org_id != row.org_id:
                raise MeetingError("TOKEN_INVALID", 401)
            principal = await self._principal(session, row, client, trace_id=trace_id)
            return principal

    async def revalidate(self, principal: Principal) -> Principal:
        """Revalidate persistent authorization, including token revocation. A queued action is not an HTTP token refresh."""
        if principal.portal:
            member = await self.rt.identity.require_member(principal.org_id, principal.member_id)
            return principal.model_copy(update={"member_role": member.member_role, "is_super_admin": False})
        async with self.rt.db.session() as session:
            client = await session.get(Client, principal.client_id)
            if not live(client) or client.org_id != principal.org_id:
                raise MeetingError("TOKEN_INVALID", 401)
            if principal.token_id:
                token = await session.get(AccessToken, principal.token_id)
                if token is None or token.revoked_at or token.deleted_at:
                    raise MeetingError("TOKEN_INVALID", 401)
            from types import SimpleNamespace
            row = SimpleNamespace(**principal.model_dump(exclude={"binding", "subject_id", "subject_type"}), id=principal.token_id)
            return await self._principal(session, row, client, trace_id=principal.trace_id)

    async def _effective(self, session, principal, requested):
        desired = set(requested)
        allowed = await self.rt.policy.action_ceiling(session, principal)
        if principal.actor_type == "AGENT":
            grant = await session.get(AgentGrant, principal.agent_grant_id)
            if not live(grant):
                raise MeetingError("TOKEN_INVALID", 401)
            allowed &= set(grant.actions)
        if not desired or not desired <= allowed:
            raise MeetingError("PERMISSION_DENIED", 403)
        return sorted(desired)

    async def _issue(self, session, client, principal, scopes, audience, *, family_id=None, refresh_deadline=None, refresh=True):
        self._audience(audience)
        if client.org_id != principal.org_id or not live(client):
            raise MeetingError("PERMISSION_DENIED", 403)
        principal = principal.model_copy(update={"scopes": frozenset(scopes) & frozenset(client.allowed_scopes)})
        if set(scopes) - set(client.allowed_scopes):
            raise MeetingError("PERMISSION_DENIED", 403)
        effective = await self._effective(session, principal, scopes)
        now = utcnow()
        limit = refresh_deadline or now + timedelta(seconds=self.rt.settings.refresh_token_seconds)
        if principal.agent_grant_id:
            agent = await session.get(AgentGrant, principal.agent_grant_id)
            if not live(agent) or agent.org_id != principal.org_id or agent.client_id != client.id or agent.member_id != principal.member_id:
                raise MeetingError("PERMISSION_DENIED", 403)
            limit = min(limit, agent.expires_at)
        if principal.actor_type != "SERVICE":
            if not principal.identity_expires_at:
                raise MeetingError("IDENTITY_REAUTH_REQUIRED", 401)
            limit = min(limit, principal.identity_expires_at)
        if limit <= now:
            raise MeetingError("TOKEN_INVALID", 401)
        token, refresh_token = random_token("mt"), random_token("mr") if refresh else None
        expires = min(now + timedelta(seconds=self.rt.settings.access_token_seconds), limit)
        row = AccessToken(org_id=principal.org_id, token_hash=digest(token), refresh_hash=digest(refresh_token) if refresh_token else None,
            family_id=family_id or new_id(), client_id=client.id, actor_type=principal.actor_type, member_id=principal.member_id,
            user_id=principal.user_id, agent_id=principal.agent_id, agent_grant_id=principal.agent_grant_id, audience=audience,
            scopes=effective, expires_at=expires, refresh_expires_at=limit if refresh_token else None,
            identity_session_id=principal.identity_session_id, identity_version=principal.identity_version,
            auth_mode_epoch=principal.auth_mode_epoch)
        session.add(row)
        record(session, principal, "auth.token.issued", resource_id=row.id)
        return {"access_token": token, "token_type": "Bearer", "expires_in": max(1, int((expires-now).total_seconds())),
                "refresh_token": refresh_token, "scope": " ".join(effective), "resource": audience}

    async def exchange(self, client_id, secret, subject_token, scopes, audience):
        raise MeetingError("AUTH_EXCHANGE_DISABLED", 410)

    async def oauth_session(self, client_id, secret, authorization_code, scopes=None):
        audience = self.rt.settings.rest_resource_uri
        if not authorization_code or not str(authorization_code).startswith("oc_") or len(authorization_code) > 256:
            raise MeetingError("STATE_INVALID", 400)
        async with self.rt.db.lock("oauth-session:" + digest(authorization_code)):
            async with self.rt.db.transaction() as session:
                client = await self._client(session, client_id, secret)
                if client.agent_id:
                    raise MeetingError("PERMISSION_DENIED", 403)
                rows = list((await session.execute(select(AuthTransaction).where(
                    AuthTransaction.purpose == "TENCENT_OAUTH", AuthTransaction.status == "RECEIVED",
                    AuthTransaction.org_id == client.org_id))).scalars())
                tx = None
                for row in rows:
                    payload = row.payload or {}
                    if payload.get("authorization_code_hash") != digest(authorization_code):
                        continue
                    bound = payload.get("client_id") or row.client_id
                    if bound and bound != client.id:
                        continue
                    tx = row
                    break
                if tx is None:
                    raise MeetingError("STATE_INVALID", 400)
                payload = dict(tx.payload or {})
                if payload.get("authorization_code_used_at"):
                    raise MeetingError("STATE_INVALID", 400)
                expires_raw = payload.get("authorization_code_expires_at")
                try:
                    expires_at = datetime.fromisoformat(expires_raw) if isinstance(expires_raw, str) else None
                except ValueError:
                    expires_at = None
                if expires_at is None or expires_at <= utcnow():
                    raise MeetingError("STATE_INVALID", 400)
                member_id = payload.get("member_id") or tx.member_id
                connection_id = payload.get("connection_id")
                if not member_id or not connection_id:
                    raise MeetingError("STATE_INVALID", 400)
                member = await self.rt.identity.require_member(client.org_id, member_id)
                connection = await session.get(Connection, connection_id)
                if connection is None or connection.member_id != member_id or connection.status != "ACTIVE":
                    raise MeetingError("UPSTREAM_REAUTH_REQUIRED", 409)
                local = await session.get(LocalMember, member_id)
                if local is None:
                    raise MeetingError("LOCAL_MEMBER_NOT_ENROLLED", 409)
                ms_token, stored = await self.rt.identity.attach_session_for_member(session, local)
                holder = Principal(org_id=client.org_id, actor_type="MEMBER", client_id=client.id, member_id=member_id,
                    user_id=member.user_id, scopes=ALL_ACTIONS, audience=audience, portal=False,
                    member_role=member.member_role, identity_expires_at=stored.expires_at,
                    identity_session_id=stored.id, identity_version=stored.identity_version,
                    auth_mode_epoch=stored.auth_mode_epoch)
                ceiling = await self.rt.policy.action_ceiling(session, holder)
                desired = scopes or sorted(ceiling or {"meeting.read", "meeting.content.read"})
                if not desired:
                    desired = ["meeting.read", "meeting.content.read"]
                issued = await self._issue(session, client, holder, desired, audience)
                payload["authorization_code_used_at"] = utcnow().isoformat()
                tx.payload = payload
                issued["connection_id"] = connection_id
                issued["member_id"] = member_id
                issued["session_token"] = ms_token
                issued["session_expires_in"] = max(1, int((stored.expires_at - utcnow()).total_seconds()))
                return issued

    async def portal_exchange(self, principal):
        if not principal.portal:
            raise MeetingError("PERMISSION_DENIED", 403)
        async with self.rt.db.transaction() as session:
            client = await session.scalar(select(Client).where(Client.org_id == principal.org_id, Client.client_type == "PORTAL", Client.deleted_at.is_(None)))
            if not live(client):
                raise MeetingError("PERMISSION_DENIED", 403)
            scopes = await self.rt.policy.action_ceiling(session, principal)
            # A user with only management permissions needs no business token.
            if not scopes:
                raise MeetingError("PERMISSION_DENIED", 403)
            return await self._issue(session, client, principal.model_copy(update={"client_id": client.id, "portal": False}),
                                     scopes, self.rt.settings.rest_resource_uri, refresh=False)

    async def client_credentials(self, client_id, secret, scopes, audience):
        async with self.rt.db.transaction() as session:
            client = await self._client(session, client_id, secret)
            if not client.allow_service or client.agent_id:
                raise MeetingError("PERMISSION_DENIED", 403)
            principal = Principal(org_id=client.org_id, actor_type="SERVICE", client_id=client.id, scopes=ALL_ACTIONS, audience=audience)
            return await self._issue(session, client, principal, scopes, audience, refresh=False)

    async def refresh(self, client_id, secret, refresh_token, audience):
        self._audience(audience)
        async with self.rt.db.lock("refresh:" + digest(refresh_token)):
            async with self.rt.db.transaction() as session:
                client = await self._client(session, client_id, secret, allow_public=True)
                row = await session.scalar(select(AccessToken).where(AccessToken.refresh_hash == digest(refresh_token)).with_for_update())
                if not row or row.client_id != client.id or row.audience != audience:
                    raise MeetingError("TOKEN_INVALID", 401)
                if row.refresh_used_at:
                    await session.execute(update(AccessToken).where(AccessToken.family_id == row.family_id).values(revoked_at=utcnow()))
                    await session.commit()  # Commit revocation even though the HTTP response is an error.
                    raise MeetingError("REFRESH_REUSE", 401)
                if row.revoked_at or not row.refresh_expires_at or row.refresh_expires_at <= utcnow():
                    raise MeetingError("TOKEN_INVALID", 401)
                principal = await self._principal(session, row, client)
                scopes = set(row.scopes) & await self.rt.policy.action_ceiling(session, principal)
                if principal.agent_grant_id:
                    agent = await session.get(AgentGrant, principal.agent_grant_id); scopes &= set(agent.actions)
                if not scopes:
                    raise MeetingError("PERMISSION_DENIED", 403)
                value = await self._issue(session, client, principal, scopes, audience,
                    family_id=row.family_id, refresh_deadline=row.refresh_expires_at)
                row.refresh_used_at = utcnow(); row.revoked_at = utcnow()
                return value

    async def revoke(self, client_id, secret, token):
        async with self.rt.db.transaction() as session:
            client = await self._client(session, client_id, secret, allow_public=True)
            row = await session.scalar(select(AccessToken).where(AccessToken.client_id == client.id,
                or_(AccessToken.token_hash == digest(token), AccessToken.refresh_hash == digest(token))))
            if row:
                await session.execute(update(AccessToken).where(AccessToken.family_id == row.family_id).values(revoked_at=utcnow()))

    async def begin_authorization(self, *, client_id, redirect_uri, resource, scope, state, code_challenge,
                                  code_challenge_method, response_type):
        self._audience(resource)
        if response_type != "code" or code_challenge_method != "S256" or not re.fullmatch(r"[A-Za-z0-9_-]{43}", code_challenge):
            raise MeetingError("INVALID_REQUEST", 400)
        if not state or len(state) > 512:
            raise MeetingError("INVALID_REQUEST", 400)
        async with self.rt.db.transaction() as session:
            client = await session.get(Client, client_id)
            scopes = sorted(set(scope.split()))
            if not live(client) or client.client_type == "PORTAL" or redirect_uri not in client.redirect_uris or not scopes or not set(scopes) <= set(client.allowed_scopes):
                raise MeetingError("INVALID_REQUEST", 400)
            row = AuthTransaction(org_id=client.org_id, purpose="DOWNSTREAM_REQUEST", client_id=client.id,
                expires_at=utcnow()+timedelta(minutes=5), payload={"redirect_uri": redirect_uri, "state": state,
                "resource": resource, "scopes": scopes, "code_challenge": code_challenge})
            session.add(row)
            return {"transaction_id": row.id, "consent_uri": self.rt.settings.portal_base_url + "/meeting/authorize?" + urlencode({"transaction_id": row.id})}

    async def authorization_details(self, transaction_id, principal):
        async with self.rt.db.session() as session:
            row = await session.get(AuthTransaction, transaction_id)
            if not principal.portal or not row or row.org_id != principal.org_id or row.purpose != "DOWNSTREAM_REQUEST" or row.expires_at <= utcnow():
                raise MeetingError("STATE_INVALID", 400)
            client = await session.get(Client, row.client_id)
            return {"id": row.id, "client_name": client.name, "client_id": client.id, "agent_id": client.agent_id,
                    "scopes": row.payload["scopes"], "resource": row.payload["resource"], "expires_at": row.expires_at}

    async def approve_authorization(self, transaction_id, principal, agent_grant_id=None):
        if not principal.portal or principal.actor_type != "MEMBER":
            raise MeetingError("PERMISSION_DENIED", 403)
        await self.rt.identity.require_member(principal.org_id, principal.member_id)
        async with self.rt.db.lock("consent:"+transaction_id):
            async with self.rt.db.transaction() as session:
                row = await session.get(AuthTransaction, transaction_id)
                if not row or row.org_id != principal.org_id or row.purpose != "DOWNSTREAM_REQUEST" or row.status != "PENDING" or row.expires_at <= utcnow():
                    raise MeetingError("STATE_INVALID", 400)
                client = await session.get(Client, row.client_id)
                if not live(client):
                    raise MeetingError("STATE_INVALID", 400)
                actor = principal.model_copy(update={"portal": False, "client_id": client.id})
                if client.agent_id:
                    grant = await session.get(AgentGrant, agent_grant_id) if agent_grant_id else None
                    if not live(grant) or grant.member_id != principal.member_id or grant.client_id != client.id or grant.agent_id != client.agent_id or grant.org_id != principal.org_id:
                        raise MeetingError("PERMISSION_DENIED", 403)
                    actor = actor.model_copy(update={"actor_type": "AGENT", "agent_id": client.agent_id, "agent_grant_id": grant.id})
                elif agent_grant_id:
                    raise MeetingError("INVALID_REQUEST", 400)
                await self._effective(session, actor, row.payload["scopes"])
                code = random_token("mc")
                row.secret_hash = digest(code); row.member_id = principal.member_id
                row.purpose = "DOWNSTREAM_CODE"; row.status = "ISSUED"
                row.expires_at = utcnow()+timedelta(seconds=self.rt.settings.auth_code_seconds)
                row.payload = row.payload | {"principal": actor.model_dump(mode="json")}
                parts = urlsplit(row.payload["redirect_uri"])
                query = parse_qsl(parts.query, keep_blank_values=True) + [("code", code), ("state", row.payload["state"])]
                destination = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))
                record(session, principal, "auth.consent.approved", resource_id=row.id)
                return {"redirect_uri": destination}

    async def authorization_code(self, client_id, secret, code, verifier, redirect_uri, audience):
        self._audience(audience)
        async with self.rt.db.lock("code:"+digest(code)):
            async with self.rt.db.transaction() as session:
                client = await self._client(session, client_id, secret, allow_public=True)
                row = await session.scalar(select(AuthTransaction).where(AuthTransaction.secret_hash == digest(code)))
                if not row or row.purpose != "DOWNSTREAM_CODE" or row.status != "ISSUED" or row.used_at or row.expires_at <= utcnow() or row.client_id != client.id:
                    raise MeetingError("STATE_INVALID", 400)
                if redirect_uri != row.payload["redirect_uri"] or redirect_uri not in client.redirect_uris or audience != row.payload["resource"] or not verify_pkce(verifier, row.payload["code_challenge"]):
                    raise MeetingError("STATE_INVALID", 400)
                principal = Principal.model_validate(row.payload["principal"])
                await self.rt.identity.require_member(principal.org_id, principal.member_id)
                result = await self._issue(session, client, principal, row.payload["scopes"], audience)
                row.used_at = utcnow(); row.status = "CONSUMED"
                return result
