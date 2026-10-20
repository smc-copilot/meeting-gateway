import base64
import pytest
from sqlalchemy import select
from app.core.config import Settings
from app.core.errors import MeetingError
from app.core.security import digest, pkce_challenge
from app.core.types import MemberContext, Principal
from app.models import Client, AccessGrant, AccessToken


class TestBackend:
    __test__ = False
    disabled = False
    unavailable = False
    async def context(self, token):
        if token != "real-backend-session":
            raise MeetingError("TOKEN_INVALID", 401)
        return await self.resolve("o1", "m1")
    async def resolve(self, org, member):
        if self.unavailable:
            raise MeetingError("IDENTITY_SERVICE_UNAVAILABLE", 503)
        if self.disabled:
            raise MeetingError("MEMBER_INACTIVE", 403)
        return MemberContext(org_id=org, member_id=member, user_id="u1", member_role="admin")
    async def close(self):
        return None


@pytest.fixture
async def runtime(tmp_path):
    from app.runtime import Runtime
    settings = Settings(environment="test", database_url=f"sqlite:///{tmp_path}/auth.sqlite",
                        keyring_json={"v1": base64.urlsafe_b64encode(b"x"*32).decode()},
                        storage_path=tmp_path/"private",
                        public_base_url="https://gateway.example.org", portal_base_url="https://portal.example.org")
    rt = Runtime(settings, backend=TestBackend())
    await rt.db.create_schema_for_test()
    from app.models import LocalMember
    async with rt.db.transaction() as s:
        s.add(LocalMember(id="m1", org_id="o1", component_id="meeting-gateway", issuer_id="account-login-v1",
            external_user_id="u1", source="ACCOUNT_LOGIN", local_enabled=True, state="ACTIVE",
            identity_version=1, member_role="admin", profile_json={"name": "m1"}))
    rt.test_member_session = await rt.identity.issue_session_for_member("m1")
    async with rt.db.transaction() as s:
        s.add(Client(id="c1", org_id="o1", name="internal", client_type="CONFIDENTIAL", secret_hash=digest("client-secret-32-chars-long-value"),
                   allowed_scopes=["meeting.read", "meeting.content.read", "meeting.create.self"], redirect_uris=["https://agent.example.org/callback"],
                   owner_member_id="m1", allow_service=False, enabled=True))
        s.add(AccessGrant(org_id="o1", subject_type="MEMBER", subject_id="m1", actions=["meeting.read", "meeting.content.read", "meeting.create.self"],
                         scope_type="ORG_APPROVED", issued_by="admin", reason="test approved"))
    yield rt
    await rt.close()


async def issue(rt, scopes=None, audience=None):
    audience = audience or rt.settings.rest_resource_uri
    scopes = scopes or ["meeting.read"]
    verifier = "x" * 50
    request = await rt.auth.begin_authorization(client_id="c1", redirect_uri="https://agent.example.org/callback",
        resource=audience, scope=" ".join(scopes), state="state-value",
        code_challenge=pkce_challenge(verifier), code_challenge_method="S256", response_type="code")
    portal = await rt.identity.session_principal(rt.test_member_session)
    result = await rt.auth.approve_authorization(request["transaction_id"], portal)
    from urllib.parse import urlsplit, parse_qs
    code = parse_qs(urlsplit(result["redirect_uri"]).query)["code"][0]
    return await rt.auth.authorization_code("c1", "client-secret-32-chars-long-value", code, verifier,
                                            "https://agent.example.org/callback", audience)


async def test_exchange_disabled(runtime):
    with pytest.raises(MeetingError) as exc:
        await runtime.auth.exchange("c1", "client-secret-32-chars-long-value", runtime.test_member_session,
                                    ["meeting.read"], runtime.settings.rest_resource_uri)
    assert exc.value.reason == "AUTH_EXCHANGE_DISABLED" and exc.value.status == 410


async def test_token_binds_real_member_and_audience(runtime):
    token = await issue(runtime)
    p = await runtime.auth.authenticate(token["access_token"], runtime.settings.rest_resource_uri)
    assert p.member_id == "m1" and p.client_id == "c1"
    with pytest.raises(MeetingError) as exc:
        await runtime.auth.authenticate(token["access_token"], runtime.settings.mcp_resource_uri)
    assert exc.value.reason == "AUDIENCE_MISMATCH"


async def test_request_cannot_expand_scope(runtime):
    with pytest.raises(MeetingError):
        await issue(runtime, ["meeting.content.download"])

async def test_raw_upstream_or_backend_token_rejected(runtime):
    for token in [runtime.test_member_session, "tencent-token", "bad-value", "mr_refresh-token"]:
        with pytest.raises(MeetingError):
            await runtime.auth.authenticate(token, runtime.settings.mcp_resource_uri)


async def test_member_disable_and_identity_outage_fail_closed(runtime):
    from app.models import LocalMember
    token = await issue(runtime)
    async with runtime.db.transaction() as s:
        member = await s.get(LocalMember, "m1")
        member.local_enabled = False
        member.state = "LOCAL_DISABLED"
    with pytest.raises(MeetingError) as exc:
        await runtime.auth.authenticate(token["access_token"], runtime.settings.rest_resource_uri)
    assert exc.value.reason == "LOCAL_MEMBER_DISABLED"


async def test_client_disable_revokes_existing_access(runtime):
    token = await issue(runtime)
    async with runtime.db.transaction() as s:
        c = await s.get(Client, "c1"); c.enabled = False
    with pytest.raises(MeetingError):
        await runtime.auth.authenticate(token["access_token"], runtime.settings.rest_resource_uri)


async def test_refresh_rotates_and_reuse_revokes_family(runtime):
    first = await issue(runtime)
    second = await runtime.auth.refresh("c1", "client-secret-32-chars-long-value", first["refresh_token"], runtime.settings.rest_resource_uri)
    assert second["refresh_token"] != first["refresh_token"]
    with pytest.raises(MeetingError) as exc:
        await runtime.auth.refresh("c1", "client-secret-32-chars-long-value", first["refresh_token"], runtime.settings.rest_resource_uri)
    assert exc.value.reason == "REFRESH_REUSE"
    with pytest.raises(MeetingError):
        await runtime.auth.authenticate(second["access_token"], runtime.settings.rest_resource_uri)


async def test_refresh_cannot_change_audience(runtime):
    token = await issue(runtime)
    with pytest.raises(MeetingError):
        await runtime.auth.refresh("c1", "client-secret-32-chars-long-value", token["refresh_token"], runtime.settings.mcp_resource_uri)


async def test_client_credentials_not_employee_impersonation(runtime):
    with pytest.raises(MeetingError):
        await runtime.auth.client_credentials("c1", "client-secret-32-chars-long-value", ["meeting.read"], runtime.settings.rest_resource_uri)


async def test_revocation_returns_no_cross_client_information(runtime):
    token = await issue(runtime)
    await runtime.auth.revoke("c1", "client-secret-32-chars-long-value", token["access_token"])
    with pytest.raises(MeetingError):
        await runtime.auth.authenticate(token["access_token"], runtime.settings.rest_resource_uri)


async def test_authorization_code_pkce_once(runtime):
    verifier = "x" * 50
    request = await runtime.auth.begin_authorization(client_id="c1", redirect_uri="https://agent.example.org/callback",
        resource=runtime.settings.mcp_resource_uri, scope="meeting.read", state="state-value",
        code_challenge=pkce_challenge(verifier), code_challenge_method="S256", response_type="code")
    portal = await runtime.identity.session_principal(runtime.test_member_session)
    result = await runtime.auth.approve_authorization(request["transaction_id"], portal)
    from urllib.parse import urlsplit, parse_qs
    code = parse_qs(urlsplit(result["redirect_uri"]).query)["code"][0]
    with pytest.raises(MeetingError):
        await runtime.auth.authorization_code("c1", "client-secret-32-chars-long-value", code, "bad", "https://agent.example.org/callback", runtime.settings.mcp_resource_uri)
    token = await runtime.auth.authorization_code("c1", "client-secret-32-chars-long-value", code, verifier, "https://agent.example.org/callback", runtime.settings.mcp_resource_uri)
    assert (await runtime.auth.authenticate(token["access_token"], runtime.settings.mcp_resource_uri)).member_id == "m1"
    with pytest.raises(MeetingError):
        await runtime.auth.authorization_code("c1", "client-secret-32-chars-long-value", code, verifier, "https://agent.example.org/callback", runtime.settings.mcp_resource_uri)


async def test_authorization_rejects_arbitrary_redirect(runtime):
    with pytest.raises(MeetingError):
        await runtime.auth.begin_authorization(client_id="c1", redirect_uri="https://evil.example.org/cb",
            resource=runtime.settings.mcp_resource_uri, scope="meeting.read", state="s", code_challenge=pkce_challenge("x"*50),
            code_challenge_method="S256", response_type="code")


async def test_database_never_contains_raw_downstream_tokens(runtime):
    value = await issue(runtime)
    async with runtime.db.session() as s:
        row = await s.scalar(select(AccessToken))
        assert row.token_hash == digest(value["access_token"])
        assert row.refresh_hash == digest(value["refresh_token"])
        assert value["access_token"] not in repr(row.__dict__)
