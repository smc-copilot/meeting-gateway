"""Strict response mapping. Unknown upstream shapes fail closed, never become fake success."""
import base64
from datetime import UTC, datetime
from app.core.errors import MeetingError
from app.core.security import canonical, digest

PARTICIPANTS_PAGE_SIZE = 100
PARTICIPANTS_MAX_PAGES = 50
PARTICIPANTS_MAX_PEOPLE = 5000
USER_BASIC_MAX_LOOKUPS = 50


def decode_join_name(user_name) -> str | None:
    if not isinstance(user_name, str) or not user_name:
        return None
    try:
        text = base64.b64decode(user_name, validate=True).decode('utf-8')
    except (ValueError, UnicodeError):
        return None
    text = text.strip()
    return text[:256] if text else None


def participant_dedupe_key(row: dict) -> str | None:
    for field in ('open_id', 'userid', 'ms_open_id'):
        value = row.get(field)
        if isinstance(value, str) and value.strip():
            return field + ':' + value.strip()
    return None


def _optional_id(value) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()[:128]
    return None


def map_participant(row: dict) -> dict:
    internal = row.get('is_enterprise_user')
    if not isinstance(internal, bool):
        internal = None
    return {
        'display_name': None,
        'join_name': decode_join_name(row.get('user_name')),
        'department': None,
        'position': None,
        'is_internal': internal,
        '_open_id': _optional_id(row.get('open_id')),
    }


def cache_participant_fields(row: dict) -> dict:
    """Normalize a Tencent 42701 participant row for local cache storage."""
    internal = row.get('is_enterprise_user')
    if not isinstance(internal, bool):
        internal = None
    user_name = row.get('user_name')
    user_name_b64 = user_name if isinstance(user_name, str) and user_name else None
    return {
        'open_id': _optional_id(row.get('open_id')),
        'userid': _optional_id(row.get('userid')),
        'ms_open_id': _optional_id(row.get('ms_open_id')),
        'user_name_b64': user_name_b64,
        'join_name': decode_join_name(user_name),
        'is_enterprise_user': internal,
    }


def public_participant(row: dict) -> dict:
    return {
        'display_name': row.get('display_name'),
        'join_name': row.get('join_name'),
        'department': row.get('department'),
        'position': row.get('position'),
        'is_internal': row.get('is_internal'),
    }


def apply_display_names(participants: list[dict], names: dict[str, str | None]) -> list[dict]:
    result = []
    for row in participants:
        open_id = row.get('_open_id')
        display = None
        if isinstance(open_id, str) and names.get(open_id):
            display = str(names[open_id])[:256]
        result.append({
            'display_name': display,
            'join_name': row.get('join_name'),
            'department': row.get('department'),
            'position': row.get('position'),
            'is_internal': row.get('is_internal'),
        })
    return result


def unavailable_participants(reason: str) -> dict:
    return {
        'participant_count': None,
        'participants_status': 'UNAVAILABLE',
        'participants_reason': reason,
        'participants': [],
    }


def merge_participant_pages(pages: list[dict], *, truncated: bool = False, finalize: bool = True) -> dict:
    """Map Tencent participants pages into meeting-queries enrichment fields.

    Tencent field map (OAuth):
    - user_name (Base64) -> join_name
    - display_name from GET /v1/users/info/basic username when open_id is available
    - is_enterprise_user -> is_internal
    - department/position unavailable from participants/basic APIs -> null
    Dedup prefers open_id, then userid, then ms_open_id.
    """
    ordered: list[dict] = []
    seen: set[str] = set()
    for page in pages:
        rows = page.get('participants') if isinstance(page, dict) else None
        if not isinstance(rows, list):
            raise MeetingError('UPSTREAM_CONTRACT_ERROR', 502)
        for row in rows:
            if not isinstance(row, dict):
                raise MeetingError('UPSTREAM_CONTRACT_ERROR', 502)
            key = participant_dedupe_key(row)
            if key is None:
                ordered.append(map_participant(row))
                continue
            if key in seen:
                continue
            seen.add(key)
            ordered.append(map_participant(row))
    people = [public_participant(p) for p in ordered] if finalize else ordered
    if truncated:
        return {
            'participant_count': None,
            'participants_status': 'PARTIAL',
            'participants_reason': 'participants.truncated',
            'participants': people,
        }
    return {
        'participant_count': len(people),
        'participants_status': 'READY',
        'participants_reason': None,
        'participants': people,
    }


def normalize_minutes(value: dict, *, llm: int = 3, text_type: int = 2) -> dict:
    minute = value.get("meeting_minute")
    if not isinstance(minute, dict) or not isinstance(minute.get("minute"), str):
        raise MeetingError("UPSTREAM_CONTRACT_ERROR", 502)
    return {"provider": "tencent_meeting", "llm": llm,
            "minute_type_effective": 2 if llm == 3 else 1, "text_type": text_type,
            "language": "default", "minute": minute["minute"], "todo": minute.get("todo") or ""}


def milliseconds(value) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(int(value) / 1000, UTC)
    except (ValueError, OverflowError, TypeError) as exc:
        raise MeetingError("UPSTREAM_CONTRACT_ERROR", 502) from exc


def seconds(value) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(int(value), UTC)
    except (ValueError, OverflowError, TypeError) as exc:
        raise MeetingError("UPSTREAM_CONTRACT_ERROR", 502) from exc


class TranscriptCollector:
    """pid is an inclusive string cursor; never invent pid+1 for opaque IDs."""
    def __init__(self):
        self.paragraphs: list[dict] = []
        self.seen: dict[str, str] = {}
        self.last_pid: str | None = None
        self.complete = False
        self.pages = 0

    def snapshot(self) -> dict:
        return {'paragraphs': self.paragraphs, 'last_pid': self.last_pid, 'complete': self.complete, 'pages': self.pages}

    @classmethod
    def restore(cls, data: dict):
        self = cls()
        paragraphs = data.get('paragraphs')
        if not isinstance(paragraphs, list):
            raise MeetingError('UPSTREAM_CONTRACT_ERROR', 502)
        self.paragraphs = paragraphs
        self.seen = {str(item['pid']): digest(canonical(item)) for item in paragraphs if isinstance(item, dict) and 'pid' in item}
        self.last_pid = data.get('last_pid')
        self.complete = bool(data.get('complete'))
        self.pages = int(data.get('pages') or 0)
        return self

    def resume_pid(self) -> str:
        return '0' if not self.last_pid else str(self.last_pid)

    def add(self, page: dict) -> str | None:
        raw = page.get("minutes", {}).get("paragraphs")
        if not isinstance(raw, list) or not isinstance(page.get("more"), bool) or self.complete:
            raise MeetingError("UPSTREAM_CONTRACT_ERROR", 502)
        if self.last_pid is not None and (not raw or str(raw[0].get("pid", "")) != self.last_pid):
            raise MeetingError("CONTENT_CHANGED", 409)
        added = 0
        for index, item in enumerate(raw):
            if not isinstance(item, dict) or "pid" not in item:
                raise MeetingError("UPSTREAM_CONTRACT_ERROR", 502)
            pid = str(item["pid"])
            fingerprint = digest(canonical(item))
            if pid in self.seen:
                if index != 0 or pid != self.last_pid or self.seen[pid] != fingerprint:
                    raise MeetingError("CONTENT_CHANGED", 409)
                continue
            self.seen[pid] = fingerprint
            self.paragraphs.append(item)
            added += 1
        if page["more"] and (not raw or added == 0):
            raise MeetingError("CONTENT_CHANGED", 409)
        self.pages += 1
        self.last_pid = str(raw[-1]["pid"]) if raw else self.last_pid
        self.complete = not page["more"]
        return None if self.complete else self.last_pid

    def finish(self) -> dict:
        if not self.complete:
            raise MeetingError("CONTENT_NOT_READY", 409)
        public = []
        for item in self.paragraphs:
            text = "".join(str(word.get("text", "")) for sentence in item.get("sentences", [])
                           for word in sentence.get("words", []))
            public.append({"pid": str(item["pid"]), "start_time_ms": item.get("start_time"),
                           "end_time_ms": item.get("end_time"), "speaker_label": item.get("speaker_info", {}).get("username", ""),
                           "text": text, "sentences": item.get("sentences", [])})
        return {"provider": "tencent_meeting", "paragraphs": public, "is_complete": True,
                "source_page_count": self.pages, "source_digest": digest(canonical(self.paragraphs)),
                "consistency": "inclusive_overlap_verified"}
