"""Local-first meeting record-file list cache (Tencent 51189) + detail passthrough (51180)."""
import logging
from sqlalchemy import select
from app.core.errors import MeetingError, UpstreamError
from app.core.types import utcnow
from app.models import (
    MeetingRecordFileRow,
    MeetingRecordFileSnapshot,
)
from app.services.audit_service import record
from app.services.oauth_userid_map_service import OAuthUseridMapService

logger = logging.getLogger(__name__)

RECORDS_PAGE_SIZE = 20
RECORDS_MAX_PAGES = 100
MAX_WINDOW_SECONDS = 31 * 24 * 3600


def _as_str_id(value) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value)[:128]
    if isinstance(value, float):
        text = str(int(value)) if value.is_integer() else str(value)
        return text[:128] if text else None
    if isinstance(value, str) and value.strip():
        return value.strip()[:128]
    return None


def _as_int(value) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip().lstrip('-').isdigit():
        return int(value.strip())
    return None


def _as_bool(value) -> bool | None:
    return value if isinstance(value, bool) else None


def _as_page_count(value) -> int | None:
    """Normalize Tencent total_page; empty/missing treated as 0."""
    if value is None or value == '':
        return 0
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float) and value.is_integer() and value >= 0:
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def map_record_file(row: dict) -> dict | None:
    file_id = _as_str_id(row.get('record_file_id'))
    if not file_id:
        return None
    password = row.get('password')
    password = password[:128] if isinstance(password, str) and password else None
    sharing_url = row.get('sharing_url')
    sharing_url = sharing_url if isinstance(sharing_url, str) and sharing_url else None
    return {
        'record_file_id': file_id,
        'record_start_time': _as_int(row.get('record_start_time')),
        'record_end_time': _as_int(row.get('record_end_time')),
        'record_size': _as_int(row.get('record_size')),
        'sharing_state': _as_int(row.get('sharing_state')),
        'sharing_url': sharing_url,
        'required_same_corp': _as_bool(row.get('required_same_corp')),
        'required_participant': _as_bool(row.get('required_participant')),
        'password': password,
        'sharing_expire': _as_int(row.get('sharing_expire')),
        'allow_download': _as_bool(row.get('allow_download')),
    }


class RecordFileCacheService:
    def __init__(self, runtime):
        self.rt = runtime

    async def list_record_files(self, principal, connection_ref: str, meeting_id: str, *,
                                pos: int = 0, size: int = 20):
        if not meeting_id or len(meeting_id) > 128:
            raise MeetingError('INVALID_REQUEST', 422)
        if pos < 0 or size < 1 or size > 100:
            raise MeetingError('INVALID_REQUEST', 422)
        p, c = await self._authorize_oauth(principal, connection_ref)

        lock_key = 'record-files-cache:' + c.id + ':' + meeting_id
        async with self.rt.db.lock(lock_key):
            snapshot = await self._find_snapshot(p.org_id, c.id, meeting_id)
            source = 'cache'
            if snapshot is None:
                if self.rt.settings.tencent_enterprise_aksk() is None:
                    logger.warning(
                        'r1.record_files_failed connection_id=%s meeting_id=%s step=env_aksk reason=UPSTREAM_CREDENTIAL_INVALID',
                        c.id, meeting_id)
                    raise MeetingError('UPSTREAM_CREDENTIAL_INVALID', 409)
                try:
                    userid = await OAuthUseridMapService(self.rt).resolve_userid(c, log_prefix='r1')
                    start_time, end_time = self._default_window()
                    files, meta = await self._fetch_all_pages(userid, meeting_id, start_time, end_time)
                except MeetingError as exc:
                    logger.warning(
                        'r1.record_files_failed connection_id=%s meeting_id=%s reason=%s upstream_code=%s status=%s',
                        c.id, meeting_id, exc.reason,
                        getattr(exc, 'upstream_code', '') or '',
                        exc.status)
                    raise
                snapshot = await self._write_all(p.org_id, c.id, meeting_id, files, meta)
                source = 'fetched'
                async with self.rt.db.transaction() as s:
                    record(s, p, 'meeting.record_files.cached', resource_id=c.id,
                           details={'status': len(files)})

        return await self._page_local(snapshot, meeting_id, source=source, pos=pos, size=size)

    async def get_record_file_detail(self, principal, connection_ref: str, record_file_id: str):
        file_id = _as_str_id(record_file_id)
        if not file_id:
            raise MeetingError('INVALID_REQUEST', 422)
        p, c = await self._authorize_oauth(principal, connection_ref)
        if self.rt.settings.tencent_enterprise_aksk() is None:
            logger.warning(
                'r2.record_file_detail_failed connection_id=%s record_file_id=%s step=env_aksk reason=UPSTREAM_CREDENTIAL_INVALID',
                c.id, file_id)
            raise MeetingError('UPSTREAM_CREDENTIAL_INVALID', 409)
        token = await self.rt.env_sts.current_token()
        if token is None:
            await self.rt.env_sts.refresh_due()
            token = await self.rt.env_sts.current_token()
        if token is None:
            logger.warning(
                'r2.record_file_detail_failed connection_id=%s record_file_id=%s step=sts_token reason=STS_NOT_READY',
                c.id, file_id)
            raise MeetingError('STS_NOT_READY', 409)
        try:
            raw = await self.rt.tencent.record_detail_aksk(record_file_id=file_id, sts_token=token)
        except MeetingError as exc:
            logger.warning(
                'r2.record_file_detail_failed connection_id=%s record_file_id=%s step=record_detail_aksk '
                'reason=%s upstream_code=%s status=%s',
                c.id, file_id, exc.reason, getattr(exc, 'upstream_code', '') or '', exc.status)
            raise
        if not isinstance(raw, dict):
            logger.warning(
                'r2.record_file_detail_failed connection_id=%s record_file_id=%s step=record_detail_aksk '
                'reason=UPSTREAM_CONTRACT_ERROR kind=not_object',
                c.id, file_id)
            raise UpstreamError('UPSTREAM_CONTRACT_ERROR')
        async with self.rt.db.transaction() as s:
            record(s, p, 'meeting.record_file.detail', resource_id=c.id)
        return raw

    async def _authorize_oauth(self, principal, connection_ref: str):
        p = await self.rt.auth.revalidate(principal)
        if p.actor_type != 'MEMBER' or not p.member_id:
            raise MeetingError('PERMISSION_DENIED', 403)
        c, _app = await self.rt.connections.owned(p, connection_ref)
        if c.member_id != p.member_id or c.kind != 'THIRD_PARTY_OAUTH':
            raise MeetingError('PERMISSION_DENIED', 403)
        async with self.rt.db.session() as s:
            await self.rt.policy.require(s, p, 'meeting.read', connection_id=c.id)
        return p, c

    async def _find_snapshot(self, org_id, connection_id, meeting_id):
        async with self.rt.db.session() as s:
            return await s.scalar(select(MeetingRecordFileSnapshot).where(
                MeetingRecordFileSnapshot.org_id == org_id,
                MeetingRecordFileSnapshot.connection_id == connection_id,
                MeetingRecordFileSnapshot.external_meeting_id == meeting_id,
                MeetingRecordFileSnapshot.deleted_at.is_(None)))

    def _default_window(self):
        """Tencent 51189 requires start_time/end_time within 31 days; gateway assigns defaults."""
        end = int(utcnow().timestamp())
        start = end - MAX_WINDOW_SECONDS
        if end <= start:
            end = start + 60
        return start, end

    async def _fetch_all_pages(self, userid, meeting_id, start_time, end_time):
        files = []
        seen: set[str] = set()
        meta = {
            'meeting_code': None,
            'subject': None,
            'meeting_record_id': None,
            'state': None,
        }
        page = 1
        for _ in range(RECORDS_MAX_PAGES):
            raw = await self.rt.tencent.records_aksk(query={
                'meeting_id': meeting_id,
                'userid': userid,
                'start_time': start_time,
                'end_time': end_time,
                'page': page,
                'page_size': RECORDS_PAGE_SIZE,
            })
            if not isinstance(raw, dict):
                logger.warning(
                    'r1.record_files_failed meeting_id=%s step=records_aksk reason=UPSTREAM_CONTRACT_ERROR kind=not_object',
                    meeting_id)
                raise UpstreamError('UPSTREAM_CONTRACT_ERROR')
            rows = raw.get('record_meetings')
            if rows is None:
                rows = []
            total_page = _as_page_count(raw.get('total_page'))
            if not isinstance(rows, list) or total_page is None:
                logger.warning(
                    'r1.record_files_failed meeting_id=%s step=records_aksk reason=UPSTREAM_CONTRACT_ERROR '
                    'kind=page_shape rows_type=%s total_page=%r',
                    meeting_id, type(rows).__name__, raw.get('total_page'))
                raise UpstreamError('UPSTREAM_CONTRACT_ERROR')
            # No recordings: empty page is success (cache empty snapshot).
            if total_page == 0 or (page == 1 and len(rows) == 0):
                return files, meta
            for meeting in rows:
                if not isinstance(meeting, dict):
                    logger.warning(
                        'r1.record_files_failed meeting_id=%s step=records_aksk reason=UPSTREAM_CONTRACT_ERROR kind=meeting_not_object',
                        meeting_id)
                    raise UpstreamError('UPSTREAM_CONTRACT_ERROR')
                if meta['meeting_code'] is None and meeting.get('meeting_code') not in (None, ''):
                    meta['meeting_code'] = str(meeting.get('meeting_code'))[:64]
                if meta['subject'] is None and isinstance(meeting.get('subject'), str) and meeting.get('subject'):
                    meta['subject'] = meeting['subject'][:512]
                if meta['meeting_record_id'] is None and meeting.get('meeting_record_id') not in (None, ''):
                    meta['meeting_record_id'] = str(meeting.get('meeting_record_id'))[:128]
                if meta['state'] is None:
                    meta['state'] = _as_int(meeting.get('state'))
                record_files = meeting.get('record_files')
                if record_files is None:
                    record_files = []
                if not isinstance(record_files, list):
                    logger.warning(
                        'r1.record_files_failed meeting_id=%s step=records_aksk reason=UPSTREAM_CONTRACT_ERROR kind=record_files_not_list',
                        meeting_id)
                    raise UpstreamError('UPSTREAM_CONTRACT_ERROR')
                for row in record_files:
                    if not isinstance(row, dict):
                        logger.warning(
                            'r1.record_files_failed meeting_id=%s step=records_aksk reason=UPSTREAM_CONTRACT_ERROR kind=file_not_object',
                            meeting_id)
                        raise UpstreamError('UPSTREAM_CONTRACT_ERROR')
                    mapped = map_record_file(row)
                    if mapped is None:
                        logger.warning(
                            'r1.record_files_failed meeting_id=%s step=records_aksk reason=UPSTREAM_CONTRACT_ERROR kind=record_file_id_missing',
                            meeting_id)
                        raise UpstreamError('UPSTREAM_CONTRACT_ERROR')
                    if mapped['record_file_id'] in seen:
                        continue
                    seen.add(mapped['record_file_id'])
                    files.append(mapped)
            if page >= total_page:
                return files, meta
            page += 1
        logger.warning(
            'r1.record_files_failed meeting_id=%s step=records_aksk reason=UPSTREAM_CONTRACT_ERROR kind=page_limit',
            meeting_id)
        raise UpstreamError('UPSTREAM_CONTRACT_ERROR')

    async def _write_all(self, org_id, connection_id, meeting_id, files, meta):
        async with self.rt.db.transaction() as s:
            existing = await s.scalar(select(MeetingRecordFileSnapshot).where(
                MeetingRecordFileSnapshot.org_id == org_id,
                MeetingRecordFileSnapshot.connection_id == connection_id,
                MeetingRecordFileSnapshot.external_meeting_id == meeting_id,
                MeetingRecordFileSnapshot.deleted_at.is_(None)))
            if existing is not None:
                return existing
            now = utcnow()
            snapshot = MeetingRecordFileSnapshot(
                org_id=org_id,
                connection_id=connection_id,
                external_meeting_id=meeting_id,
                meeting_code=meta.get('meeting_code'),
                subject=meta.get('subject'),
                meeting_record_id=meta.get('meeting_record_id'),
                state=meta.get('state'),
                total_count=len(files),
                fetched_at=now,
            )
            s.add(snapshot)
            await s.flush()
            for index, fields in enumerate(files):
                s.add(MeetingRecordFileRow(
                    org_id=org_id,
                    snapshot_id=snapshot.id,
                    connection_id=connection_id,
                    external_meeting_id=meeting_id,
                    record_file_id=fields['record_file_id'],
                    record_start_time_ms=fields['record_start_time'],
                    record_end_time_ms=fields['record_end_time'],
                    record_size=fields['record_size'],
                    sharing_state=fields['sharing_state'],
                    sharing_url=fields['sharing_url'],
                    required_same_corp=fields['required_same_corp'],
                    required_participant=fields['required_participant'],
                    password=fields['password'],
                    sharing_expire=fields['sharing_expire'],
                    allow_download=fields['allow_download'],
                    sort_index=index,
                ))
            return snapshot

    async def _page_local(self, snapshot, meeting_id, *, source: str, pos: int, size: int):
        async with self.rt.db.session() as s:
            result = await s.execute(
                select(MeetingRecordFileRow)
                .where(
                    MeetingRecordFileRow.snapshot_id == snapshot.id,
                    MeetingRecordFileRow.deleted_at.is_(None),
                )
                .order_by(MeetingRecordFileRow.sort_index.asc())
            )
            all_rows = list(result.scalars())
        total = len(all_rows)
        page = all_rows[pos:pos + size]
        record_files = [{
            'record_file_id': row.record_file_id,
            'record_start_time': row.record_start_time_ms,
            'record_end_time': row.record_end_time_ms,
            'record_size': row.record_size,
            'sharing_state': row.sharing_state,
            'sharing_url': row.sharing_url,
            'required_same_corp': row.required_same_corp,
            'required_participant': row.required_participant,
            'password': row.password,
            'sharing_expire': row.sharing_expire,
            'allow_download': row.allow_download,
        } for row in page]
        next_pos = pos + len(page)
        return {
            'meeting_id': meeting_id,
            'source': source,
            'record_file_count': total,
            'total_count': snapshot.total_count if snapshot.total_count is not None else total,
            'meeting_code': snapshot.meeting_code,
            'subject': snapshot.subject,
            'pos': pos,
            'size': size,
            'has_remaining': next_pos < total,
            'next_pos': next_pos if next_pos < total else None,
            'record_files': record_files,
        }
