import base64
from functools import lru_cache
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from py_vapid import Vapid
from sqlalchemy.engine import URL, make_url


def parse_vapid_private_key(value: str) -> Vapid:
    if "-----BEGIN" in value:
        return Vapid.from_pem(value.encode("utf-8"))
    return Vapid.from_string(value)


class Settings(BaseSettings):
    """Environment-driven configuration. All vars are prefixed PLATEOS_."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="PLATEOS_",
        extra="ignore",
        secrets_dir="/run/secrets" if Path("/run/secrets").is_dir() else None,
    )

    environment: Literal["development", "test", "production"] = "development"
    process_role: Literal["api", "worker"] = "api"

    # A direct URL remains supported for workstation development. Production
    # Compose passes the non-secret connection fields and injects the password
    # from /run/secrets/plateos_database_password.
    database_url: str | None = None
    database_host: str = "localhost"
    database_port: int = Field(default=5432, ge=1, le=65535)
    database_user: str = "plateos"
    database_password: str | None = None
    database_name: str = "plateos"

    # OpenAI-compatible endpoint: swap between OpenAI, Gemini's compat layer,
    # or a local Ollama without code changes (see docs/decisions/2026-08-21).
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str | None = None
    llm_model: str = "gpt-4o-mini"

    openfoodfacts_base_url: str = "https://world.openfoodfacts.org/api/v2"

    # Single-user auth: one password, one signed HttpOnly cookie (decision D6).
    app_password: str = "changeme"
    session_secret: str = "changeme"
    # Username for the bootstrap admin account (decision D36).
    admin_username: str = "admin"
    # Set to true when served behind TLS (homelab reverse proxy).
    cookie_secure: bool = False

    # Optional static API token for external automation (Apple Shortcuts).
    # Grants full API access as the default user — treat like a password.
    api_token: str | None = None

    default_user_timezone: str = "Europe/Lisbon"

    # Placeholder anthropometrics for the seeded profile; editable via API.
    default_weight_kg: float = 75.0
    default_height_cm: float = 178.0

    max_request_body_bytes: int = Field(default=2_000_000, ge=1024, le=20_000_000)

    # JSON file holding Settings-screen overrides (providers/models/OFF URL).
    # Must live on a writable volume in containers; never inside the database.
    runtime_settings_file: str = "data/runtime-settings.json"

    # Web Push key material is file-injected in production. The private VAPID
    # key is worker-only; the API needs only the public and storage keys.
    web_push_public_key: str | None = None
    web_push_private_key: SecretStr | None = None
    web_push_subscription_key: SecretStr | None = None
    web_push_vapid_subject: str | None = None
    web_push_poll_seconds: float = Field(default=15.0, ge=1.0, le=300.0)
    web_push_batch_size: int = Field(default=25, ge=1, le=100)
    web_push_lease_seconds: int = Field(default=60, ge=15, le=600)
    web_push_request_timeout_seconds: float = Field(default=15.0, ge=1.0, le=45.0)
    web_push_max_attempts: int = Field(default=5, ge=1, le=10)
    web_push_retry_base_seconds: int = Field(default=30, ge=1, le=3600)
    web_push_retry_max_seconds: int = Field(default=3600, ge=1, le=86400)

    @property
    def web_push_api_enabled(self) -> bool:
        return self.web_push_public_key is not None and self.web_push_subscription_key is not None

    @property
    def web_push_private_key_value(self) -> str | None:
        return self.web_push_private_key.get_secret_value() if self.web_push_private_key else None

    @property
    def web_push_subscription_key_value(self) -> str | None:
        return (
            self.web_push_subscription_key.get_secret_value()
            if self.web_push_subscription_key
            else None
        )

    @field_validator("default_user_timezone")
    @classmethod
    def validate_default_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("must be a valid IANA timezone") from exc
        return value

    @field_validator("web_push_vapid_subject")
    @classmethod
    def validate_vapid_subject(cls, value: str | None) -> str | None:
        if value == "":
            return None
        if value is not None and not (value.startswith("mailto:") or value.startswith("https://")):
            raise ValueError("must be a mailto: or https:// URI")
        return value

    @field_validator(
        "web_push_public_key",
        "web_push_private_key",
        "web_push_subscription_key",
        mode="before",
    )
    @classmethod
    def empty_push_secret_is_unset(cls, value: object) -> object:
        return None if value == "" else value

    @model_validator(mode="after")
    def resolve_and_validate_runtime(self) -> "Settings":
        if self.database_url is None:
            password = self.database_password
            if password is None and self.environment != "production":
                password = "plateos"
            if password is None:
                raise ValueError("database_password is required in production")
            self.database_url = URL.create(
                "postgresql+asyncpg",
                username=self.database_user,
                password=password,
                host=self.database_host,
                port=self.database_port,
                database=self.database_name,
            ).render_as_string(hide_password=False)

        push_values = (self.web_push_public_key, self.web_push_subscription_key)
        if any(push_values) and not all(push_values):
            raise ValueError("web_push_public_key and web_push_subscription_key must be configured together")
        if self.web_push_subscription_key is not None:
            try:
                Fernet(self.web_push_subscription_key.get_secret_value().encode("ascii"))
            except (ValueError, TypeError) as exc:
                raise ValueError("web_push_subscription_key must be a valid Fernet key") from exc
        if self.web_push_retry_base_seconds > self.web_push_retry_max_seconds:
            raise ValueError("web_push_retry_base_seconds cannot exceed web_push_retry_max_seconds")
        if self.web_push_lease_seconds < self.web_push_request_timeout_seconds + 5:
            raise ValueError("web_push_lease_seconds must exceed the request timeout by at least 5 seconds")

        if self.environment != "production":
            return self

        weak_values = {
            "",
            "changeme",
            "password",
            "plateos",
            "generate-a-long-random-string",
        }
        weak_fragments = ("changeme", "letmein", "password", "plateos", "qwerty")

        def is_periodic(secret: str) -> bool:
            return any(
                len(secret) % period == 0
                and secret == secret[:period] * (len(secret) // period)
                for period in range(1, len(secret) // 2 + 1)
            )

        def is_weak(secret: str, minimum_length: int) -> bool:
            normalized = secret.strip().lower()
            return (
                len(secret) < minimum_length
                or normalized in weak_values
                or any(fragment in normalized for fragment in weak_fragments)
                or len(set(secret)) < 4
                or is_periodic(secret)
            )

        if self.process_role == "api":
            if is_weak(self.app_password, 16):
                raise ValueError("app_password must be at least 16 characters and non-default")
            if is_weak(self.session_secret, 32):
                raise ValueError("session_secret must be at least 32 characters and high-entropy")
            if self.api_token is not None and is_weak(self.api_token, 32):
                raise ValueError("api_token must be at least 32 characters and high-entropy")
            if not self.cookie_secure:
                raise ValueError("cookie_secure must be true in production")
        elif not all(
            (
                self.web_push_public_key,
                self.web_push_private_key,
                self.web_push_subscription_key,
                self.web_push_vapid_subject,
            )
        ):
            raise ValueError("production Web Push worker requires all Web Push settings")
        elif self.web_push_private_key is not None and self.web_push_public_key is not None:
            try:
                vapid = parse_vapid_private_key(self.web_push_private_key.get_secret_value())
                derived_public = base64.urlsafe_b64encode(
                    vapid.public_key.public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
                ).rstrip(b"=").decode("ascii")
            except Exception as exc:  # py-vapid wraps backend-specific key errors
                raise ValueError("web_push_private_key must be a valid VAPID PEM or URL-safe key") from exc
            if derived_public != self.web_push_public_key:
                raise ValueError("Web Push VAPID public and private keys do not match")

        database = make_url(self.database_url)
        if (
            database.drivername != "postgresql+asyncpg"
            or not database.host
            or not database.username
            or not database.database
        ):
            raise ValueError("database_url must be a complete postgresql+asyncpg URL")
        if database.password is None or is_weak(database.password, 24):
            raise ValueError("database credentials must be non-default in production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
