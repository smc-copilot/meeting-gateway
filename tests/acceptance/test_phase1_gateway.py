"""Synthetic phase-1 gates. These tests never call Tencent."""
import sys
from datetime import timedelta
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1] / "integration"))
import pytest
from sqlalchemy import select, func
from app.core.errors import MeetingError
from app.core.types import utcnow
from app.models import Client, Meeting, Operation, SyncJob
from app.schemas.requests import MeetingQuery
from test_operations import member_oauth, request
from test_resources_jobs import seed


async def test_trusted_member_queues_without_waiting(rt, human, enterprise_app_body):
    _, c, p, _ = await seed(rt, human, enterprise_app_body)
    await member_oauth(rt, c)
    async with rt.db.transaction() as s:
        client = await s.get(Client, "employee-client")
        client.create_policy = "TRUSTED_MEMBER"
    op = await rt.operations.prepare(p, request(c), "trusted-1")
    assert op["state"] == "QUEUED" and op["job_id"] and rt.tencent.created == 0


async def test_human_confirm_sends_nothing_before_confirm(rt, human, enterprise_app_body):
    _, c, p, _ = await seed(rt, human, enterprise_app_body)
    await member_oauth(rt, c)
    op = await rt.operations.prepare(p, request(c), "human-1")
    assert op["state"] == "AWAITING_CONFIRMATION" and rt.tencent.created == 0
    approved = await rt.operations.confirm_business(p, op["id"], op["request_hash"])
    assert approved["state"] == "QUEUED" and rt.tencent.created == 0


async def test_approved_service_and_on_behalf_make_no_upstream_call(rt, human, enterprise_app_body):
    _, c, p, sp = await seed(rt, human, enterprise_app_body)
    await member_oauth(rt, c)
    before = len(rt.tencent.calls)
    async with rt.db.transaction() as s:
        client = await s.get(Client, "employee-client")
        client.create_policy = "APPROVED_SERVICE"
    with pytest.raises(MeetingError, match="PERMISSION_DENIED"):
        await rt.operations.prepare(p, request(c), "machine-1")
    with pytest.raises(MeetingError, match="PERMISSION_DENIED"):
        await rt.operations.prepare(sp, request(c), "service-1")
    other = request(c).model_copy(update={"host_member_id": "m2"})
    async with rt.db.transaction() as s:
        client = await s.get(Client, "employee-client")
        client.create_policy = "HUMAN_CONFIRM"
    with pytest.raises(MeetingError, match="PERMISSION_DENIED"):
        await rt.operations.prepare(p, other, "behalf-1")
    assert len(rt.tencent.calls) == before and rt.tencent.created == 0


async def test_corp_window_is_refused_with_zero_upstream_calls(rt, human, enterprise_app_body):
    _, c, p, _ = await seed(rt, human, enterprise_app_body)
    await member_oauth(rt, c)
    before = len(rt.tencent.calls)
    with pytest.raises(MeetingError, match="PERMISSION_DENIED"):
        await rt.queries.submit(p, MeetingQuery(selection="CORP_WINDOW", connection_ref=c["id"]))
    assert len(rt.tencent.calls) == before


async def test_meeting_id_miss_does_not_store_subject(rt, human, enterprise_app_body):
    _, c, p, _ = await seed(rt, human, enterprise_app_body)
    await member_oauth(rt, c)
    async with rt.db.session() as s:
        before = await s.scalar(select(func.count()).select_from(Meeting))
        jobs_before = await s.scalar(select(func.count()).select_from(SyncJob))
    with pytest.raises(MeetingError, match="RESOURCE_NOT_ACCESSIBLE"):
        await rt.queries.submit(p, MeetingQuery(selection="MEETING_ID", connection_ref=c["id"], meeting_id="missing-9"))
    async with rt.db.session() as s:
        after = await s.scalar(select(func.count()).select_from(Meeting))
        leaked = await s.scalar(select(Meeting).where(Meeting.subject == "missing-9"))
        jobs_after = await s.scalar(select(func.count()).select_from(SyncJob))
    assert after == before and leaked is None and jobs_after == jobs_before
    assert any(item[1] == "meeting" for item in rt.tencent.calls)


async def test_stale_detail_defaults_to_ensure(rt, human, enterprise_app_body):
    _, c, p, _ = await seed(rt, human, enterprise_app_body)
    result = await rt.meetings.get(p, "meeting1", fetch="ensure")
    assert result["accepted"] is True and result["job_id"]
    cached = await rt.meetings.get(p, "meeting1", fetch="cache")
    assert cached["id"] == "meeting1"


async def test_default_recording_is_explicitly_none(rt, human, enterprise_app_body):
    _, c, p, _ = await seed(rt, human, enterprise_app_body)
    await member_oauth(rt, c)
    op = await rt.operations.prepare(p, request(c), "record-none")
    await rt.operations.confirm(human, op["id"], op["request_hash"])
    job = await rt.jobs.claim("create-worker")
    await rt.operations.execute(job.id, job.lease_token)
    body = rt.tencent.calls[-1][3]["body"]
    assert body["settings"]["auto_record_type"] == "none" and rt.tencent.created == 1


async def test_enterprise_member_can_query_and_create_without_switching_channel(rt, human, enterprise_app_body):
    _, c, p, sp = await seed(rt, human, enterprise_app_body)
    before = len(rt.tencent.calls)
    with pytest.raises(MeetingError, match="PERMISSION_DENIED"):
        await rt.queries.submit(p, MeetingQuery(selection="CORP_WINDOW", connection_ref=c["id"]))
    with pytest.raises(MeetingError, match="PERMISSION_DENIED"):
        await rt.operations.prepare(sp, request(c), "service-enterprise")
    op = await rt.operations.prepare(p, request(c), "enterprise-self")
    assert op["state"] == "AWAITING_CONFIRMATION" and len(rt.tencent.calls) == before
    await rt.operations.confirm(human, op["id"], op["request_hash"])
    job = await rt.jobs.claim("enterprise-create")
    await rt.operations.execute(job.id, job.lease_token)
    assert rt.tencent.created == 1 and rt.tencent.calls[-1][2].type == 1


async def test_user_window_reads_every_page_once(rt, human, enterprise_app_body):
    _, c, p, _ = await seed(rt, human, enterprise_app_body)
    def response(operation, kwargs):
        page = kwargs["query"]["page"]
        count = 1 if page == 3 else 20
        start = (page - 1) * 20
        return {"meeting_info_list": [{"meeting_id": f"hist-{index}", "subject": "Listed", "start_time": "10", "end_time": "20"}
                                       for index in range(start, start + count)], "total_page": 3, "current_page": page,
                "record_meetings": []}
    rt._provider.response = response
    start = utcnow() - timedelta(hours=2)
    body = MeetingQuery(selection="USER_WINDOW", connection_ref=c["id"], target_member_id="m1", start_at=start, end_at=start + timedelta(hours=1))
    submitted = await rt.queries.submit(p, body)
    pages = [item[3]["query"]["page"] for item in rt.tencent.calls if item[1] == "history"]
    assert pages == [1, 2, 3]
    assert submitted["selection"] == "USER_WINDOW"
    assert submitted["meeting_count"] == 41
    assert [item["meeting_id"] for item in submitted["items"]] == [f"hist-{index}" for index in range(41)]
    assert submitted["items"][0]["subject"] == "Listed"
    assert submitted["items"][0]["state"] == "ENDED"
    assert submitted["items"][0]["connection_ref"] == c["id"]
    assert await rt.jobs.claim("history-worker") is None
    async with rt.db.session() as s:
        stored = await s.scalar(select(func.count()).select_from(Meeting).where(Meeting.external_id.like("hist-%")))
    assert stored == 0


async def test_recording_ensure_checks_upstream_even_when_empty(rt, human, enterprise_app_body):
    _, c, p, _ = await seed(rt, human, enterprise_app_body)
    job_id = await rt.queries.ensure_recordings(p, "meeting1")
    job = await rt.jobs.claim("recording-worker")
    assert job.id == job_id
    await rt.queries.run(job, job.lease_token)
    async with rt.db.session() as s:
        finished = await s.get(SyncJob, job.id)
    assert finished.progress["complete"] is True and finished.progress["upstream_empty"] is True
    assert any(item[1] == "records" for item in rt.tencent.calls)


async def test_confirmation_expires_in_ten_minutes(rt, human, enterprise_app_body):
    _, c, p, _ = await seed(rt, human, enterprise_app_body)
    await member_oauth(rt, c)
    op = await rt.operations.prepare(p, request(c), "expire-1")
    async with rt.db.transaction() as s:
        row = await s.get(Operation, op["id"])
        row.confirm_deadline = utcnow() - timedelta(seconds=1)
    with pytest.raises(MeetingError, match="OPERATION_EXPIRED"):
        await rt.operations.confirm_business(p, op["id"], op["request_hash"])
    assert rt.tencent.created == 0
