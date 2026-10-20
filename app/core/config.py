"""Validated deployment configuration. No tenant Tencent secret is an environment default."""
import base64
import re
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import AliasChoices, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False, extra="ignore")
    environment: Literal["development", "test", "production"] = "production"
    database_url: str = "postgresql+asyncpg://meeting:CHANGE_ME@postgres:5432/meeting"
    identity_mode: Literal["account_login", "tencent_oauth"] = "tencent_oauth"
    account_login_url: str = ""
    meeting_component_id: str = ""
    meeting_org_id: str = ""
    meeting_bootstrap_admin_user_ids: list[str] = Field(default_factory=list)
    auth_session_ttl_seconds: int = Field(900, ge=60, le=3600)
    auth_admin_fresh_seconds: int = Field(300, ge=30, le=300)
    account_login_allow_private_http: bool = False
    tencent_meeting_auth_mode: Literal["oauth"] = "oauth"
    tencent_meeting_corp_id: str = ""
    tencent_meeting_app_id: str = ""
    tencent_meeting_app_secret: SecretStr = SecretStr("")
    tencent_meeting_allowed_open_corp_ids: list[str] = Field(default_factory=list)
    tencent_meeting_oauth_return_uris: list[str] = Field(default_factory=list)
    tencent_meeting_webhook_name: str = ""
    tencent_meeting_webhook_encoding_aes_key: SecretStr = Field(
        default=SecretStr(""),
        validation_alias=AliasChoices(
            "TENCENT_MEETING_WEBHOOK_ENCODING_AES_KEY",
            "TENCENT_MEETING_WEBHOOK_EncodingAESKey",
        ),
    )
    tencent_meeting_webhook_token: SecretStr = Field(
        default=SecretStr(""),
        validation_alias=AliasChoices("TENCENT_MEETING_WEBHOOK_TOKEN", "TENCENT_MEETING_WEBHOOK_Token"),
    )
    tencent_meeting_webhook_url: str = ""
    nodeskclaw_backend_url: str = ""
    backend_service_token: SecretStr = SecretStr("")
    metrics_token: SecretStr = SecretStr("")
    public_base_url: str = "https://meeting-gateway.example.invalid"
    portal_base_url: str = "https://console.example.invalid"
    rest_resource_uri: str = ""
    mcp_resource_uri: str = ""
    keyring_json: dict[str, str] = Field(default_factory=dict)
    active_key_id: str = "v1"
    allowed_hosts: list[str] = Field(default_factory=lambda: ["meeting-gateway.example.invalid"])
    cors_origins: list[str] = Field(default_factory=list)
    mcp_origins: list[str] = Field(default_factory=list)
    media_allowed_hosts: list[str] = Field(default_factory=list)
    notification_allowed_hosts: list[str] = Field(default_factory=list)
    notification_allowed_networks: list[str] = Field(default_factory=list)
    storage_path: Path = Path("storage/private")
    meeting_enabled: bool = True
    meeting_mcp_enabled: bool = False
    meeting_create_enabled: bool = False
    meeting_corp_sync_enabled: bool = False
    meeting_media_download_enabled: bool = False
    meeting_auto_record_enabled: bool = False
    access_token_seconds: int = Field(900, ge=60, le=3600)
    refresh_token_seconds: int = Field(604800, ge=60, le=604800)
    auth_code_seconds: int = Field(60, ge=15, le=120)
    upstream_state_seconds: int = Field(300, ge=60, le=600)
    confirmation_seconds: int = Field(600, ge=30, le=3600)
    download_start_seconds: int = Field(60, ge=15, le=300)
    download_session_seconds: int = Field(3600, ge=60, le=14400)
    source_health_seconds: int = Field(60, ge=0, le=300)
    max_request_bytes: int = Field(1048576, ge=1024, le=8388608)
    max_upstream_json_bytes: int = Field(16777216, ge=1024, le=67108864)
    max_download_bytes: int = Field(2147483648, ge=1024)
    max_download_concurrency: int = Field(4, ge=1, le=64)
    download_bytes_per_second: int = Field(8388608, ge=65536)
    daily_download_bytes_per_client: int = Field(10737418240, ge=1024)
    upstream_timeout_seconds: float = Field(20, ge=1, le=60)
    upstream_min_interval_seconds: float = Field(0.2, ge=0)
    corp_records_min_interval_seconds: float = Field(6.1, ge=0)
    worker_poll_seconds: float = Field(2, ge=0.05)
    worker_lease_seconds: int = Field(120, ge=30)
    job_max_attempts: int = Field(8, ge=1, le=20)
    transcript_page_size: int = Field(100, ge=2, le=1000)
    transcript_max_pages: int = Field(10000, ge=1)
    metadata_retention_days: int = Field(180, ge=1)
    content_retention_days: int = Field(30, ge=1)
    audit_retention_days: int = Field(180, ge=1)
    diagnostic_retention_days: int = Field(7, ge=1)
    maintenance_interval_seconds: int = Field(3600, ge=30)
    max_http_concurrency: int = Field(100, ge=1, le=1000)

    def fixed_oauth_callback_url(self) -> str:
        if not self.tencent_meeting_app_id:
            return ""
        return self.public_base_url.rstrip("/") + "/callbacks/tencent/oauth/" + self.tencent_meeting_app_id

    def fixed_webhook_callback_url(self) -> str:
        if not self.tencent_meeting_app_id:
            return ""
        return self.public_base_url.rstrip("/") + "/callbacks/tencent/events/" + self.tencent_meeting_app_id

    def tencent_webhook_complete(self) -> bool:
        return bool(
            self.tencent_meeting_app_id
            and self.tencent_meeting_corp_id
            and self.tencent_meeting_app_secret.get_secret_value()
            and self.tencent_meeting_webhook_name
            and self.tencent_meeting_webhook_encoding_aes_key.get_secret_value()
            and self.tencent_meeting_webhook_token.get_secret_value()
            and self.tencent_meeting_webhook_url
        )

    def _check_tencent_webhook(self):
        from app.integrations.tencent_meeting.webhook import _key

        if self.tencent_meeting_auth_mode != "oauth" or not self.tencent_meeting_app_id:
            raise ValueError("VALUE_REQUIRED")
        if not self.tencent_webhook_complete():
            raise ValueError("VALUE_REQUIRED")
        try:
            _key(self.tencent_meeting_webhook_encoding_aes_key.get_secret_value())
        except ValueError as exc:
            raise ValueError("VALUE_REQUIRED") from exc
        if self.tencent_meeting_webhook_url != self.fixed_webhook_callback_url():
            raise ValueError("VALUE_REQUIRED")

    def _check_login_url(self):
        if self.identity_mode == "tencent_oauth":
            if self.meeting_component_id and not re.fullmatch(r"[a-z][a-z0-9-]{2,63}", self.meeting_component_id):
                raise ValueError("IDENTITY_CONFIG_INVALID")
            return
        if not self.account_login_url:
            if self.environment == "production":
                raise ValueError("IDENTITY_CONFIG_INVALID")
            return
        parsed = urlsplit(self.account_login_url)
        if parsed.query or parsed.fragment or parsed.username or parsed.path != "/api/v1/auth/account-login":
            raise ValueError("IDENTITY_CONFIG_INVALID")
        if parsed.scheme == "http":
            if not self.account_login_allow_private_http:
                raise ValueError("IDENTITY_CONFIG_INVALID")
        elif parsed.scheme != "https":
            raise ValueError("IDENTITY_CONFIG_INVALID")
        if self.meeting_component_id and not re.fullmatch(r"[a-z][a-z0-9-]{2,63}", self.meeting_component_id):
            raise ValueError("IDENTITY_CONFIG_INVALID")

    @model_validator(mode="after")
    def validate_deployment(self):
        self.public_base_url = self.public_base_url.rstrip("/")
        self.portal_base_url = self.portal_base_url.rstrip("/")
        self.nodeskclaw_backend_url = self.nodeskclaw_backend_url.rstrip("/")
        self.rest_resource_uri = self.rest_resource_uri or self.public_base_url + "/api/v1"
        self.mcp_resource_uri = self.mcp_resource_uri or self.public_base_url + "/mcp"
        if self.rest_resource_uri == self.mcp_resource_uri:
            raise ValueError("REST and MCP audiences must differ")
        if self.nodeskclaw_backend_url or self.backend_service_token.get_secret_value():
            raise ValueError("LEGACY_IDENTITY_CONFIG_FORBIDDEN")
        if self.auth_admin_fresh_seconds > self.auth_session_ttl_seconds:
            raise ValueError("IDENTITY_CONFIG_INVALID")
        if self.environment == "test":
            self.meeting_component_id = self.meeting_component_id or "meeting-gateway"
            self.meeting_org_id = self.meeting_org_id or "o1"
            if not self.meeting_bootstrap_admin_user_ids:
                self.meeting_bootstrap_admin_user_ids = ["u-m1", "u1"]
            if self.identity_mode == "account_login" and not self.account_login_url:
                self.account_login_url = "http://127.0.0.1:9/api/v1/auth/account-login"
                self.account_login_allow_private_http = True
        self._check_login_url()
        if self.environment == "production":
            self._check_tencent_webhook()
            if not self.database_url.startswith("postgresql+asyncpg://"):
                raise ValueError("Production requires PostgreSQL asyncpg")
            required = [self.keyring_json, self.meeting_component_id, self.meeting_org_id]
            if self.identity_mode == "account_login":
                required.append(self.account_login_url)
            if not all(required):
                raise ValueError("IDENTITY_CONFIG_INVALID")
            if "CHANGE_ME" in self.database_url:
                raise ValueError("Replace bootstrap credentials")
            for url in [self.public_base_url, self.portal_base_url, self.rest_resource_uri, self.mcp_resource_uri]:
                parsed = urlsplit(url)
                if parsed.scheme != "https" or not parsed.hostname or parsed.hostname.endswith(".invalid"):
                    raise ValueError("Configure real HTTPS public URLs")
            if "*" in self.allowed_hosts or "*" in self.cors_origins or "*" in self.mcp_origins:
                raise ValueError("Production wildcard hosts/origins are forbidden")
        if self.keyring_json:
            if self.active_key_id not in self.keyring_json:
                raise ValueError("Active encryption key not found")
            for value in self.keyring_json.values():
                try:
                    raw = base64.urlsafe_b64decode(value)
                except Exception as exc:
                    raise ValueError("Encryption key must be base64") from exc
                if len(raw) != 32:
                    raise ValueError("Encryption key must be 32 bytes")
        return self
