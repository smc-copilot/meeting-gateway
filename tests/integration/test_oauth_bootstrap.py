"""Public OAuth start → gateway complete issues mt_ → business continue_to."""
import base64
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import select

from app.core.config import Settings
from app.core.errors import MeetingError
from app.core.security import digest
from app.core.types import utcnow
from app.main import create_app
from app.models import AccessGrant, Application, Connection, LocalMember
from app.runtime import Runtime

SDK = "33510141629"
AES = base64.b64encode(b"w" * 32).decode()
CONTINUE_TO = "https://app.example.org/meeting/callback"


class FakeTencent:
    def __init__(self):
        self.calls = []
        self.response = {}
        self.error = None
    async def admit(self, connection_id, operation, *, heartbeat=None):
        return None
    async def call(self, connection_id, operation, operator, **kwargs):
        return {}
    async def oauth(self, operation, payload):
        self.calls.append(("oauth", operation, payload))
        if self.error:
            raise self.error
        value = self.response.get(operation)
        if value is not None:
            return value
        return {"open_id": "open-boot-1", "open_corp_id": "open-corp", "access_token": "upstream-access-private",
                "refresh_token": "upstream-refresh-private", "expires": int((utcnow() + timedelta(hours=6)).timestamp()),
                "scopes": ["VIEW_USER_INFO", "VIEW_VIDEO"]}


@pytest.fixture
async def bootstrap_rt(tmp_path):
    provider = FakeTencent()
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{tmp_path}/oauth-boot.sqlite",
        keyring_json={"v1": base64.urlsafe_b64encode(b"x" * 32).decode()},
        storage_path=tmp_path / "private",
        public_base_url="https://meeting.example.org",
        portal_base_url="https://portal.example.org",
        allowed_hosts=["testserver", "meeting.example.org"],
        identity_mode="tencent_oauth",
        meeting_org_id="o1",
        meeting_component_id="meeting-gateway",
        tencent_meeting_corp_id="210022394",
        tencent_meeting_app_id=SDK,
        tencent_meeting_app_secret=SecretStr("oauth-app-secret"),
        tencent_meeting_allowed_open_corp_ids=["open-corp"],
        tencent_meeting_webhook_name="hook",
        tencent_meeting_webhook_token=SecretStr("token-value"),
        tencent_meeting_webhook_encoding_aes_key=SecretStr(AES),
        tencent_meeting_webhook_url=f"https://meeting.example.org/callbacks/tencent/events/{SDK}",
        upstream_min_interval_seconds=0,
    )
    runtime = Runtime(settings, provider=provider)
    await runtime.db.create_schema_for_test()
    async with runtime.db.transaction() as session:
        await runtime.identity.ensure_deployment(session)
    yield runtime
    await runtime.close()


async def test_account_login_and_exchange_http_disabled(bootstrap_rt):
    app = create_app(runtime=bootstrap_rt)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://meeting.example.org") as client:
        login = await client.post("/api/v1/auth/account-login", json={"account": "a", "password": "b"})
        assert login.status_code == 410
        assert login.json()["reason"] == "ACCOUNT_LOGIN_DISABLED"
        exchange = await client.post("/api/v1/auth/exchange", json={
            "client_id": "c-boot", "client_secret": "x", "subject_token": "ms_x",
            "scopes": ["meeting.read"], "resource": bootstrap_rt.settings.rest_resource_uri,
        })
        assert exchange.status_code == 410
        assert exchange.json()["reason"] == "AUTH_EXCHANGE_DISABLED"


async def test_public_oauth_bootstrap_gateway_complete_issues_mt(bootstrap_rt):
    app = create_app(runtime=bootstrap_rt)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://meeting.example.org", follow_redirects=False) as http:
        started = await http.get("/api/v1/oauth/authorizations", params={
            "continue_to": CONTINUE_TO, "application_id": "",
        })
        assert started.status_code == 200, started.text
        data = started.json()["data"]
        assert "authorization_url" in data
        query = parse_qs(urlsplit(data["authorization_url"]).query)
        state = query["state"][0]
        assert query["redirect_uri"][0].endswith("/callbacks/tencent/oauth/" + SDK)

    async with bootstrap_rt.db.session() as session:
        row = await session.scalar(select(Application).where(Application.sdk_id == SDK))
        app_id = row.id

    callback = await bootstrap_rt.connections.oauth_callback(app_id, state, "auth-code-once")
    assert callback["status"] == "ACTIVE"
    assert callback["authorization_code"].startswith("oc_")
    assert callback["return_to"] == "https://meeting.example.org/oauth/tencent/complete"
    assert callback["continue_to"] == CONTINUE_TO

    async with AsyncClient(transport=transport, base_url="https://meeting.example.org", follow_redirects=False) as http:
        complete = await http.get("/oauth/tencent/complete", params={
            "connection_id": callback["connection_id"],
            "status": "ACTIVE",
            "authorization_code": callback["authorization_code"],
        })
        assert complete.status_code == 303
        location = complete.headers["location"]
        assert location.startswith(CONTINUE_TO)
        landed = parse_qs(urlsplit(location).query)
        assert landed["access_token"][0].startswith("mt_")
        assert landed["connection_id"][0] == callback["connection_id"]
        assert landed["session_token"][0].startswith("ms_")
        token = landed["access_token"][0]

    principal = await bootstrap_rt.auth.authenticate(token, bootstrap_rt.settings.rest_resource_uri)
    assert principal.member_id

    async with bootstrap_rt.db.session() as session:
        member = await session.get(LocalMember, principal.member_id)
        conn = await session.get(Connection, callback["connection_id"])
        grants = list((await session.execute(select(AccessGrant).where(
            AccessGrant.subject_id == principal.member_id, AccessGrant.deleted_at.is_(None)))).scalars())
    assert member.source == "TENCENT_OAUTH"
    assert conn.status == "ACTIVE" and conn.corporate_verified
    assert grants and "meeting.read" in grants[0].actions

    with pytest.raises(MeetingError) as exc:
        await bootstrap_rt.auth.oauth_session_gateway(callback["authorization_code"])
    assert exc.value.reason == "STATE_INVALID"


async def test_oauth_start_rejects_invalid_continue_to(bootstrap_rt):
    with pytest.raises(MeetingError) as exc:
        await bootstrap_rt.connections.oauth_start_public(
            "", "javascript:alert(1)", client_host="127.0.0.1")
    assert exc.value.reason == "INVALID_REQUEST"


async def test_oauth_authorizations_http_no_auth_header(bootstrap_rt):
    app = create_app(runtime=bootstrap_rt)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://meeting.example.org") as http:
        denied = await http.get("/api/v1/oauth/authorizations", params={
            "continue_to": "not-a-url",
        })
        assert denied.status_code == 422
        ok = await http.get("/api/v1/oauth/authorizations", params={"continue_to": CONTINUE_TO})
        assert ok.status_code == 200
        assert ok.json()["data"]["authorization_url"].startswith("https://meeting.tencent.com/")
        legacy = await http.get("/api/v1/oauth/authorizations", params={"return_to": CONTINUE_TO})
        assert legacy.status_code == 200
