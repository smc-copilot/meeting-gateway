"""Client-authenticated Tencent OAuth bootstrap: start → callback → sessions → business token."""
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
from app.models import AccessGrant, Application, Client, Connection, LocalMember
from app.runtime import Runtime

SDK = "33510141629"
AES = base64.b64encode(b"w" * 32).decode()
SECRET = "client-secret-32-chars-long-value"
RETURN_TO = "https://app.example.org/meeting/callback"


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
        tencent_meeting_oauth_return_uris=[RETURN_TO],
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
        session.add(Client(
            id="c-boot", org_id="o1", name="internal-boot", client_type="CONFIDENTIAL",
            secret_hash=digest(SECRET), allowed_scopes=["meeting.read", "meeting.content.read"],
            redirect_uris=[], owner_member_id="system", allow_service=False, enabled=True,
        ))
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
            "client_id": "c-boot", "client_secret": SECRET, "subject_token": "ms_x",
            "scopes": ["meeting.read"], "resource": bootstrap_rt.settings.rest_resource_uri,
        })
        assert exchange.status_code == 410
        assert exchange.json()["reason"] == "AUTH_EXCHANGE_DISABLED"


async def test_client_oauth_bootstrap_issues_business_token(bootstrap_rt):
    async with bootstrap_rt.db.session() as session:
        client = await session.get(Client, "c-boot")
        client_snap = type("C", (), {
            "id": client.id, "org_id": client.org_id, "client_type": client.client_type,
            "enabled": True, "deleted_at": None, "agent_id": None,
        })()
    started = await bootstrap_rt.connections.oauth_start_for_client(client_snap, "", RETURN_TO, client_host="127.0.0.1")
    assert "authorization_url" in started
    query = parse_qs(urlsplit(started["authorization_url"]).query)
    state = query["state"][0]
    assert query["redirect_uri"][0].endswith("/callbacks/tencent/oauth/" + SDK)

    async with bootstrap_rt.db.session() as session:
        app = await session.scalar(select(Application).where(Application.sdk_id == SDK))
        app_id = app.id

    callback = await bootstrap_rt.connections.oauth_callback(app_id, state, "auth-code-once")
    assert callback["status"] == "ACTIVE"
    assert callback["authorization_code"].startswith("oc_")

    issued = await bootstrap_rt.auth.oauth_session("c-boot", SECRET, callback["authorization_code"])
    assert issued["access_token"].startswith("mt_")
    assert issued["connection_id"] == callback["connection_id"]
    assert issued["session_token"].startswith("ms_")

    principal = await bootstrap_rt.auth.authenticate(issued["access_token"], bootstrap_rt.settings.rest_resource_uri)
    assert principal.member_id == issued["member_id"]
    assert principal.client_id == "c-boot"

    async with bootstrap_rt.db.session() as session:
        member = await session.get(LocalMember, issued["member_id"])
        conn = await session.get(Connection, callback["connection_id"])
        grants = list((await session.execute(select(AccessGrant).where(
            AccessGrant.subject_id == issued["member_id"], AccessGrant.deleted_at.is_(None)))).scalars())
    assert member.source == "TENCENT_OAUTH"
    assert conn.status == "ACTIVE" and conn.corporate_verified
    assert grants and "meeting.read" in grants[0].actions

    with pytest.raises(MeetingError) as exc:
        await bootstrap_rt.auth.oauth_session("c-boot", SECRET, callback["authorization_code"])
    assert exc.value.reason == "STATE_INVALID"


async def test_oauth_start_requires_return_to_whitelist(bootstrap_rt):
    client_snap = type("C", (), {
        "id": "c-boot", "org_id": "o1", "client_type": "CONFIDENTIAL",
        "enabled": True, "deleted_at": None, "agent_id": None,
    })()
    with pytest.raises(MeetingError) as exc:
        await bootstrap_rt.connections.oauth_start_for_client(
            client_snap, "", "https://evil.example.org/cb", client_host="127.0.0.1")
    assert exc.value.reason == "INVALID_REQUEST"
