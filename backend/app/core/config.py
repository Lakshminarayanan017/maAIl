"""Settings. One source, validated at import, loud on anything missing.

Two database URLs, deliberately:

``app_database_url``    the non-owner role the application uses. Subject to RLS.
``owner_database_url``  the owner role. Migrations and ``db.sh`` only.

Nothing on a request path may use the owner URL. ``tests/arch`` enforces it.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, computed_field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["development", "test", "production"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        env_prefix="",
        extra="ignore",
        case_sensitive=False,
    )

    env: Environment = Field(default="development", alias="MAAIL_ENV")
    log_level: str = Field(default="INFO", alias="MAAIL_LOG_LEVEL")

    # --- database ---------------------------------------------------------
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "maail"

    postgres_app_user: str = "maail_app"
    postgres_app_password: SecretStr = SecretStr("change_me_app")

    postgres_owner_user: str = "maail_owner"
    postgres_owner_password: SecretStr = SecretStr("change_me_owner")

    # --- http -------------------------------------------------------------
    session_secret: SecretStr = SecretStr("change_me_to_32_bytes_minimum_abcdef")
    cors_origins: str = "http://localhost:5173"
    #: Where the browser app lives. OAuth callbacks redirect back here.
    web_base_url: str = "http://localhost:5173"
    session_ttl_days: int = 14

    # --- credential encryption (gap D8) ------------------------------------
    #: ``<version>:<base64 32-byte key>``, comma separated. Every version
    #: stays loaded so rows encrypted under an old one remain readable while
    #: they are re-wrapped.
    data_encryption_keys: str = ""
    data_encryption_key_version: int = 1

    # --- google oauth ------------------------------------------------------
    google_client_id: str = ""
    google_client_secret: SecretStr = SecretStr("")
    google_redirect_uri: str = "http://localhost:8000/api/v1/auth/google/callback"
    #: While the OAuth app is in Testing, Google expires a test user's refresh
    #: token after about seven days (gap A3). v1 accepts that and designs for
    #: it, so the expiry is predicted rather than discovered when sync fails.
    google_oauth_testing_mode: bool = True
    google_testing_refresh_ttl_days: int = 7

    # --- engine -----------------------------------------------------------
    db_pool_size: int = 10
    db_max_overflow: int = 5
    db_statement_timeout_ms: int = 15_000
    sql_echo: bool = False

    @field_validator("log_level")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.upper()

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_production(self) -> bool:
        return self.env == "production"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def google_oauth_configured(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret.get_secret_value())

    @computed_field  # type: ignore[prop-decorator]
    @property
    def cookie_secure(self) -> bool:
        """Secure cookies everywhere but plain-HTTP local development."""
        return self.is_production or self.web_base_url.startswith("https://")

    def _url(self, user: str, password: SecretStr, driver: str) -> str:
        return (
            f"postgresql+{driver}://{user}:{password.get_secret_value()}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def app_database_url(self) -> str:
        """The application's own role. Non-owner, so RLS cannot be escaped."""
        return self._url(self.postgres_app_user, self.postgres_app_password, "asyncpg")

    @property
    def owner_database_url(self) -> str:
        """Schema owner. Migrations and maintenance only — never a request."""
        return self._url(self.postgres_owner_user, self.postgres_owner_password, "asyncpg")

    def assert_production_ready(self) -> None:
        """Fail at startup rather than serve with a placeholder secret."""
        if not self.is_production:
            return
        placeholders = {
            "SESSION_SECRET": self.session_secret.get_secret_value(),
            "POSTGRES_APP_PASSWORD": self.postgres_app_password.get_secret_value(),
            "POSTGRES_OWNER_PASSWORD": self.postgres_owner_password.get_secret_value(),
        }
        bad = [name for name, value in placeholders.items() if value.startswith("change_me")]
        if bad:
            raise RuntimeError(f"Placeholder secrets in production: {', '.join(sorted(bad))}")
        if len(self.session_secret.get_secret_value()) < 32:
            raise RuntimeError("SESSION_SECRET must be at least 32 characters")
        if not self.data_encryption_keys:
            raise RuntimeError("DATA_ENCRYPTION_KEYS is required; credentials are stored sealed")
        if not self.google_oauth_configured:
            raise RuntimeError("GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET are required")
        if not self.google_redirect_uri.startswith("https://"):
            raise RuntimeError("GOOGLE_REDIRECT_URI must be https in production")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
