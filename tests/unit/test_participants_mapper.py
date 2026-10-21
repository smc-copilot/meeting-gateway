import base64
import pytest
from app.core.errors import MeetingError
from app.integrations.tencent_meeting.mapper import (
    decode_join_name, map_participant, merge_participant_pages, unavailable_participants,
)


def test_decode_join_name_base64_and_invalid():
    assert decode_join_name(base64.b64encode('示例入会'.encode()).decode()) == '示例入会'
    assert decode_join_name('!!!') is None
    assert decode_join_name('') is None
    assert decode_join_name(None) is None


def test_map_participant_fields():
    row = {
        'user_name': base64.b64encode(b'Alice').decode(),
        'is_enterprise_user': True,
        'open_id': 'open-1',
    }
    assert map_participant(row) == {
        'display_name': None,
        'join_name': 'Alice',
        'department': None,
        'position': None,
        'is_internal': True,
        '_open_id': 'open-1',
    }


def test_cache_participant_fields():
    from app.integrations.tencent_meeting.mapper import cache_participant_fields
    encoded = base64.b64encode('入会'.encode()).decode()
    assert cache_participant_fields({
        'open_id': 'o1', 'userid': 'u1', 'ms_open_id': 'm1',
        'user_name': encoded, 'is_enterprise_user': False,
    }) == {
        'open_id': 'o1', 'userid': 'u1', 'ms_open_id': 'm1',
        'user_name_b64': encoded, 'join_name': '入会', 'is_enterprise_user': False,
    }


def test_apply_display_names_from_user_basic():
    from app.integrations.tencent_meeting.mapper import apply_display_names
    rows = [
        {'_open_id': 'o1', 'join_name': '入会', 'display_name': None, 'department': None, 'position': None, 'is_internal': True},
        {'_open_id': None, 'join_name': '访客', 'display_name': None, 'department': None, 'position': None, 'is_internal': False},
    ]
    out = apply_display_names(rows, {'o1': '用户昵称'})
    assert out[0]['display_name'] == '用户昵称' and '_open_id' not in out[0]
    assert out[1]['display_name'] is None


def test_merge_ready_empty_and_dedupe():
    empty = merge_participant_pages([{'participants': [], 'has_remaining': False}])
    assert empty == {
        'participant_count': 0,
        'participants_status': 'READY',
        'participants_reason': None,
        'participants': [],
    }
    name = base64.b64encode(b'Bob').decode()
    pages = [{
        'participants': [
            {'open_id': 'o1', 'user_name': name, 'is_enterprise_user': False},
            {'open_id': 'o1', 'user_name': name, 'is_enterprise_user': False},
            {'userid': 'u2', 'user_name': name, 'is_enterprise_user': True},
        ],
        'has_remaining': False,
    }]
    merged = merge_participant_pages(pages)
    assert merged['participants_status'] == 'READY'
    assert merged['participant_count'] == 2
    assert [p['is_internal'] for p in merged['participants']] == [False, True]


def test_merge_partial_when_truncated():
    pages = [{'participants': [{'ms_open_id': 'tmp-1', 'user_name': base64.b64encode(b'X').decode()}],
              'has_remaining': True}]
    merged = merge_participant_pages(pages, truncated=True)
    assert merged['participants_status'] == 'PARTIAL'
    assert merged['participant_count'] is None
    assert merged['participants_reason'] == 'participants.truncated'
    assert len(merged['participants']) == 1


def test_merge_rejects_bad_page_shape():
    with pytest.raises(MeetingError):
        merge_participant_pages([{'participants': 'bad'}])


def test_unavailable_helper():
    assert unavailable_participants('participants.oauth_only')['participants_status'] == 'UNAVAILABLE'
    assert unavailable_participants('participants.oauth_only')['participant_count'] is None
