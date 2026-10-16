"""Validated deployment configuration. No tenant Tencent secret is an environment default."""
import base64
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False, extra="ignore")
    environment: Literal["development", "test", "production"] = "production"
    database_url: str = "postgresql+asyncpg://meeting:CHANGE_ME@postgres:5432/meeting"
    nodeskclaw_backend_url: str = "http://nodeskclaw-backend:8000"
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

    @model_validator(mode="after")
    def validate_deployment(self):
        self.public_base_url = self.public_base_url.rstrip("/")
        self.portal_base_url = self.portal_base_url.rstrip("/")
        self.nodeskclaw_backend_url = self.nodeskclaw_backend_url.rstrip("/")
        self.rest_resource_uri = self.rest_resource_uri or self.public_base_url + "/api/v1"
        self.mcp_resource_uri = self.mcp_resource_uri or self.public_base_url + "/mcp"
        if self.rest_resource_uri == self.mcp_resource_uri:
            raise ValueError("REST and MCP audiences must differ")
        if self.environment == "production":
            if not self.database_url.startswith("postgresql+asyncpg://"):
                raise ValueError("Production requires PostgreSQL asyncpg")
            if not self.keyring_json or not self.backend_service_token.get_secret_value():
                raise ValueError("Production encryption keys and Backend service credential are required")
            if "CHANGE_ME" in self.database_url or len(self.backend_service_token.get_secret_value()) < 32:
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
