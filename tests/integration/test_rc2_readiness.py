"""Offline reproductions of the RC2 readiness gaps. No live Tencent account is used."""
import json
from datetime import timedelta
import httpx
import pytest
from sqlalchemy import select
from app.core.errors import ERROR_CODES, MeetingError, UpstreamError, _MESSAGES
from app.models import AccessGrant
from app.services.diagnostic_service import DiagnosticService
from app.services.diagnostic_service import DiagnosticService
from app.core.types import Operator, utcnow
from app.models import Application, Connection, Credential, EventInbox, SyncJob, Asset, Recording
from app.schemas.requests import ApplicationCreate, MeetingCreate
from test_admin_connections import prepare
from test_resources_jobs import seed
from test_tencent_transport import actual_transport
from test_events import callback


def test_error_codes_stay_frozen_when_reasons_are_appended():
    assert ERROR_CODES["RATE_LIMITED"] == 710022
    assert ERROR_CODES["UPSTREAM_UNAVAILABLE"] == 710036
    assert ERROR_CODES["UPSTREAM_DAILY_QUOTA"] == 710041
    assert set(_MESSAGES) == set(ERROR_CODES)


@pytest.mark.parametrize("code,reason", [
    (190303, "UPSTREAM_CREDENTIAL_INVALID"),
    (190325, "UPSTREAM_CAPABILITY_UNAVAILABLE"),
    (190300, "UPSTREAM_CLOCK_SKEW"),
    (190311, "UPSTREAM_DAILY_QUOTA"),
    (190312, "UPSTREAM_DAILY_QUOTA"),
    (30003, "CONTENT_NOT_READY"),
    (30002, "CONTENT_ABSENT"),
    (30001, "CONTENT_ABSENT"),
])
async def test_upstream_codes_are_classified(rt, human, enterprise_app_body, code, reason):
    a, c = await prepare(rt, human, enterprise_app_body)
    response = httpx.Response(400, json={"error_info": {"error_code": code, "message": "SECRET-BODY"}})
    client = await actual_transport(rt, lambda request: response)
    with pytest.raises(UpstreamError) as caught:
        await client.call(c["id"], "upcoming", Operator(id="external-m1", type=1))
    assert caught.value.reason == reason
    assert "SECRET" not in str(caught.value.payload("trace"))
    if reason == "UPSTREAM_DAILY_QUOTA":
        assert caught.value.retry_after is None


async def test_three_fast_transcript_pages_advance(rt, human, enterprise_app_body):
    a, c, p, sp = await seed(rt, human, enterprise_app_body)
    async with rt.db.transaction() as s:
        app = await s.get(Application, a["id"])
        await rt.admin.save_secret(s, app, "STS", {"sts_token": "ticket"}, connection_id=c["id"], expires_at=utcnow()+timedelta(hours=2))
    rt.settings.upstream_min_interval_seconds = 0.2
    seen = []

    def handler(request):
        pid = request.url.params["pid"]
        seen.append(pid)
        paragraphs = [{"pid": "p1", "sentences": [{"words": [{"text": "a"}]}]}, {"pid": "p2", "sentences": [{"words": [{"text": "b"}]}]}]
        if pid == "0":
            return httpx.Response(200, json={"more": True, "minutes": {"paragraphs": paragraphs}})
        if pid == "p2" and seen.count("p2") == 1:
            return httpx.Response(200, json={"more": True, "minutes": {"paragraphs": [paragraphs[1], {"pid": "p3", "sentences": [{"words": [{"text": "c"}]}]}]}})
        return httpx.Response(200, json={"more": False, "minutes": {"paragraphs": [{"pid": "p3", "sentences": [{"words": [{"text": "c"}]}]}]}})

    await actual_transport(rt, handler)
    asset = await rt.content.fetch(p, "record1", "transcript")
    assert asset["is_complete"] and seen[0] == "0" and seen[1] != "0" and "0" not in seen[1:]
    async with rt.db.session() as s:
        stored = await s.scalar(select(Asset).where(Asset.recording_id == "record1", Asset.asset_type == "transcript"))
        assert stored.state == "READY"


async def test_transcript_checkpoint_survives_restart(rt, human, enterprise_app_body):
    a, c, p, sp = await seed(rt, human, enterprise_app_body)
    async with rt.db.transaction() as s:
        app = await s.get(Application, a["id"])
        await rt.admin.save_secret(s, app, "STS", {"sts_token": "ticket"}, connection_id=c["id"], expires_at=utcnow()+timedelta(hours=2))
        job = await rt.jobs.enqueue(s, "CONTENT", p, {"recording_id": "record1", "content_type": "transcript"}, connection_id=c["id"])
        ident = job.id
    claimed = await rt.jobs.claim("worker")
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        pid = request.url.params["pid"]
        first = {"pid": "p1", "sentences": [{"words": [{"text": "a"}]}]}
        second = {"pid": "p2", "sentences": [{"words": [{"text": "b"}]}]}
        if pid == "0":
            return httpx.Response(200, json={"more": True, "minutes": {"paragraphs": [first]}})
        if calls["n"] == 2:
            return httpx.Response(503, json={"error_info": {"error_code": 1}})
        return httpx.Response(200, json={"more": False, "minutes": {"paragraphs": [first, second]}})

    await actual_transport(rt, handler)
    with pytest.raises(MeetingError):
        await rt.content.fetch(p, "record1", "transcript", job_id=claimed.id, lease_token=claimed.lease_token)
    async with rt.db.session() as s:
        assert not list((await s.execute(select(Asset))).scalars())
        progress = (await s.get(SyncJob, ident)).progress
        assert progress["pid"] == "p1" and progress["checkpoint_key"]
    await rt.content.fetch(p, "record1", "transcript", job_id=claimed.id, lease_token=claimed.lease_token)
    read = await rt.content.read(p, "record1", "transcript")
    assert [item["pid"] for item in read["content"]["paragraphs"]] == ["p1", "p2"]


async def test_throttle_deferral_does_not_spend_attempt_budget(rt, human, enterprise_app_body):
    a, c, p, sp = await seed(rt, human, enterprise_app_body)
    await rt.rate.acquire("shared", 6)
    with pytest.raises(MeetingError) as caught:
        await rt.rate.acquire("shared", 6)
    assert caught.value.budgeted is False
    async with rt.db.transaction() as s:
        job = await rt.jobs.enqueue(s, "SYNC", sp, {"kind": "CORP_RECORDS"}, connection_id=c["id"])
        ident = job.id
    claimed = await rt.jobs.claim("worker")
    await rt.jobs.fail(claimed.id, claimed.lease_token, caught.value)
    async with rt.db.session() as s:
        row = await s.get(SyncJob, ident)
        assert row.state == "RETRYING" and row.attempts == 0


async def test_twenty_record_pages_finish_when_spacing_is_zero(rt, human, enterprise_app_body):
    a, c, p, sp = await seed(rt, human, enterprise_app_body)
    rt.settings.upstream_min_interval_seconds = 0
    rt.settings.corp_records_min_interval_seconds = 0
    pages = []

    def handler(request):
        page = int(request.url.params["page"])
        pages.append(page)
        return httpx.Response(200, json={"total_page": 20, "current_page": page, "record_meetings": [{
            "meeting_id": "m-"+str(page), "meeting_record_id": "r-"+str(page), "subject": "S", "host_user_id": "external-m1",
            "record_files": [{"record_file_id": str(page), "record_start_time": 1700000000000, "record_end_time": 1700001000000}]}]
        })

    await actual_transport(rt, handler)
    from app.schemas.requests import SyncRequest
    await rt.sync.request(sp, SyncRequest(connection_ref=c["id"], kind="CORP_RECORDS", start_at=utcnow()-timedelta(days=1), end_at=utcnow()))
    job = await rt.jobs.claim("sync-worker")
    await rt.sync.run(job, job.lease_token)
    assert pages == list(range(1, 21))
    async with rt.db.session() as s:
        assert (await s.get(SyncJob, job.id)).progress["complete"] is True


async def test_oauth_timeout_stays_recoverable(rt, human, enterprise_app_body):
    from urllib.parse import parse_qs, urlsplit
    await rt.admin.bootstrap(human)
    data = enterprise_app_body.model_dump()
    data.update(application_type="THIRD_PARTY_OAUTH", sdk_id="oauth-sdk", data_scope="user", secret_id=None, secret_key=None,
                oauth_secret="oauth-client-test-secret", allowed_open_corp_ids=["open-corp"])
    app = await rt.admin.create_application(human, ApplicationCreate(**data))
    start = await rt.connections.oauth_start(human, app["id"])
    state = parse_qs(urlsplit(start["authorization_url"]).query)["state"][0]
    received = await rt.connections.oauth_callback(app["id"], state, "code")
    await rt.connections.confirm_oauth(human, received["connection_id"])
    async with rt.db.transaction() as s:
        cred = (await s.execute(select(Credential).where(Credential.connection_id == received["connection_id"]))).scalar_one()
        cred.expires_at = utcnow()-timedelta(minutes=1)
        before = cred.ciphertext
    rt._provider.error = UpstreamError("UPSTREAM_UNAVAILABLE")
    with pytest.raises(UpstreamError):
        await rt.connections.oauth_credentials(received["connection_id"])
    async with rt.db.session() as s:
        row = await s.get(Connection, received["connection_id"])
        cred = (await s.execute(select(Credential).where(Credential.connection_id == row.id, Credential.active.is_(True)))).scalar_one()
        assert row.status == "DEGRADED" and row.last_reason == "UPSTREAM_UNAVAILABLE" and cred.ciphertext == before
    rt._provider.error = None
    token = await rt.connections.oauth_credentials(received["connection_id"])
    assert token["access_token"] and "access_token" not in ""
    async with rt.db.session() as s:
        assert (await s.get(Connection, received["connection_id"])).status == "ACTIVE"


async def test_minutes_failure_event_does_not_publish(rt, human, enterprise_app_body):
    a, c, p, sp = await seed(rt, human, enterprise_app_body)
    body = {"event": "smart.minutes", "payload": [{"record_file_id": "file1", "result": 2, "subject": "SECRET TITLE"}]}
    data, headers = callback(body, enterprise_app_body.webhook_encoding_key)
    inbox = await rt.events.receive(a["receiver_id"], data, headers)
    job = await rt.jobs.claim("event-worker")
    await rt.events.process_inbox(job, job.lease_token)
    async with rt.db.session() as s:
        row = await s.get(EventInbox, inbox)
        assert row.safe_summary["result"] == 2 and row.safe_summary["outcome"] == "FAILED"
        assert "SECRET" not in str(row.safe_summary)
        assert not list((await s.execute(select(SyncJob).where(SyncJob.kind == "CONTENT"))).scalars())
        assert not list((await s.execute(select(Asset))).scalars())


async def test_known_recording_event_queues_content_once(rt, human, enterprise_app_body):
    a, c, p, sp = await seed(rt, human, enterprise_app_body)
    body = {"event": "recording.completed", "payload": [{"recording_files": [{"record_file_id": "file1"}]}]}
    data, headers = callback(body, enterprise_app_body.webhook_encoding_key)
    await rt.events.receive(a["receiver_id"], data, headers)
    job = await rt.jobs.claim("event-worker")
    await rt.events.process_inbox(job, job.lease_token)
    async with rt.db.session() as s:
        queued = list((await s.execute(select(SyncJob).where(SyncJob.kind.in_(["CONTENT", "INGEST_CONTENT"])))).scalars())
        assert queued and queued[0].payload["recording_id"] == "record1"


async def test_deleted_recording_event_blocks_local_read(rt, human, enterprise_app_body):
    a, c, p, sp = await seed(rt, human, enterprise_app_body)
    rt._provider.response = {"minutes": {"meeting_minute": {"minute": "# notes", "todo": ""}}}
    await rt.content.fetch(p, "record1", "minutes")
    body = {"event": "recording.deleted", "payload": [{"record_file_id": "file1"}]}
    data, headers = callback(body, enterprise_app_body.webhook_encoding_key)
    await rt.events.receive(a["receiver_id"], data, headers)
    job = await rt.jobs.claim("event-worker")
    await rt.events.process_inbox(job, job.lease_token)
    async with rt.db.session() as s:
        asset = await s.scalar(select(Asset).where(Asset.recording_id == "record1"))
        recording = await s.get(Recording, "record1")
        assert asset.state == "SOURCE_REMOVED" and recording.state == "SOURCE_REMOVED"


async def test_cloud_record_is_rejected_until_enabled_and_changes_confirmation(rt, human, enterprise_app_body):
    a, c, p, sp = await seed(rt, human, enterprise_app_body)
    start = utcnow()+timedelta(hours=1)
    from test_operations import member_oauth
    await member_oauth(rt, c)
    body = MeetingCreate(subject="Demo", start_at=start, end_at=start+timedelta(hours=1), host_member_id="m1", connection_ref=c["id"], auto_record_type="CLOUD")
    with pytest.raises(MeetingError) as caught:
        await rt.operations.prepare(p, body, "idem-1")
    assert caught.value.reason == "AUTO_RECORD_DISABLED"
    rt.settings.meeting_auto_record_enabled = True
    first = await rt.operations.prepare(p, body, "idem-2")
    plain = body.model_copy(update={"auto_record_type": "NONE"})
    second = await rt.operations.prepare(p, plain, "idem-3")
    assert first["request"]["auto_record_type"] == "CLOUD" and first["request_hash"] != second["request_hash"]


async def test_record_detail_reports_host_without_url(rt, human, enterprise_app_body):
    a, c, p, sp = await seed(rt, human, enterprise_app_body)
    rt._provider.response = {"record_detail": {"download_address": "https://media.example.org/private/file?token=secret", "file_type": "mp4"}}
    result = await DiagnosticService(rt).run(human, c["id"], "record_detail", "record1")
    assert result["media_hosts"] == [{"host": "media.example.org", "allowed": True}]
    assert "secret" not in json.dumps(result) and result["chain"][0]["status"] == "NOT_RUN"
    assert any(item["probe"] == "record_detail" and item["status"] == "PASSED" for item in result["chain"])


async def test_revoked_grant_blocks_new_download_and_range(rt, human, enterprise_app_body):
    from test_downloads import asset_seed
    _, reader = await asset_seed(rt, human, enterprise_app_body)
    ticket = await rt.downloads.issue(reader, "text1", "Review")
    async with rt.db.transaction() as s:
        s.add(AccessGrant(org_id="o1", subject_type="MEMBER", subject_id="m1", actions=["meeting.content.download"],
            scope_type="ORG_APPROVED", effect="DENY", issued_by="m1", reason="Revoked"))
    with pytest.raises(MeetingError):
        await rt.downloads.open(reader, ticket["ticket"], "bytes=0-10")
