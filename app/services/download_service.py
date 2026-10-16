"""Gateway-controlled native downloads with subject binding and connect-time DNS validation.

Already-transmitted bytes cannot be recalled. Quota counts bytes authorized for
transmission (a disconnect may therefore conservatively over-count a final chunk).
"""
import asyncio
from datetime import timedelta
import re
import time
from sqlalchemy import select
import aiohttp
from app.core.errors import MeetingError
from app.core.security import digest, random_token
from app.core.types import utcnow
from app.models import Asset, DownloadTicket, DownloadQuota, AccessToken
from app.storage.safe_http import SafeHTTP
from app.services.audit_service import record

MIME = {'txt': 'text/plain', 'pdf': 'application/pdf', 'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'md': 'text/markdown', 'mp4': 'video/mp4', 'm4a': 'audio/mp4', 'mp3': 'audio/mpeg', 'wav': 'audio/wav'}


class PreparedDownload:
    def __init__(self, service, principal, token, ticket_id, session, response, extension, expected_size):
        self.service, self.principal, self.token, self.ticket_id = service, principal, token, ticket_id
        self.session, self.response, self.extension = session, response, extension
        self.expected_size, self.sent, self.closed = expected_size, 0, False
        self.status = response.status
        self.headers = {'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff',
                        'Content-Disposition': f'attachment; filename="meeting-{ticket_id}.{extension}"'}
        if response.headers.get('Content-Length'):
            self.headers['Content-Length'] = str(expected_size)
        if response.status == 206:
            self.headers['Content-Range'] = response.headers['Content-Range']
            self.headers['Accept-Ranges'] = 'bytes'
        self.media_type = MIME[extension]

    async def close(self):
        if self.closed:
            return
        self.closed = True
        self.response.close()
        await self.session.close()
        await self.service.release(self.principal, self.ticket_id, self.sent)

    async def iterate(self):
        started = checked = time.monotonic()
        since_check = 0
        try:
            async for chunk in self.response.content.iter_chunked(65536):
                if self.sent + len(chunk) > self.service.rt.settings.max_download_bytes:
                    raise MeetingError('DOWNLOAD_NOT_ALLOWED', 413)
                now = time.monotonic()
                if now-checked >= 30 or since_check >= 8*1024*1024:
                    self.principal, row, asset = await self.service.validate(self.principal, self.token)
                    async with self.service.rt.db.session() as session:
                        asset, rec, _ = await self.service._asset(session, self.principal, asset.id)
                    await self.service.native_address(self.principal, asset, rec)
                    await self.service.heartbeat(row.id)
                    checked, since_check = now, 0
                # Reserve quota before returning bytes. Every process uses the same row and advisory lock.
                await self.service.charge(self.principal, len(chunk))
                delay = (self.sent+len(chunk))/self.service.rt.settings.download_bytes_per_second - (time.monotonic()-started)
                if delay > 0:
                    await asyncio.sleep(delay)
                self.sent += len(chunk)
                since_check += len(chunk)
                yield chunk
            if self.expected_size is not None and self.sent != self.expected_size:
                raise MeetingError('UPSTREAM_UNAVAILABLE', 502)
        finally:
            await asyncio.shield(self.close())


class DownloadService:
    def __init__(self, runtime):
        self.rt = runtime
        self.http = SafeHTTP(runtime.settings.media_allowed_hosts)

    def parse_range(self, value):
        if value is None:
            return None
        if len(value) > 80 or not re.fullmatch(r'bytes=(?:[0-9]+-[0-9]*|-[0-9]+)', value):
            raise MeetingError('INVALID_REQUEST', 416)
        start, end = value[6:].split('-')
        if (not start and int(end) == 0) or (start and end and int(start) > int(end)):
            raise MeetingError('INVALID_REQUEST', 416)
        if len(start) > 19 or len(end) > 19:
            raise MeetingError('INVALID_REQUEST', 416)
        return value

    async def _asset(self, s, p, ident):
        a = await self.rt.admin._get(s, Asset, p.org_id, ident)
        rec, m = await self.rt.meetings.recording(s, p, a.recording_id, 'meeting.content.download', asset_type=a.asset_type)
        await self.rt.policy.require(s, p, 'meeting.content.download', meeting=m, asset=a)
        if a.state in {'BLOCKED', 'SOURCE_REMOVED'} or (a.expires_at and a.expires_at <= utcnow()):
            raise MeetingError('DOWNLOAD_NOT_ALLOWED', 403)
        if a.asset_type in {'video', 'audio'} and not self.rt.settings.meeting_media_download_enabled:
            raise MeetingError('FEATURE_DISABLED', 403)
        return a, rec, m

    async def native_address(self, p, a, rec):
        c, op = await self.rt.content._source(p, rec)
        raw = await self.rt.tencent.call(c.id, 'record_detail', op, file_id=rec.external_file_id)
        if raw.get('allow_download') is False:
            raise MeetingError('DOWNLOAD_NOT_ALLOWED', 403)
        if a.asset_type == 'transcript':
            entries = raw.get('meeting_summary', [])
        elif a.asset_type == 'minutes':
            # Tencent's documented export fields do not include a Yuanbao equivalent.
            # Never silently substitute DeepSeek/Hunyuan for the Yuanbao asset.
            llm = (a.details or {}).get('llm', 3)
            key = {1: 'ai_topic_minutes', 2: 'ai_ds_minutes'}.get(llm)
            entries = raw.get(key, []) if key else []
        elif a.asset_type == 'video':
            entries = [{'download_address': raw.get('download_address'), 'file_type': raw.get('file_type', 'mp4')}]
        elif a.asset_type == 'audio':
            entries = [{'download_address': raw.get('audio_address'), 'file_type': raw.get('audio_file_type', 'm4a')}]
        else:
            entries = []
        if not isinstance(entries, list):
            raise MeetingError('UPSTREAM_CONTRACT_ERROR', 502)
        for item in entries:
            if not isinstance(item, dict):
                continue
            extension = str(item.get('file_type', '')).lower().lstrip('.')
            address = item.get('download_address')
            if address and extension in MIME:
                self.http.check(address)
                return address, extension
        raise MeetingError('DOWNLOAD_NOT_ALLOWED', 403)

    async def issue(self, principal, asset_id, purpose):
        if not isinstance(purpose, str) or not 3 <= len(purpose.strip()) <= 128:
            raise MeetingError('INVALID_REQUEST', 422)
        p = await self.rt.auth.revalidate(principal)
        async with self.rt.db.session() as s:
            a, rec, m = await self._asset(s, p, asset_id)
        # Address is verified but deliberately never persisted in plaintext or returned.
        await self.native_address(p, a, rec)
        p = await self.rt.auth.revalidate(p)
        token = random_token('md_')
        now = utcnow()
        async with self.rt.db.transaction() as s:
            a, rec, m = await self._asset(s, p, asset_id)
            ticket = DownloadTicket(org_id=p.org_id, token_hash=digest(token), principal_binding=digest(p.binding),
                principal_data=p.model_dump(mode='json'), asset_id=a.id, asset_version=a.content_hash, purpose=purpose.strip(),
                expires_at=now+timedelta(seconds=self.rt.settings.download_start_seconds),
                session_expires_at=now+timedelta(seconds=self.rt.settings.download_session_seconds))
            s.add(ticket)
            await s.flush()
            record(s, p, 'download.ticket_created', resource_id=a.id)
            prefix = '/mcp/downloads/' if p.audience == self.rt.settings.mcp_resource_uri else '/api/v1/downloads/'
            return {'ticket': token, 'download_path': prefix+token, 'expires_at': ticket.expires_at,
                    'session_expires_at': ticket.session_expires_at, 'asset_id': a.id, 'asset_version': a.content_hash}

    async def validate(self, principal, token):
        if not isinstance(token, str) or len(token) > 256:
            raise MeetingError('DOWNLOAD_EXPIRED', 403)
        p = await self.rt.auth.revalidate(principal)
        async with self.rt.db.session() as s:
            if p.token_id:
                access = await s.get(AccessToken, p.token_id)
                if not access or access.expires_at <= utcnow():
                    raise MeetingError('TOKEN_INVALID', 401)
            row = await s.scalar(select(DownloadTicket).where(DownloadTicket.token_hash == digest(token),
                                                            DownloadTicket.deleted_at.is_(None)))
            if (not row or row.org_id != p.org_id or row.principal_binding != digest(p.binding) or row.revoked_at
                or row.session_expires_at <= utcnow() or (row.started_at is None and row.expires_at <= utcnow())):
                raise MeetingError('DOWNLOAD_EXPIRED', 403)
            a, rec, m = await self._asset(s, p, row.asset_id)
            if a.content_hash != row.asset_version:
                raise MeetingError('CONTENT_CHANGED', 409)
            return p, row, a

    async def charge(self, principal, size):
        if size < 0:
            raise MeetingError('INVALID_REQUEST', 422)
        day = utcnow().date().isoformat()
        key = principal.org_id + ':' + principal.client_id
        async with self.rt.db.lock('download-quota:' + key), self.rt.db.transaction() as s:
            q = await s.scalar(select(DownloadQuota).where(DownloadQuota.org_id == principal.org_id,
                DownloadQuota.client_id == principal.client_id, DownloadQuota.day == day,
                DownloadQuota.deleted_at.is_(None)))
            if q is None:
                q = DownloadQuota(org_id=principal.org_id, client_id=principal.client_id, day=day,
                                  reserved_bytes=0, completed_bytes=0)
                s.add(q)
            if q.completed_bytes + size > self.rt.settings.daily_download_bytes_per_client:
                raise MeetingError('RATE_LIMITED', 429)
            q.completed_bytes += size

    async def _acquire(self, p, ticket_id):
        async with self.rt.db.lock('download-stream:' + p.org_id + ':' + p.client_id), self.rt.db.transaction() as s:
            rows = list((await s.execute(select(DownloadTicket).where(DownloadTicket.org_id == p.org_id,
                DownloadTicket.deleted_at.is_(None), DownloadTicket.active_streams > 0))).scalars())
            cutoff = utcnow()-timedelta(seconds=90)
            active = 0
            for row in rows:
                if not row.stream_lease_at or row.stream_lease_at < cutoff:
                    row.active_streams = 0
                elif row.principal_data.get('client_id') == p.client_id:
                    active += row.active_streams
            row = await s.get(DownloadTicket, ticket_id, with_for_update=True)
            if row.active_streams or active >= self.rt.settings.max_download_concurrency:
                raise MeetingError('RATE_LIMITED', 429, retry_after=30)
            row.active_streams = 1
            row.stream_lease_at = utcnow()
            row.started_at = row.started_at or utcnow()
            record(s, p, 'download.started', resource_id=row.asset_id)

    async def heartbeat(self, ticket_id):
        async with self.rt.db.transaction() as s:
            row = await s.get(DownloadTicket, ticket_id, with_for_update=True)
            if row:
                row.stream_lease_at = utcnow()

    async def release(self, p, ticket_id, sent):
        async with self.rt.db.transaction() as s:
            row = await s.get(DownloadTicket, ticket_id, with_for_update=True)
            if row:
                row.active_streams = max(0, row.active_streams-1)
                row.bytes_sent += sent
                record(s, p, 'download.finished', resource_id=row.asset_id, details={'bytes': sent})

    async def open(self, principal, token, range_header=None):
        byte_range = self.parse_range(range_header)
        p, ticket, a = await self.validate(principal, token)
        async with self.rt.db.session() as s:
            a, rec, m = await self._asset(s, p, a.id)
        url, extension = await self.native_address(p, a, rec)
        p, ticket, a = await self.validate(p, token)
        await self._acquire(p, ticket.id)
        session, response = None, None
        try:
            session = self.http.session()
            headers = {'Accept-Encoding': 'identity'}
            if byte_range:
                headers['Range'] = byte_range
            response = await session.get(url, headers=headers, allow_redirects=False)
            if response.status not in {200, 206} or response.headers.get('Content-Encoding', 'identity') != 'identity':
                raise MeetingError('DOWNLOAD_NOT_ALLOWED', 403)
            expected = None
            if response.headers.get('Content-Length'):
                expected = int(response.headers['Content-Length'])
                if expected < 0 or expected > self.rt.settings.max_download_bytes:
                    raise MeetingError('DOWNLOAD_NOT_ALLOWED', 413)
            if byte_range:
                match = re.fullmatch(r'bytes ([0-9]+)-([0-9]+)/([0-9]+)', response.headers.get('Content-Range', ''))
                if response.status != 206 or not match:
                    raise MeetingError('UPSTREAM_CONTRACT_ERROR', 502)
                first, last, total = map(int, match.groups())
                wanted_first, wanted_last = byte_range[6:].split('-')
                if (last < first or last >= total or total > self.rt.settings.max_download_bytes
                    or (wanted_first and first != int(wanted_first))
                    or (wanted_first and wanted_last and last != min(int(wanted_last), total-1))
                    or (not wanted_first and first != max(0, total-int(wanted_last)))
                    or (expected is not None and expected != last-first+1)):
                    raise MeetingError('UPSTREAM_CONTRACT_ERROR', 502)
            elif response.status != 200:
                raise MeetingError('UPSTREAM_CONTRACT_ERROR', 502)
            await self.validate(p, token)
            return PreparedDownload(self, p, token, ticket.id, session, response, extension, expected)
        except BaseException:
            if response:
                response.close()
            if session:
                await session.close()
            await asyncio.shield(self.release(p, ticket.id, 0))
            raise
