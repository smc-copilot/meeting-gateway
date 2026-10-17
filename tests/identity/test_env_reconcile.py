import base64
from urllib.parse import parse_qs, urlsplit

import pytest
from pydantic import SecretStr
from sqlalchemy import select

from app.core.config import Settings
from app.core.errors import MeetingError
from app.models import Application, Connection, Credential


SDK = "33510141629"
AES = base64.b64encode(b"w" * 32).decode()


def production(**extra):
    values = {
        "environment": "production",
        "database_url": "postgresql+asyncpg://meeting:secret@db/meeting",
        "keyring_json": {"v1": base64.urlsafe_b64encode(b"k" * 32).decode()},
        "meeting_component_id": "meeting-gateway",
        "meeting_org_id": "org-1",
        "account_login_url": "https://login.example/api/v1/auth/account-login",
        "public_base_url": "https://copilot.example:9999",
        "portal_base_url": "https://portal.example",
        "allowed_hosts": ["copilot.example"],
        "tencent_meeting_corp_id": "210022394",
        "tencent_meeting_app_id": SDK,
        "tencent_meeting_app_secret": "secret-value",
        "tencent_meeting_webhook_name": "smc-copilot-webhook",
        "tencent_meeting_webhook_url": "https://copilot.example:9999/callbacks/tencent/events/" + SDK,
    }
    values.update(extra)
    return Settings(
        _env_file=None,
        TENCENT_MEETING_WEBHOOK_EncodingAESKey=values.pop("tencent_meeting_webhook_encoding_aes_key", AES),
        TENCENT_MEETING_WEBHOOK_Token=values.pop("tencent_meeting_webhook_token", "token-value"),
        **values,
    )


def test_webhook_aliases_and_production_url_rules():
    mixed = Settings(_env_file=None, environment="test", TENCENT_MEETING_WEBHOOK_EncodingAESKey="mixed-key",
                     TENCENT_MEETING_WEBHOOK_Token="mixed-token")
    canonical = Settings(_env_file=None, environment="test", TENCENT_MEETING_WEBHOOK_ENCODING_AES_KEY="upper-key",
                         TENCENT_MEETING_WEBHOOK_TOKEN="upper-token")
    assert mixed.tencent_meeting_webhook_encoding_aes_key.get_secret_value() == "mixed-key"
    assert canonical.tencent_meeting_webhook_token.get_secret_value() == "upper-token"
    ready = production()
    assert ready.fixed_oauth_callback_url().endswith("/callbacks/tencent/oauth/" + SDK)
    with pytest.raises(ValueError):
        production(tencent_meeting_app_id="")
    with pytest.raises(ValueError):
        production(tencent_meeting_webhook_encoding_aes_key=base64.b64encode(b"short").decode())
    with pytest.raises(ValueError):
        production(tencent_meeting_webhook_url="https://copilot.example:9999/callbacks/tencent/events/other")


def arm(rt, secret="oauth-secret-a", token="callback-token-test"):
    rt.settings.tencent_meeting_app_id = SDK
    rt.settings.tencent_meeting_corp_id = "210022394"
    rt.settings.tencent_meeting_app_secret = SecretStr(secret)
    rt.settings.tencent_meeting_webhook_name = "smc-copilot-webhook"
    rt.settings.tencent_meeting_webhook_token = SecretStr(token)
    rt.settings.tencent_meeting_webhook_encoding_aes_key = SecretStr(AES)
    rt.settings.tencent_meeting_allowed_open_corp_ids = ["open-corp"]
    rt.settings.tencent_meeting_webhook_url = rt.settings.fixed_webhook_callback_url()


async def load_app(rt):
    async with rt.db.transaction() as session:
        await rt.identity.ensure_deployment(session)
        return await session.scalar(select(Application).where(Application.org_id == "o1",
            Application.sdk_id == SDK, Application.deleted_at.is_(None)))


async def test_env_reconcile_rotates_secrets_and_keeps_ids(rt, human):
    arm(rt)
    first = await load_app(rt)
    async with rt.db.transaction() as session:
        row = await session.get(Application, first.id)
        row.webhook_verified_at = row.updated_at
        session.add(Connection(org_id="o1", application_id=first.id, kind="THIRD_PARTY_OAUTH",
            member_id="m1", external_id="open-kept", status="ACTIVE"))
    arm(rt, secret="oauth-secret-b", token="callback-token-next")
    second = await load_app(rt)
    assert second.id == first.id and second.receiver_id == first.receiver_id
    assert second.webhook_verified_at is None
    async with rt.db.session() as session:
        oauth = list((await session.execute(select(Credential).where(Credential.application_id == first.id,
            Credential.purpose == "OAUTH_APP").order_by(Credential.generation))).scalars())
        webhook = list((await session.execute(select(Credential).where(Credential.application_id == first.id,
            Credential.purpose == "WEBHOOK").order_by(Credential.generation))).scalars())
        kept = await session.scalar(select(Connection).where(Connection.application_id == first.id,
            Connection.deleted_at.is_(None)))
        current = await session.get(Application, first.id)
        _, secret = await rt.admin.read_secret(session, current, "OAUTH_APP")
    assert [row.generation for row in oauth] == [1, 2] and oauth[-1].active and not oauth[0].active
    assert webhook[-1].generation == 2 and kept.external_id == "open-kept"
    assert secret == {"secret": "oauth-secret-b"}


async def test_env_oauth_uses_fixed_redirect_and_rejects_replay(rt, human):
    arm(rt)
    app = await load_app(rt)
    started = await rt.connections.oauth_start(human, None)
    query = parse_qs(urlsplit(started["authorization_url"]).query)
    assert query["redirect_uri"][0] == rt.settings.fixed_oauth_callback_url()
    assert query["sdk_id"][0] == SDK
    state = query["state"][0]
    created = await rt.connections.oauth_callback(app.id, state, "one-time-code")
    assert created["connection_id"]
    with pytest.raises(MeetingError) as exc:
        await rt.connections.oauth_callback(app.id, state, "one-time-code")
    assert exc.value.reason == "STATE_INVALID"
