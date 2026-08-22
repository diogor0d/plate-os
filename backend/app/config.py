from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-driven configuration. All vars are prefixed PLATEOS_."""

    model_config = SettingsConfigDict(env_file=".env", env_prefix="PLATEOS_", extra="ignore")

    database_url: str = "postgresql+asyncpg://plateos:plateos@localhost:5432/plateos"

    # OpenAI-compatible endpoint: swap between OpenAI, Gemini's compat layer,
    # or a local Ollama without code changes (see docs/decisions/2026-08-21).
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str | None = None
    llm_model: str = "gpt-4o-mini"

    openfoodfacts_base_url: str = "https://world.openfoodfacts.org/api/v2"

    # Single-user auth: one password, one signed HttpOnly cookie (decision D6).
    app_password: str = "changeme"
    session_secret: str = "changeme"
    # Set to true when served behind TLS (homelab reverse proxy).
    cookie_secure: bool = False

    # Optional static API token for external automation (Apple Shortcuts).
    # Grants full API access as the default user — treat like a password.
    api_token: str | None = None

    default_user_timezone: str = "Europe/Lisbon"

    # Placeholder anthropometrics for the seeded profile; editable via API.
    default_weight_kg: float = 75.0
    default_height_cm: float = 178.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
