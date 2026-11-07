"""Incremental sync of Tencent GET /v1/users/list into the local directory map."""
import logging
import math
from sqlalchemy import select
from app.core.errors import MeetingError, UpstreamError
from app.models import MeetingDirectorySyncState, MeetingDirectoryUser

logger = logging.getLogger(__name__)

LOCKED_FIELDS = frozenset({"userid", "uuid", "username"})
TEXT_LIMITS = {
    "area": 16, "update_time": 32, "avatar_url": 1024, "phone": 32, "email": 256,
    "status": 32, "job_title": 128, "staff_id": 128, "entry_time": 32,
    "role_name": 64, "role_code": 64,
}
INT_FIELDS = frozenset({
    "user_account_type", "account_version", "ai_account_type", "phone_status",
    "add_on_largemeeting", "add_on_webinar", "email_status", "is_voov",
})
LIST_FIELDS = frozenset({"department_list", "allow_login_terminal"})
PAGE_SIZE = 20


def _text(value, limit: int) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return ""
    text = str(value).strip()
    return text[:limit]


def _int(value) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value.strip())
    return None


def _bool(value) -> bool | None:
    return value if isinstance(value, bool) else None


def _list(value) -> list:
    return list(value) if isinstance(value, list) else []


def _fields(row: dict) -> dict:
    userid = _text(row.get("userid"), 128)
    if not userid:
        return {}
    return {
        "userid": userid,
        "uuid": _text(row.get("uuid"), 128),
        "username": _text(row.get("username"), 256),
        "area": _text(row.get("area"), 16),
        "update_time": _text(row.get("update_time"), 32),
        "avatar_url": _text(row.get("avatar_url"), 1024),
        "phone": _text(row.get("phone"), 32),
        "email": _text(row.get("email"), 256),
        "status": _text(row.get("status"), 32),
        "job_title": _text(row.get("job_title"), 128),
        "staff_id": _text(row.get("staff_id"), 128),
        "entry_time": _text(row.get("entry_time"), 32),
        "role_name": _text(row.get("role_name"), 64),
        "role_code": _text(row.get("role_code"), 64),
        "department_list": _list(row.get("department_list")),
        "user_account_type": _int(row.get("user_account_type")),
        "account_version": _int(row.get("account_version")),
        "enable_ai_account": _bool(row.get("enable_ai_account")),
        "ai_account_type": _int(row.get("ai_account_type")),
        "phone_status": _int(row.get("phone_status")),
        "add_on_largemeeting": _int(row.get("add_on_largemeeting")),
        "add_on_webinar": _int(row.get("add_on_webinar")),
        "email_status": _int(row.get("email_status")),
        "is_voov": _int(row.get("is_voov")),
        "allow_login_terminal": _list(row.get("allow_login_terminal")),
    }


class DirectoryUserService:
    def __init__(self, runtime):
        self.rt = runtime

    async def sync(self, principal, *, full: bool = False):
        p = await self.rt.auth.revalidate(principal)
        if p.actor_type != "MEMBER" or not p.member_id:
            raise MeetingError("PERMISSION_DENIED", 403)
        if self.rt.settings.tencent_enterprise_aksk() is None:
            raise MeetingError("UPSTREAM_CREDENTIAL_INVALID", 409)
        async with self.rt.db.lock("directory-users:" + p.org_id):
            state = await self._state(p.org_id)
            start = 1 if full or state is None or state.last_page <= 0 else state.last_page + 1
            if state is not None and not full and state.total_count and start > self._pages(state.total_count):
                return self._result(started_page=start, last_page=state.last_page, synced_count=0,
                                     total_count=state.total_count, complete=True)
            page = start
            synced = 0
            total_count = state.total_count if state is not None else 0
            while True:
                raw = await self._page(page)
                users = raw.get("users")
                total = _int(raw.get("total_count"))
                if not isinstance(users, list) or total is None or total < 0:
                    logger.warning(
                        "u1.users_sync_failed org_id=%s page=%s reason=UPSTREAM_CONTRACT_ERROR kind=page_shape",
                        p.org_id, page)
                    raise UpstreamError("UPSTREAM_CONTRACT_ERROR")
                total_count = total
                pages = self._pages(total)
                if page > pages:
                    await self._save_state(p.org_id, last_page=pages, total_count=total)
                    return self._result(started_page=start, last_page=pages, synced_count=synced,
                                         total_count=total, complete=True)
                mapped = []
                for row in users:
                    if not isinstance(row, dict):
                        logger.warning(
                            "u1.users_sync_failed org_id=%s page=%s reason=UPSTREAM_CONTRACT_ERROR kind=user_not_object",
                            p.org_id, page)
                        raise UpstreamError("UPSTREAM_CONTRACT_ERROR")
                    fields = _fields(row)
                    if not fields:
                        logger.warning(
                            "u1.users_sync_failed org_id=%s page=%s reason=UPSTREAM_CONTRACT_ERROR kind=userid_missing",
                            p.org_id, page)
                        raise UpstreamError("UPSTREAM_CONTRACT_ERROR")
                    mapped.append(fields)
                if not mapped and page < pages:
                    logger.warning(
                        "u1.users_sync_failed org_id=%s page=%s reason=UPSTREAM_CONTRACT_ERROR kind=empty_before_last",
                        p.org_id, page)
                    raise UpstreamError("UPSTREAM_CONTRACT_ERROR")
                await self._upsert_page(p.org_id, mapped, page, total)
                synced += len(mapped)
                if page >= pages:
                    return self._result(started_page=start, last_page=page, synced_count=synced,
                                         total_count=total, complete=True)
                page += 1

    async def update(self, principal, userid: str, changes: dict):
        p = await self.rt.auth.revalidate(principal)
        if p.actor_type != "MEMBER" or not p.member_id:
            raise MeetingError("PERMISSION_DENIED", 403)
        if not changes or LOCKED_FIELDS & set(changes):
            raise MeetingError("INVALID_REQUEST", 422)
        unknown = set(changes) - set(TEXT_LIMITS) - INT_FIELDS - LIST_FIELDS - {"enable_ai_account"}
        if unknown:
            raise MeetingError("INVALID_REQUEST", 422)
        normalized = {}
        for key, value in changes.items():
            if key in TEXT_LIMITS:
                normalized[key] = _text(value, TEXT_LIMITS[key])
            elif key in INT_FIELDS:
                normalized[key] = _int(value)
            elif key in LIST_FIELDS:
                if not isinstance(value, list):
                    raise MeetingError("INVALID_REQUEST", 422)
                normalized[key] = list(value)
            else:
                normalized[key] = _bool(value)
        async with self.rt.db.transaction() as s:
            row = await s.scalar(select(MeetingDirectoryUser).where(
                MeetingDirectoryUser.org_id == p.org_id,
                MeetingDirectoryUser.userid == userid,
                MeetingDirectoryUser.deleted_at.is_(None)))
            if row is None:
                raise MeetingError("RESOURCE_NOT_ACCESSIBLE", 404)
            for key, value in normalized.items():
                setattr(row, key, value)
            row.version += 1
            return _public(row)

    async def _page(self, page: int):
        try:
            raw = await self.rt.tencent.users_list(page=page, page_size=PAGE_SIZE)
        except MeetingError as exc:
            logger.warning(
                "u1.users_sync_failed page=%s reason=%s upstream_code=%s status=%s",
                page, exc.reason, getattr(exc, "upstream_code", "") or "", exc.status)
            raise
        if not isinstance(raw, dict):
            logger.warning("u1.users_sync_failed page=%s reason=UPSTREAM_CONTRACT_ERROR kind=not_object", page)
            raise UpstreamError("UPSTREAM_CONTRACT_ERROR")
        return raw

    async def _state(self, org_id: str):
        async with self.rt.db.session() as s:
            return await s.scalar(select(MeetingDirectorySyncState).where(
                MeetingDirectorySyncState.org_id == org_id,
                MeetingDirectorySyncState.deleted_at.is_(None)))

    async def _upsert_page(self, org_id: str, rows: list[dict], page: int, total_count: int):
        async with self.rt.db.transaction() as s:
            for fields in rows:
                current = await s.scalar(select(MeetingDirectoryUser).where(
                    MeetingDirectoryUser.org_id == org_id,
                    MeetingDirectoryUser.userid == fields["userid"],
                    MeetingDirectoryUser.deleted_at.is_(None)))
                if current is None:
                    s.add(MeetingDirectoryUser(org_id=org_id, **fields))
                else:
                    for key, value in fields.items():
                        setattr(current, key, value)
                    current.version += 1
            state = await s.scalar(select(MeetingDirectorySyncState).where(
                MeetingDirectorySyncState.org_id == org_id,
                MeetingDirectorySyncState.deleted_at.is_(None)))
            if state is None:
                s.add(MeetingDirectorySyncState(
                    org_id=org_id, last_page=page, total_count=total_count, page_size=PAGE_SIZE))
            else:
                state.last_page = page
                state.total_count = total_count
                state.page_size = PAGE_SIZE
                state.version += 1

    async def _save_state(self, org_id: str, *, last_page: int, total_count: int):
        await self._upsert_page(org_id, [], last_page, total_count)

    @staticmethod
    def _pages(total_count: int) -> int:
        if total_count <= 0:
            return 0
        return math.ceil(total_count / PAGE_SIZE)

    @staticmethod
    def _result(*, started_page: int, last_page: int, synced_count: int, total_count: int, complete: bool):
        return {
            "started_page": started_page,
            "last_page": last_page,
            "synced_count": synced_count,
            "total_count": total_count,
            "page_size": PAGE_SIZE,
            "complete": complete,
        }


def _public(row: MeetingDirectoryUser) -> dict:
    return {
        "userid": row.userid,
        "uuid": row.uuid,
        "username": row.username,
        "area": row.area,
        "update_time": row.update_time,
        "avatar_url": row.avatar_url,
        "phone": row.phone,
        "email": row.email,
        "status": row.status,
        "job_title": row.job_title,
        "staff_id": row.staff_id,
        "entry_time": row.entry_time,
        "role_name": row.role_name,
        "role_code": row.role_code,
        "department_list": row.department_list or [],
        "user_account_type": row.user_account_type,
        "account_version": row.account_version,
        "enable_ai_account": row.enable_ai_account,
        "ai_account_type": row.ai_account_type,
        "phone_status": row.phone_status,
        "add_on_largemeeting": row.add_on_largemeeting,
        "add_on_webinar": row.add_on_webinar,
        "email_status": row.email_status,
        "is_voov": row.is_voov,
        "allow_login_terminal": row.allow_login_terminal or [],
    }
