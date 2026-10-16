"""Backend identity adapter: actual identity, no local JWT signing secret."""
import httpx
from pydantic import ValidationError
from app.core.types import MemberContext
from app.core.errors import MeetingError


class BackendClient:
    def __init__(self, base_url: str, service_token: str, *, http_client=None):
        self.base_url = base_url.rstrip("/")
        self.service_token = service_token
        self.http = http_client or httpx.AsyncClient(timeout=10, follow_redirects=False, trust_env=False)

    async def _request(self, method: str, path: str, *, token: str, body=None):
        try:
            response = await self.http.request(method, self.base_url + path,
                headers={"Authorization": "Bearer " + token}, json=body)
        except httpx.HTTPError as exc:
            raise MeetingError("IDENTITY_SERVICE_UNAVAILABLE", 503) from exc
        if response.status_code in {401, 403}:
            raise MeetingError("MEMBER_INACTIVE" if response.status_code == 403 else "TOKEN_INVALID", response.status_code)
        if response.status_code != 200:
            raise MeetingError("IDENTITY_SERVICE_UNAVAILABLE", 503)
        try:
            data = response.json()
            if data.get("code", 0) != 0:
                raise ValueError("Backend rejected context")
            return data["data"]
        except (ValueError, KeyError, TypeError) as exc:
            raise MeetingError("IDENTITY_SERVICE_UNAVAILABLE", 503) from exc

    @staticmethod
    def _context(value):
        try:
            member = MemberContext.model_validate(value)
        except ValidationError as exc:
            raise MeetingError("IDENTITY_SERVICE_UNAVAILABLE", 503) from exc
        if not member.is_active or member.must_change_password:
            raise MeetingError("MEMBER_INACTIVE", 403)
        return member

    async def context(self, token: str) -> MemberContext:
        return self._context(await self._request("GET", "/api/v1/auth/meeting-context", token=token))

    async def resolve(self, org_id: str, member_id: str) -> MemberContext:
        value = await self._request("POST", "/api/v1/internal/meeting/principals/resolve",
            token=self.service_token, body={"org_id": org_id, "member_ids": [member_id]})
        rows = value.get("principals", []) if isinstance(value, dict) else []
        matches = [row for row in rows if row.get("member_id") == member_id and row.get("org_id") == org_id]
        if len(matches) != 1:
            raise MeetingError("MEMBER_INACTIVE", 403)
        return self._context(matches[0])

    async def search(self, org_id: str, query: str):
        value = await self._request("POST", "/api/v1/internal/meeting/principals/search", token=self.service_token,
                                    body={"org_id": org_id, "query": query, "limit": 30})
        return value.get("principals", [])

    async def ready(self):
        try:
            response = await self.http.get(self.base_url + "/health", timeout=3)
            return response.status_code == 200
        except httpx.HTTPError:
            return False

    async def close(self):
        await self.http.aclose()
