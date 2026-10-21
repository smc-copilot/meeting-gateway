"""meeting-queries no longer embeds participants; covered here as negative contract."""
from datetime import timedelta
import pytest
from app.core.types import utcnow
from app.schemas.requests import MeetingQuery
from test_resources_jobs import seed
from test_operations import member_oauth


async def _member(rt, human, enterprise_app_body, *, oauth=True):
    _a, c, p, _sp = await seed(rt, human, enterprise_app_body)
    if oauth:
        await member_oauth(rt, c)
        async with rt.db.transaction() as s:
            from app.models import Connection
            row = await s.get(Connection, c['id'])
            row.external_id = 'open-m1'
            row.corporate_verified = True
            row.status = 'ACTIVE'
    return c, p


async def test_user_window_has_no_participants_fields(rt, human, enterprise_app_body):
    c, p = await _member(rt, human, enterprise_app_body, oauth=True)
    start = utcnow() - timedelta(days=2)
    end = utcnow()

    def response(operation, kwargs):
        if operation == 'history':
            return {
                'meeting_info_list': [{
                    'meeting_id': 'up-1', 'subject': '示例会议', 'meeting_code': '012345678',
                    'start_time': int(start.timestamp()), 'end_time': int(end.timestamp()),
                }],
                'total_page': 1,
            }
        return {}

    rt._provider.response = response
    result = await rt.queries.submit(p, MeetingQuery(
        selection='USER_WINDOW', connection_ref=c['id'], target_member_id='m1',
        start_at=start, end_at=end))
    assert result['meeting_count'] == 1
    item = result['items'][0]
    assert item['meeting_id'] == 'up-1'
    assert item['meeting_code'] == '012345678'
    assert 'participants' not in item
    assert 'participant_count' not in item
    assert 'participants_status' not in item
    assert 'participants_reason' not in item
    assert not any(call[1] == 'participants' for call in rt.tencent.calls)
    assert not any(call[1] == 'user_basic' for call in rt.tencent.calls)


async def test_meeting_id_selection_projection_only(rt, human, enterprise_app_body):
    c, p = await _member(rt, human, enterprise_app_body, oauth=True)

    def response(operation, kwargs):
        if operation == 'meeting':
            return {'meeting_info_list': [{
                'meeting_id': 'up-detail', 'subject': '单场', 'meeting_code': '814808046',
                'status': 'ENDED',
            }]}
        return {}

    rt._provider.response = response
    result = await rt.queries.submit(p, MeetingQuery(
        selection='MEETING_ID', connection_ref=c['id'], meeting_id='up-detail'))
    item = result['items'][0]
    assert item['meeting_code'] == '814808046'
    assert 'participants' not in item
    assert not any(call[1] == 'participants' for call in rt.tencent.calls)
