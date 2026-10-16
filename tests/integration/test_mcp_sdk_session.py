"""Optional MCP SDK session. Skipped when the SDK is not installed; a skip is not a pass."""
import pytest

pytestmark = pytest.mark.sdk


async def _pkce_token(rt, human):
    from urllib.parse import parse_qs, urlsplit
    from app.core.security import pkce_challenge
    from app.schemas.requests import ClientCreate
    from test_http_mcp import client_for
    created = await rt.admin.create_client(human, ClientCreate(
        name="SDK public", client_type="PUBLIC_MCP", allowed_scopes=["meeting.read"],
        redirect_uris=["https://client.example.org/callback"], owner_member_id="m1", reason="SDK session"))
    verifier = "x" * 64
    async with await client_for(rt) as client:
        params = {"response_type": "code", "client_id": created["id"],
            "redirect_uri": "https://client.example.org/callback", "resource": rt.settings.mcp_resource_uri,
            "scope": "meeting.read", "state": "sdk-state", "code_challenge": pkce_challenge(verifier),
            "code_challenge_method": "S256"}
        res = await client.get("/oauth/authorize", params=params, follow_redirects=False)
        txn = parse_qs(urlsplit(res.headers["location"]).query)["transaction_id"][0]
        approved = (await client.post("/api/v1/portal/authorization/" + txn + "/approve",
            headers={"Authorization": "Bearer backend-m1"}, json={})).json()["data"]
        code = parse_qs(urlsplit(approved["redirect_uri"]).query)["code"][0]
        token = (await client.post("/oauth/token", data={
            "grant_type": "authorization_code", "client_id": created["id"], "code": code,
            "code_verifier": verifier, "redirect_uri": params["redirect_uri"], "resource": params["resource"]})).json()
    return created, token["access_token"]


def _open(rt, token):
    import httpx
    from mcp.client.streamable_http import streamable_http_client
    from app.main import create_app
    http = httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(runtime=rt)),
        base_url="https://meeting.example.org", headers={"Authorization": "Bearer " + token})
    return http, streamable_http_client("https://meeting.example.org/mcp", http_client=http, terminate_on_close=False)


async def _use(rt, token, callback):
    from mcp.client.session import ClientSession
    http, transport = _open(rt, token)
    async with http, transport as (read, write, _session_id):
        async with ClientSession(read, write) as session:
            return await callback(session)


async def test_sdk_session_lists_calls_and_matches_rest_denial(rt, human, enterprise_app_body):
    pytest.importorskip("mcp.client.session", reason="MCP SDK unavailable; this session test is not a pass")
    from test_http_mcp import client_for, issue
    from test_resources_jobs import seed
    await seed(rt, human, enterprise_app_body)
    created, token = await _pkce_token(rt, human)

    async def first(session):
        initial = await session.initialize()
        names = {item.name for item in (await session.list_tools()).tools}
        denied = await session.call_tool("meeting_transcript_read", {"recording_id": "record1"})
        return initial.protocolVersion, names, denied.isError

    version, names, denied = await _use(rt, token, first)
    assert version == "2025-11-25" and "meeting_list" in names and denied is True
    again = await _use(rt, token, lambda session: session.initialize())
    assert again.protocolVersion == "2025-11-25"
    await rt.auth.revoke(created["id"], None, token)
    with pytest.raises(Exception):
        await _use(rt, token, lambda session: session.initialize())
    rest = await issue(rt, human, ["meeting.read"], rt.settings.rest_resource_uri)
    async with await client_for(rt) as client:
        response = await client.get("/api/v1/recordings/record1/transcript", headers={"Authorization": "Bearer " + rest})
        assert response.status_code == 404
    wrong = await issue(rt, human, ["meeting.read"], rt.settings.rest_resource_uri)
    with pytest.raises(Exception):
        await _use(rt, wrong, lambda session: session.initialize())
