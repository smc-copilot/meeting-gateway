"""Local identity projected from one account-login response. No upstream directory calls."""
import re
from datetime import timedelta
from sqlalchemy import select
from app.core.errors import MeetingError
from app.core.security import digest, random_token
from app.core.types import MemberContext, utcnow
from app.models import (IdentityDeployment, LocalMember, LoginObservation, IdentitySession, LegacyMemberMap,
                        AccessGrant, Application, new_id)
from app.services.permission_service import live

ISSUER = "account-login-v1"
ROLES = {"admin": "admin", "operator": "operator", "member": "member"}
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


class IdentityService:
    def __init__(self, runtime):
        self.rt = runtime
        self._attempts: dict[str, list] = {}

    def _limit(self, account: str):
        now = utcnow().timestamp()
        key = digest(account)
        recent = [item for item in self._attempts.get(key, []) if now - item < 60]
        if len(recent) >= 8:
            raise MeetingError("RATE_LIMITED", 429, retry_after=60)
        recent.append(now)
        self._attempts[key] = recent

    async def ensure_deployment(self, session):
        settings = self.rt.settings
        row = await session.scalar(select(IdentityDeployment).where(IdentityDeployment.deleted_at.is_(None)))
        digest_value = digest("|".join([settings.meeting_component_id, settings.meeting_org_id, settings.identity_mode]))
        if row is None:
            row = IdentityDeployment(component_id=settings.meeting_component_id, org_id=settings.meeting_org_id,
                issuer_id=ISSUER, namespace_version=1, auth_mode_epoch=1, applied_config_digest=digest_value)
            session.add(row)
            await session.flush()
            await self._project_tencent(session, row)
            return row
        if row.component_id != settings.meeting_component_id or row.org_id != settings.meeting_org_id or row.issuer_id != ISSUER:
            raise MeetingError("IDENTITY_NAMESPACE_MISMATCH", 409)
        return row

    async def _project_tencent(self, session, deployment):
        settings = self.rt.settings
        app_id = settings.tencent_meeting_app_id
        secret = settings.tencent_meeting_app_secret.get_secret_value()
        corp = settings.tencent_meeting_corp_id
        if not app_id or not secret or not corp:
            return
        environment = "production" if settings.environment == "production" else "test"
        existing = await session.scalar(select(Application).where(Application.org_id == deployment.org_id,
            Application.sdk_id == app_id, Application.deleted_at.is_(None)))
        if existing:
            existing.tencent_corp_id = corp
            existing.allowed_open_corp_ids = list(settings.tencent_meeting_allowed_open_corp_ids)
            data = dict(existing.settings_data or {})
            data.update({"owner": "ENV", "managed_key": "tencent-default",
                         "oauth_return_uris": list(settings.tencent_meeting_oauth_return_uris)})
            existing.settings_data = data
            return
        app = Application(org_id=deployment.org_id, name="ENV OAuth", application_type="THIRD_PARTY_OAUTH",
            environment=environment, tencent_corp_id=corp, sdk_id=app_id, data_scope="user", enabled=True,
            receiver_id=new_id(), allowed_open_corp_ids=list(settings.tencent_meeting_allowed_open_corp_ids),
            settings_data={"owner": "ENV", "managed_key": "tencent-default",
                           "oauth_return_uris": list(settings.tencent_meeting_oauth_return_uris)})
        session.add(app)
        await session.flush()
        await self.rt.admin.save_secret(session, app, "OAUTH_APP", {"secret": secret})

    async def require_member(self, org_id: str, member_id: str) -> MemberContext:
        async with self.rt.db.session() as session:
            await self.ensure_deployment(session)
            member = await self._load(session, org_id, member_id)
        return self._context(member)

    async def _load(self, session, org_id: str, member_id: str) -> LocalMember:
        member = await session.get(LocalMember, member_id)
        if member is None or member.deleted_at is not None or member.org_id != org_id:
            mapped = await session.scalar(select(LegacyMemberMap).where(LegacyMemberMap.org_id == org_id,
                LegacyMemberMap.legacy_member_id == member_id, LegacyMemberMap.deleted_at.is_(None)))
            member = await session.get(LocalMember, mapped.local_member_id) if mapped else None
        if member is None or member.deleted_at is not None or member.org_id != org_id:
            raise MeetingError("LOCAL_MEMBER_NOT_ENROLLED", 409)
        if member.state == "LOCAL_DISABLED" or not member.local_enabled:
            raise MeetingError("LOCAL_MEMBER_DISABLED", 403)
        if member.state != "ACTIVE":
            raise MeetingError("MEMBER_INACTIVE", 403)
        return member

    @staticmethod
    def _context(member: LocalMember) -> MemberContext:
        profile = member.profile_json or {}
        return MemberContext(org_id=member.org_id, user_id=member.external_user_id, member_id=member.id,
            name=profile.get("name") or "", member_role=member.member_role, is_active=True,
            must_change_password=False, is_super_admin=False)

    async def search(self, org_id: str, query: str):
        async with self.rt.db.session() as session:
            rows = list((await session.execute(select(LocalMember).where(LocalMember.org_id == org_id,
                LocalMember.deleted_at.is_(None), LocalMember.state == "ACTIVE"))).scalars())
        items = []
        for member in rows:
            profile = member.profile_json or {}
            text = " ".join([member.external_user_id, profile.get("name") or "", profile.get("username") or ""])
            if query and query not in text and query not in member.id:
                continue
            items.append({"member_id": member.id, "user_id": member.external_user_id,
                          "name": profile.get("name") or "", "member_role": member.member_role})
        return items[:30]

    async def login(self, account: str, password: str) -> dict:
        if not isinstance(account, str) or not isinstance(password, str):
            raise MeetingError("INVALID_REQUEST", 422)
        if not account.strip() or not 1 <= len(account) <= 200 or not 1 <= len(password) <= 200:
            raise MeetingError("INVALID_REQUEST", 422)
        self._limit(account)
        payload = await self.rt.accounts.login(account, password)
        user, expires_in, role, unrecognized = self._validate(payload)
        now = utcnow()
        deadline = now + timedelta(seconds=min(expires_in, self.rt.settings.auth_session_ttl_seconds))
        async with self.rt.db.transaction() as session:
            deployment = await self.ensure_deployment(session)
            if user["current_org_id"] != deployment.org_id:
                raise MeetingError("ACCOUNT_ORG_MISMATCH", 403)
            member = await session.scalar(select(LocalMember).where(LocalMember.component_id == deployment.component_id,
                LocalMember.org_id == deployment.org_id, LocalMember.issuer_id == ISSUER,
                LocalMember.external_user_id == user["id"], LocalMember.deleted_at.is_(None)))
            if member and (member.state == "LOCAL_DISABLED" or not member.local_enabled):
                raise MeetingError("LOCAL_MEMBER_DISABLED", 403)
            if member is None:
                member = LocalMember(org_id=deployment.org_id, component_id=deployment.component_id, issuer_id=ISSUER,
                    external_user_id=user["id"], source="ACCOUNT_LOGIN", local_enabled=True, state="ACTIVE",
                    identity_version=1, member_role=role, last_verified_at=now,
                    profile_json=self._profile(user, role, unrecognized))
                session.add(member)
                await session.flush()
            else:
                member.state = "ACTIVE"
                member.member_role = role
                member.last_verified_at = now
                member.profile_json = self._profile(user, role, unrecognized)
                member.identity_version += 1
            observation = LoginObservation(member_id=member.id, attempt_seq=member.last_applied_attempt_seq + 1,
                received_at=now, normalized_role=role, observed_flags={"role_unrecognized": unrecognized},
                accepted_for_session=True, source_expires_in=expires_in, valid_until=deadline,
                projection_digest=digest(user["id"] + role))
            session.add(observation)
            await session.flush()
            member.last_applied_attempt_seq = observation.attempt_seq
            token = random_token("ms")
            stored = IdentitySession(token_hash=digest(token), member_id=member.id, observation_id=observation.id,
                component_id=deployment.component_id, org_id=deployment.org_id, issued_at=now, expires_at=deadline,
                identity_version=member.identity_version, auth_mode_epoch=deployment.auth_mode_epoch)
            session.add(stored)
            await session.flush()
            return {"session_token": token, "token_type": "bearer",
                    "expires_in": max(1, int((deadline - now).total_seconds())),
                    "identity_mode": "account_login", "component_id": deployment.component_id,
                    "org_id": deployment.org_id,
                    "user": {"user_id": member.external_user_id, "member_id": member.id,
                             "name": (member.profile_json or {}).get("name") or "", "member_role": member.member_role},
                    "session_id": stored.id}

    def _validate(self, payload: dict):
        if not isinstance(payload, dict) or type(payload.get("code")) is not int or payload.get("code") != 0:
            if isinstance(payload, dict) and type(payload.get("code")) is int and payload.get("code") != 0:
                raise MeetingError("ACCOUNT_LOGIN_REJECTED", 401)
            raise MeetingError("ACCOUNT_LOGIN_CONTRACT_ERROR", 502)
        if payload.get("error_code") not in {None} or payload.get("message_key") not in {None}:
            if "error_code" in payload and payload.get("error_code") not in {None}:
                raise MeetingError("ACCOUNT_LOGIN_CONTRACT_ERROR", 502)
            if "message_key" in payload and payload.get("message_key") not in {None}:
                raise MeetingError("ACCOUNT_LOGIN_CONTRACT_ERROR", 502)
        data = payload.get("data")
        if not isinstance(data, dict):
            raise MeetingError("ACCOUNT_LOGIN_CONTRACT_ERROR", 502)
        expires_in = data.get("expires_in")
        if type(expires_in) is not int or not 1 <= expires_in <= 86400:
            raise MeetingError("ACCOUNT_LOGIN_CONTRACT_ERROR", 502)
        token_type = data.get("token_type")
        if not isinstance(token_type, str) or token_type.lower() != "bearer":
            raise MeetingError("ACCOUNT_LOGIN_CONTRACT_ERROR", 502)
        for name in ("access_token", "refresh_token"):
            value = data.get(name)
            if not isinstance(value, str) or not value or len(value) > 16384:
                raise MeetingError("ACCOUNT_LOGIN_CONTRACT_ERROR", 502)
        user = data.get("user")
        if not isinstance(user, dict):
            raise MeetingError("ACCOUNT_LOGIN_CONTRACT_ERROR", 502)
        user_id = str(user.get("id") or "").lower()
        org_id = str(user.get("current_org_id") or "").lower()
        if not UUID_RE.fullmatch(user_id) or not UUID_RE.fullmatch(org_id):
            raise MeetingError("ACCOUNT_LOGIN_CONTRACT_ERROR", 502)
        if user.get("is_active") is not True:
            raise MeetingError("MEMBER_INACTIVE", 403)
        if user.get("must_change_password") is not False:
            raise MeetingError("ACCOUNT_PASSWORD_CHANGE_REQUIRED", 403)
        if data.get("needs_org_setup") is not False:
            raise MeetingError("ACCOUNT_ORG_REQUIRED", 403)
        if org_id != self.rt.settings.meeting_org_id.lower():
            raise MeetingError("ACCOUNT_ORG_MISMATCH", 403)
        raw_role = user.get("portal_org_role")
        unrecognized = False
        if raw_role is None or raw_role == "":
            role, unrecognized = "member", True
        elif not isinstance(raw_role, str) or raw_role not in ROLES:
            if not isinstance(raw_role, str):
                raise MeetingError("ACCOUNT_LOGIN_CONTRACT_ERROR", 502)
            role, unrecognized = "member", True
        else:
            role = ROLES[raw_role]
        user = dict(user)
        user["id"] = user_id
        user["current_org_id"] = org_id
        return user, expires_in, role, unrecognized

    @staticmethod
    def _profile(user, role, unrecognized):
        def clip(name, limit):
            value = user.get(name)
            if value is None:
                return ""
            if not isinstance(value, str):
                return ""
            return value[:limit]
        return {"name": clip("name", 128), "username": clip("username", 200), "email": clip("email", 320),
                "portal_org_role": role, "role_unrecognized": unrecognized,
                "is_task_admin": user.get("is_task_admin") is True, "is_super_admin": False}

    async def session_principal(self, token: str, trace_id=""):
        if not token.startswith("ms_"):
            raise MeetingError("IDENTITY_REAUTH_REQUIRED", 401)
        async with self.rt.db.session() as session:
            deployment = await self.ensure_deployment(session)
            row = await session.scalar(select(IdentitySession).where(IdentitySession.token_hash == digest(token),
                IdentitySession.deleted_at.is_(None)))
            if row is None or row.revoked_at or row.expires_at <= utcnow():
                raise MeetingError("IDENTITY_REAUTH_REQUIRED", 401)
            if row.auth_mode_epoch != deployment.auth_mode_epoch:
                raise MeetingError("IDENTITY_MODE_CHANGED", 401)
            member = await self._load(session, row.org_id, row.member_id)
            if member.identity_version != row.identity_version:
                raise MeetingError("IDENTITY_REAUTH_REQUIRED", 401)
        from app.core.types import Principal
        from app.services.permission_service import ALL_ACTIONS
        return Principal(org_id=member.org_id, actor_type="MEMBER", client_id="portal", member_id=member.id,
            user_id=member.external_user_id, scopes=ALL_ACTIONS, portal=True, member_role=member.member_role,
            is_super_admin=False, trace_id=trace_id, session_issued_at=row.issued_at,
            identity_expires_at=row.expires_at, identity_session_id=row.id,
            identity_version=row.identity_version, auth_mode_epoch=row.auth_mode_epoch)

    async def logout(self, token: str):
        async with self.rt.db.transaction() as session:
            row = await session.scalar(select(IdentitySession).where(IdentitySession.token_hash == digest(token)))
            if row and not row.revoked_at:
                row.revoked_at = utcnow()
                from app.models import AccessToken
                from sqlalchemy import update
                await session.execute(update(AccessToken).where(AccessToken.identity_session_id == row.id)
                    .values(revoked_at=utcnow()))
        return {"revoked": True}

    async def issue_session_for_member(self, member_id: str) -> str:
        now = utcnow()
        token = random_token("ms")
        async with self.rt.db.transaction() as session:
            deployment = await self.ensure_deployment(session)
            member = await session.get(LocalMember, member_id)
            if member is None:
                raise MeetingError("LOCAL_MEMBER_NOT_ENROLLED", 409)
            observation = LoginObservation(member_id=member.id, attempt_seq=member.last_applied_attempt_seq + 1,
                received_at=now, normalized_role=member.member_role, observed_flags={}, accepted_for_session=True,
                source_expires_in=self.rt.settings.auth_session_ttl_seconds,
                valid_until=now + timedelta(seconds=self.rt.settings.auth_session_ttl_seconds),
                projection_digest=digest(member.id))
            session.add(observation)
            await session.flush()
            member.last_applied_attempt_seq = observation.attempt_seq
            session.add(IdentitySession(token_hash=digest(token), member_id=member.id, observation_id=observation.id,
                component_id=deployment.component_id, org_id=member.org_id, issued_at=now,
                expires_at=observation.valid_until, identity_version=member.identity_version,
                auth_mode_epoch=deployment.auth_mode_epoch))
        return token

    async def disable(self, principal, member_id: str, reason: str):
        async with self.rt.db.transaction() as session:
            await self.rt.admin.require(session, principal, "meeting.acl.manage")
            target = await self._load(session, principal.org_id, member_id)
            if await self._last_admin(session, principal.org_id, target.id):
                raise MeetingError("LAST_ADMIN_DISABLE_FORBIDDEN", 409)
            target.local_enabled = False
            target.state = "LOCAL_DISABLED"
            await session.execute(select(IdentitySession).where(IdentitySession.member_id == target.id))
            rows = list((await session.execute(select(IdentitySession).where(IdentitySession.member_id == target.id,
                IdentitySession.revoked_at.is_(None)))).scalars())
            for row in rows:
                row.revoked_at = utcnow()
        return {"member_id": member_id, "state": "LOCAL_DISABLED", "reason": reason}

    async def enable(self, principal, member_id: str, reason: str):
        async with self.rt.db.transaction() as session:
            await self.rt.admin.require(session, principal, "meeting.acl.manage")
            target = await session.get(LocalMember, member_id)
            if target is None or target.org_id != principal.org_id or target.deleted_at is not None:
                raise MeetingError("LOCAL_MEMBER_NOT_ENROLLED", 409)
            target.local_enabled = True
            target.state = "LEGACY_UNVERIFIED"
        return {"member_id": member_id, "state": "LEGACY_UNVERIFIED", "reason": reason}

    async def apply_legacy_map(self, rows: list[dict]):
        seen_legacy = set()
        seen_external = set()
        async with self.rt.db.transaction() as session:
            await self.ensure_deployment(session)
            for row in rows:
                legacy = row["legacy_member_id"]
                external = row["external_user_id"].lower()
                org_id = row["org_id"]
                key = (org_id, legacy)
                if key in seen_legacy or external in seen_external:
                    raise MeetingError("IDENTITY_MAPPING_CONFLICT", 409)
                seen_legacy.add(key)
                seen_external.add(external)
                member = await session.scalar(select(LocalMember).where(LocalMember.org_id == org_id,
                    LocalMember.external_user_id == external, LocalMember.deleted_at.is_(None)))
                if member is None:
                    member = LocalMember(org_id=org_id, component_id=self.rt.settings.meeting_component_id,
                        issuer_id=ISSUER, external_user_id=external, source="LEGACY_MAPPING", local_enabled=True,
                        state="LEGACY_UNVERIFIED", identity_version=1, member_role="member", profile_json={})
                    session.add(member)
                    await session.flush()
                session.add(LegacyMemberMap(org_id=org_id, legacy_member_id=legacy, local_member_id=member.id,
                    external_user_id=external, note="explicit map"))
            from app.models import Connection, Client, AccessGrant
            missing = []
            connections = list((await session.execute(select(Connection).where(Connection.deleted_at.is_(None)))).scalars())
            for connection in connections:
                if connection.member_id and not await self._known(session, connection.org_id, connection.member_id):
                    missing.append(connection.member_id)
            clients = list((await session.execute(select(Client).where(Client.deleted_at.is_(None)))).scalars())
            for client in clients:
                if client.owner_member_id and not await self._known(session, client.org_id, client.owner_member_id):
                    missing.append(client.owner_member_id)
            grants = list((await session.execute(select(AccessGrant).where(AccessGrant.deleted_at.is_(None),
                AccessGrant.subject_type == "MEMBER"))).scalars())
            for grant in grants:
                if not await self._known(session, grant.org_id, grant.subject_id):
                    missing.append(grant.subject_id)
            if missing:
                raise MeetingError("IDENTITY_MIGRATION_REQUIRED", 409)
        return {"mapped": len(rows)}

    async def _known(self, session, org_id: str, member_id: str) -> bool:
        member = await session.get(LocalMember, member_id)
        if member and member.org_id == org_id and member.deleted_at is None:
            return True
        mapped = await session.scalar(select(LegacyMemberMap).where(LegacyMemberMap.org_id == org_id,
            LegacyMemberMap.legacy_member_id == member_id, LegacyMemberMap.deleted_at.is_(None)))
        return mapped is not None

    async def _last_admin(self, session, org_id: str, member_id: str) -> bool:
        grants = list((await session.execute(select(AccessGrant).where(AccessGrant.org_id == org_id,
            AccessGrant.deleted_at.is_(None), AccessGrant.subject_type == "MEMBER"))).scalars())
        needed = {"meeting.acl.manage", "meeting.application.manage"}
        holders = set()
        for grant in grants:
            if not live(grant) or grant.effect != "ALLOW" or grant.purpose != "MANAGE":
                continue
            if needed <= set(grant.actions):
                member = await session.get(LocalMember, grant.subject_id)
                if member and member.state == "ACTIVE" and member.local_enabled and member.deleted_at is None:
                    holders.add(member.id)
        return member_id in holders and len(holders) == 1
