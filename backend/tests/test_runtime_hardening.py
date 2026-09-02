import base64
from pathlib import Path
from typing import Any

import pytest
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from pydantic import ValidationError
from pydantic_settings import SettingsConfigDict
from py_vapid import Vapid

from app.config import Settings
from app.middleware import RequestBodyLimitMiddleware


def production_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "environment": "production",
        "database_url": "postgresql+asyncpg://plateos:J7vN2kQ9xR4mT8cW6pL3sD5f@db/plateos",
        "app_password": "Cedar-Maple-47-River",
        "session_secret": "J7vN2kQ9xR4mT8cW6pL3sD5fH1bA0zEu",
        "cookie_secure": True,
        "_env_file": None,
    }
    values.update(overrides)
    return Settings(**values)


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"app_password": "changeme"}, "app_password"),
        ({"session_secret": "too-short"}, "session_secret"),
        ({"session_secret": "s" * 32}, "session_secret"),
        ({"session_secret": "password" * 4}, "session_secret"),
        ({"session_secret": "Ab3!" * 8}, "session_secret"),
        ({"cookie_secure": False}, "cookie_secure"),
        (
            {"database_url": "postgresql+asyncpg://plateos:plateos@db/plateos"},
            "database credentials",
        ),
        (
            {"database_url": "postgresql://plateos:J7vN2kQ9xR4mT8cW6pL3sD5f@db/plateos"},
            "complete postgresql\\+asyncpg URL",
        ),
        ({"api_token": "too-short"}, "api_token"),
    ],
)
def test_production_settings_reject_unsafe_values(
    override: dict[str, object], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        production_settings(**override)


def test_production_settings_accept_strong_values() -> None:
    settings = production_settings()
    assert settings.environment == "production"
    assert settings.cookie_secure is True


def test_production_worker_requires_push_but_not_api_secrets() -> None:
    key = Fernet.generate_key().decode()
    vapid = Vapid()
    vapid.generate_keys()
    private_key = vapid.private_pem().decode()
    public_key = base64.urlsafe_b64encode(
        vapid.public_key.public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
    ).rstrip(b"=").decode()
    settings = production_settings(
        process_role="worker",
        app_password="changeme",
        session_secret="changeme",
        cookie_secure=False,
        web_push_public_key=public_key,
        web_push_private_key=private_key,
        web_push_subscription_key=key,
        web_push_vapid_subject="mailto:operator@example.test",
    )
    assert settings.process_role == "worker"

    with pytest.raises(ValidationError, match="requires all Web Push settings"):
        production_settings(
            process_role="worker",
            app_password="changeme",
            session_secret="changeme",
            cookie_secure=False,
        )


def test_push_settings_reject_partial_or_invalid_storage_keys() -> None:
    with pytest.raises(ValidationError, match="configured together"):
        Settings(web_push_public_key="public-key", _env_file=None)
    with pytest.raises(ValidationError, match="valid Fernet key"):
        Settings(
            web_push_public_key="public-key",
            web_push_subscription_key="not-a-fernet-key",
            _env_file=None,
        )
    with pytest.raises(ValidationError, match="exceed the request timeout"):
        Settings(web_push_lease_seconds=15, web_push_request_timeout_seconds=15, _env_file=None)


def test_production_settings_load_prefixed_secret_files(tmp_path: Path) -> None:
    class SecretSettings(Settings):
        model_config = SettingsConfigDict(
            env_prefix="PLATEOS_", secrets_dir=tmp_path, extra="ignore"
        )

    (tmp_path / "plateos_database_password").write_text(
        "J7vN2kQ9xR4mT8cW6pL3sD5f\n", encoding="utf-8"
    )
    (tmp_path / "plateos_app_password").write_text(
        "Cedar-Maple-47-River\n", encoding="utf-8"
    )
    (tmp_path / "plateos_session_secret").write_text(
        "J7vN2kQ9xR4mT8cW6pL3sD5fH1bA0zEu", encoding="utf-8"
    )

    settings = SecretSettings(
        environment="production",
        database_host="db",
        cookie_secure=True,
        _env_file=None,
    )
    assert settings.app_password == "Cedar-Maple-47-River"
    assert "J7vN2kQ9xR4mT8cW6pL3sD5f" in (settings.database_url or "")


def test_request_body_limit_rejects_before_route_parsing() -> None:
    app = FastAPI()
    app.add_middleware(RequestBodyLimitMiddleware, max_bytes=10)

    @app.post("/echo")
    async def echo(request: Request) -> dict[str, int]:
        return {"bytes": len(await request.body())}

    with TestClient(app) as client:
        accepted = client.post("/echo", content=b"1234567890")
        rejected = client.post("/echo", content=b"12345678901")

    assert accepted.status_code == 200
    assert accepted.json() == {"bytes": 10}
    assert rejected.status_code == 413
    assert rejected.json() == {"detail": "Request body too large"}


class FakeReadinessSession:
    def __init__(self, profile_count: int) -> None:
        self.profile_count = profile_count
        self.calls = 0

    async def __aenter__(self) -> "FakeReadinessSession":
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def scalar(self, _query: object) -> int | None:
        self.calls += 1
        return self.profile_count if self.calls == 1 else None


@pytest.mark.asyncio
async def test_readiness_checks_database_schema_and_single_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import main as main_module

    session = FakeReadinessSession(profile_count=1)
    monkeypatch.setattr(main_module, "SessionLocal", lambda: session)

    assert await main_module.ready() == {"status": "ready"}
    assert session.calls == 7


@pytest.mark.asyncio
async def test_readiness_rejects_invalid_profile_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import main as main_module

    session = FakeReadinessSession(profile_count=0)
    monkeypatch.setattr(main_module, "SessionLocal", lambda: session)

    response: Any = await main_module.ready()
    assert response.status_code == 503
    assert response.body == b'{"status":"not_ready"}'


@pytest.mark.asyncio
async def test_readiness_rejects_database_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import main as main_module

    class BrokenSession:
        async def __aenter__(self) -> None:
            raise OSError("database unavailable")

        async def __aexit__(self, *_args: object) -> None:
            return None

    monkeypatch.setattr(main_module, "SessionLocal", BrokenSession)

    response: Any = await main_module.ready()
    assert response.status_code == 503
    assert response.body == b'{"status":"not_ready"}'
