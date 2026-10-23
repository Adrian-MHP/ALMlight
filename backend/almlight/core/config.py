"""Runtime configuration, read from environment variables prefixed with ``ALMLIGHT_``.

Nothing secret has a default here. The session signing key is either supplied via
``ALMLIGHT_SECRET_KEY`` or generated once and persisted in the data directory, so a
fresh installation is secure without manual key handling.
"""

from __future__ import annotations

import secrets
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ALMLIGHT_", env_file=None, extra="ignore")

    environment: str = "production"
    database_url: str = "postgresql+psycopg://almlight:almlight@db:5432/almlight"
    data_dir: Path = Path("/data")
    static_dir: Path | None = Path("/app/static")

    secret_key: str | None = None
    session_hours: int = 12
    cookie_secure: bool = False

    admin_username: str = "admin"
    admin_password: str | None = None
    demo_data: bool = False

    max_upload_mb: int = 100
    max_image_mb: int = 15

    # Live co-editing: a session is saved as a new item version when its last editor leaves (after a short
    # grace period, so a page reload does not create a version) or after this many idle seconds.
    collab_leave_grace_seconds: float = 8.0
    collab_idle_seconds: float = 300.0
    collab_draft_save_seconds: float = 2.0
    cors_origins: list[str] = Field(default_factory=list)
    log_level: str = "INFO"

    # Outbound webhooks and notification e-mails are delivered by an in-process worker; tests switch it off.
    outbox_worker: bool = True

    # Git repositories (Code page, linked revisions): mirrors are fetched by a background worker. Local paths
    # are accepted only below <data_dir>/repos-local unless explicitly allowed (they let the server read files).
    git_sync_minutes: float = 10.0
    git_allow_local_paths: bool = False
    git_max_commits: int = 5000
    git_timeout_seconds: int = 300

    # Public base URL (links in e-mails, single sign-on redirects), e.g. https://alm.example.com
    public_url: str | None = None
    # Notification e-mails (digest); disabled unless smtp_host and smtp_from are set
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_from: str | None = None
    smtp_security: str = "starttls"  # starttls | ssl | none
    email_digest_seconds: float = 60.0

    # Single sign-on (OpenID Connect, e.g. Microsoft Entra ID, Keycloak, Okta); local accounts keep working
    oidc_issuer: str | None = None
    oidc_client_id: str | None = None
    oidc_client_secret: str | None = None
    oidc_scopes: str = "openid profile email"
    oidc_label: str = "Single sign-on"
    oidc_username_claim: str = "preferred_username"
    oidc_admin_group: str | None = None  # members of this group (``groups`` claim) become administrators
    oidc_allow_signup: bool = True

    @property
    def files_dir(self) -> Path:
        return self.data_dir / "files"

    @property
    def repos_dir(self) -> Path:
        """Bare mirrors of connected Git repositories."""
        return self.data_dir / "vcs"

    @property
    def local_repos_dir(self) -> Path:
        """Local repositories that may be connected by path (demo data, on-premises file shares)."""
        return self.data_dir / "repos-local"

    def resolved_secret_key(self) -> str:
        if self.secret_key:
            return self.secret_key
        key_file = self.data_dir / "secret_key"
        if key_file.exists():
            return key_file.read_text().strip()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        key = secrets.token_urlsafe(48)
        key_file.write_text(key)
        key_file.chmod(0o600)
        return key


@lru_cache
def get_settings() -> Settings:
    return Settings()
