"""Strict response mapping. Unknown upstream shapes fail closed, never become fake success."""
from datetime import UTC, datetime
from app.core.errors import MeetingError
from app.core.security import canonical, digest


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
