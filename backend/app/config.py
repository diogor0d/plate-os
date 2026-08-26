from functools import lru_cache
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL, make_url


class Settings(BaseSettings):
    """Environment-driven configuration. All vars are prefixed PLATEOS_."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="PLATEOS_",
        extra="ignore",
        secrets_dir="/run/secrets" if Path("/run/secrets").is_dir() else None,
    )

    environment: Literal["development", "test", "production"] = "development"

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

    @field_validator("default_user_timezone")
    @classmethod
    def validate_default_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("must be a valid IANA timezone") from exc
        return value

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

        if is_weak(self.app_password, 16):
            raise ValueError("app_password must be at least 16 characters and non-default")
        if is_weak(self.session_secret, 32):
            raise ValueError("session_secret must be at least 32 characters and high-entropy")
        if self.api_token is not None and is_weak(self.api_token, 32):
            raise ValueError("api_token must be at least 32 characters and high-entropy")
        if not self.cookie_secure:
            raise ValueError("cookie_secure must be true in production")

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
