"""Application-owned dependencies; lazy services keep domain modules independently testable."""
from collections import Counter
from functools import cached_property
import httpx
from app.core.database import Database
from app.core.security import KeyRing, CursorCodec
from app.integrations.nodeskclaw_backend.client import AccountLoginClient
from app.storage.local import LocalEncryptedStorage


class Runtime:
    def __init__(self, settings, *, backend=None, provider=None, upstream_http=None):
        self.settings = settings
        self.db = Database(settings.database_url, allow_sqlite=settings.environment in {"test", "development"})
        self.keys = KeyRing(settings.keyring_json, settings.active_key_id)
        self.cursors = CursorCodec(self.keys.purpose_key("cursor"))
        self.accounts = AccountLoginClient(settings)
        self.backend = backend
        self.upstream_http = upstream_http or httpx.AsyncClient(timeout=settings.upstream_timeout_seconds,
                                                               follow_redirects=False, trust_env=False)
        self._provider = provider
        self.storage = LocalEncryptedStorage(settings.storage_path, self.keys)
        self.metrics = Counter()

    @cached_property
    def policy(self):
        from app.services.permission_service import PermissionService
        return PermissionService(self)
    @cached_property
    def identity(self):
        from app.services.identity_service import IdentityService
        return IdentityService(self)
    @cached_property
    def auth(self):
        from app.services.auth_service import AuthService
        return AuthService(self)
    @cached_property
    def admin(self):
        from app.services.admin_service import AdminService
        return AdminService(self)
    @cached_property
    def tencent(self):
        if self._provider is not None:
            return self._provider
        from app.integrations.tencent_meeting.client import TencentClient
        return TencentClient(self)
    @cached_property
    def connections(self):
        from app.services.connection_service import ConnectionService
        return ConnectionService(self)
    @cached_property
    def meetings(self):
        from app.services.meeting_service import MeetingService
        return MeetingService(self)
    @cached_property
    def queries(self):
        from app.services.query_service import QueryService
        return QueryService(self)
    @cached_property
    def content(self):
        from app.services.content_service import ContentService
        return ContentService(self)
    @cached_property
    def operations(self):
        from app.services.operation_service import OperationService
        return OperationService(self)
    @cached_property
    def jobs(self):
        from app.services.job_service import JobService
        return JobService(self)
    @cached_property
    def sync(self):
        from app.services.sync_service import SyncService
        return SyncService(self)
    @cached_property
    def downloads(self):
        from app.services.download_service import DownloadService
        return DownloadService(self)
    @cached_property
    def events(self):
        from app.services.event_service import EventService
        return EventService(self)
    @cached_property
    def rate(self):
        from app.services.rate_service import RateService
        return RateService(self)

    async def close(self):
        await self.upstream_http.aclose()
        await self.accounts.close()
        if self.backend is not None:
            await self.backend.close()
        await self.db.close()
