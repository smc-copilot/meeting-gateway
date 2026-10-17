import json
import pytest
from app.core.config import Settings
from app.core.errors import MeetingError
from app.runtime import Runtime


ORG = "2be7c618-326d-4a73-91ea-1cfda10f7073"
USER = "55576b5f-5be6-4a20-aca8-5b5526adf18a"


class Response:
    def __init__(self, status, payload):
        self.status_code = status
        self.content = json.dumps(payload).encode()


class Http:
    def __init__(self, status=200, payload=None):
        self.status = status
        self.payload = payload or {}
        self.urls = []
    async def post(self, url, json=None):
        self.urls.append(url)
        assert "password" not in json or json["password"]
        return Response(self.status, self.payload)
    async def aclose(self):
        return None


def settings(tmp_path):
    import base64
    return Settings(environment="test", database_url=f"sqlite:///{tmp_path}/id.sqlite",
        keyring_json={"v1": base64.urlsafe_b64encode(b"x"*32).decode()},
        storage_path=tmp_path/"private", public_base_url="https://meeting.example.org",
        portal_base_url="https://portal.example.org", meeting_org_id=ORG,
        meeting_component_id="meeting-gateway", meeting_bootstrap_admin_user_ids=[USER],
        account_login_url="http://127.0.0.1:9/api/v1/auth/account-login",
        account_login_allow_private_http=True)


def payload(**overrides):
    user = {"id": USER, "current_org_id": ORG, "is_active": True, "must_change_password": False,
            "portal_org_role": "admin", "role": "user", "is_task_admin": True, "name": "Ada"}
    user.update(overrides.pop("user", {}))
    data = {"expires_in": 900, "token_type": "bearer", "access_token": "upstream-access",
            "refresh_token": "upstream-refresh", "needs_org_setup": False, "user": user}
    data.update(overrides)
    return {"code": 0, "error_code": None, "message_key": None, "data": data}


async def test_login_drops_upstream_tokens_and_keeps_role(tmp_path):
    http = Http(payload=payload())
    rt = Runtime(settings(tmp_path))
    rt.accounts.http = http
    await rt.db.create_schema_for_test()
    try:
        result = await rt.identity.login("ada", "secret-value")
        assert result["user"]["member_role"] == "admin"
        assert result["user"]["user_id"] == USER
        assert "upstream-access" not in json.dumps(result)
        assert result["session_token"].startswith("ms_")
        with pytest.raises(MeetingError) as exc:
            await rt.auth.authenticate(result["session_token"], rt.settings.rest_resource_uri)
        assert exc.value.reason == "TOKEN_INVALID"
        rt.accounts.assert_target("http://127.0.0.1:9/api/v1/auth/meeting-context")
    except MeetingError as exc:
        assert exc.reason == "IDENTITY_EGRESS_FORBIDDEN"
    finally:
        await rt.close()


async def test_login_rejects_inactive_and_wrong_org(tmp_path):
    rt = Runtime(settings(tmp_path))
    await rt.db.create_schema_for_test()
    try:
        rt.accounts.http = Http(payload=payload(user={"is_active": False}))
        with pytest.raises(MeetingError) as exc:
            await rt.identity.login("ada", "secret-value")
        assert exc.value.reason == "MEMBER_INACTIVE"
        rt.accounts.http = Http(payload=payload(user={"current_org_id": "11111111-1111-1111-1111-111111111111"}))
        with pytest.raises(MeetingError) as exc:
            await rt.identity.login("ada", "secret-value")
        assert exc.value.reason == "ACCOUNT_ORG_MISMATCH"
    finally:
        await rt.close()


async def test_legacy_map_conflict_and_missing(tmp_path):
    rt = Runtime(settings(tmp_path))
    await rt.db.create_schema_for_test()
    from app.models import Client
    from app.core.security import digest
    try:
        async with rt.db.transaction() as session:
            session.add(Client(id="c1", org_id=ORG, name="internal", client_type="CONFIDENTIAL",
                secret_hash=digest("x"), allowed_scopes=["meeting.read"], redirect_uris=[],
                owner_member_id="legacy-1", allow_service=False, enabled=True))
        with pytest.raises(MeetingError) as exc:
            await rt.identity.apply_legacy_map([])
        assert exc.value.reason == "IDENTITY_MIGRATION_REQUIRED"
        with pytest.raises(MeetingError) as exc:
            await rt.identity.apply_legacy_map([
                {"org_id": ORG, "legacy_member_id": "legacy-1", "external_user_id": USER},
                {"org_id": ORG, "legacy_member_id": "legacy-2", "external_user_id": USER},
            ])
        assert exc.value.reason == "IDENTITY_MAPPING_CONFLICT"
    finally:
        await rt.close()


async def test_legacy_config_rejected(tmp_path):
    import base64
    with pytest.raises(ValueError, match="LEGACY_IDENTITY_CONFIG_FORBIDDEN"):
        Settings(environment="test", database_url=f"sqlite:///{tmp_path}/id.sqlite",
            keyring_json={"v1": base64.urlsafe_b64encode(b"x"*32).decode()},
            backend_service_token="s"*32, public_base_url="https://meeting.example.org",
            portal_base_url="https://portal.example.org")
