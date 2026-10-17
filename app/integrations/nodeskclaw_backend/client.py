"""Account-login only. Context, resolve, search and upstream health are not called."""
import json
from urllib.parse import urlsplit
import httpx
from app.core.errors import MeetingError

ALLOWED_PATH = "/api/v1/auth/account-login"
FORBIDDEN_MARKERS = (
    "/auth/meeting-context",
    "/principals/resolve",
    "/principals/search",
    "/auth/me",
    "/auth/refresh",
)


class AccountLoginClient:
    def __init__(self, settings, *, http_client=None):
        self.url = settings.account_login_url
        self.http = http_client or httpx.AsyncClient(timeout=10, follow_redirects=False, trust_env=False)

    def assert_target(self, url: str):
        if url != self.url:
            raise MeetingError("IDENTITY_EGRESS_FORBIDDEN", 503)
        parsed = urlsplit(url)
        if parsed.query or parsed.fragment or parsed.username or parsed.path != ALLOWED_PATH:
            raise MeetingError("IDENTITY_EGRESS_FORBIDDEN", 503)
        lowered = url.lower()
        if any(marker in lowered for marker in FORBIDDEN_MARKERS):
            raise MeetingError("IDENTITY_EGRESS_FORBIDDEN", 503)

    async def login(self, account: str, password: str) -> dict:
        self.assert_target(self.url)
        try:
            response = await self.http.post(self.url, json={"account": account, "password": password})
        except httpx.HTTPError as exc:
            raise MeetingError("ACCOUNT_LOGIN_UNAVAILABLE", 503) from exc
        if response.status_code in {301, 302, 303, 307, 308}:
            raise MeetingError("ACCOUNT_LOGIN_CONTRACT_ERROR", 502)
        if response.status_code in {401, 403}:
            raise MeetingError("ACCOUNT_LOGIN_REJECTED", 401)
        if response.status_code == 429 or response.status_code >= 500:
            raise MeetingError("ACCOUNT_LOGIN_UNAVAILABLE", 503)
        if response.status_code != 200:
            raise MeetingError("ACCOUNT_LOGIN_CONTRACT_ERROR", 502)
        raw = response.content
        if len(raw) > 262144:
            raise MeetingError("ACCOUNT_LOGIN_CONTRACT_ERROR", 502)
        try:
            payload = json.loads(raw.decode("utf-8"), object_pairs_hook=_no_duplicates)
        except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
            raise MeetingError("ACCOUNT_LOGIN_CONTRACT_ERROR", 502) from exc
        return payload

    async def close(self):
        await self.http.aclose()


def _no_duplicates(pairs):
    seen = set()
    out = {}
    for key, value in pairs:
        if key in seen:
            raise ValueError("duplicate")
        seen.add(key)
        out[key] = value
    return out
