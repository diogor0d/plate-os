import base64
import socket
import uuid
from datetime import UTC, datetime
from ipaddress import ip_address
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from pydantic import ValidationError
from pywebpush import WebPushException
from py_vapid import Vapid
from sqlalchemy.dialects import postgresql

from app.api.deps import get_cookie_profile
from app.api.routes import push as push_routes
from app.config import Settings
from app.models import PushSubscription
from app.schemas.push import PushSubscriptionCreate, PushSubscriptionDelete
from app.services import web_push


def subscription() -> PushSubscriptionCreate:
    return PushSubscriptionCreate(
        endpoint="https://push.example.com/send/device-1",
        expiration_time=None,
        keys={"p256dh": "public-client-key", "auth": "auth-secret"},
        device_name="Phone",
    )


def worker_settings(key: str, **overrides: object) -> Settings:
    vapid = Vapid()
    vapid.generate_keys()
    values: dict[str, object] = {
        "environment": "test",
        "process_role": "worker",
        "web_push_public_key": base64.urlsafe_b64encode(
            vapid.public_key.public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
        ).rstrip(b"=").decode(),
        "web_push_private_key": vapid.private_pem().decode(),
        "web_push_subscription_key": key,
        "web_push_vapid_subject": "mailto:operator@example.test",
        "_env_file": None,
    }
    values.update(overrides)
    return Settings(**values)


def test_subscription_encryption_round_trip_hides_endpoint() -> None:
    key = Fernet.generate_key().decode()
    body = subscription()
    encrypted = web_push.encrypt_subscription(body, key)

    assert b"push.example.com" not in encrypted
    assert web_push.decrypt_subscription(encrypted, key) == body.model_dump(
        mode="json", exclude={"device_name"}
    )
    with pytest.raises(web_push.PushError, match="cannot be decrypted"):
        web_push.decrypt_subscription(encrypted, Fernet.generate_key().decode())


class ScalarSession:
    def __init__(self, value: object) -> None:
        self.value = value

    async def scalar(self, _statement: object) -> object:
        return self.value


@pytest.mark.asyncio
async def test_upsert_cannot_transfer_another_users_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def public_endpoint(_endpoint: str) -> tuple[str, list]:
        return "push.example.com", [ip_address("8.8.8.8")]

    monkeypatch.setattr(web_push, "resolve_public_endpoint", public_endpoint)
    owner_id = uuid.uuid4()
    existing = PushSubscription(
        id=uuid.uuid4(),
        user_id=owner_id,
        endpoint_fingerprint=web_push.endpoint_fingerprint(str(subscription().endpoint)),
        encrypted_subscription=b"ciphertext",
    )
    with pytest.raises(web_push.PushError, match="already registered") as caught:
        await web_push.upsert_subscription(
            ScalarSession(existing),  # type: ignore[arg-type]
            uuid.uuid4(),
            subscription(),
            Fernet.generate_key().decode(),
        )
    assert caught.value.status_code == 409


class Result:
    def __init__(self, *, rows: list[tuple] | None = None, rowcount: int = 1) -> None:
        self._rows = rows or []
        self.rowcount = rowcount

    def all(self) -> list[tuple]:
        return self._rows


class ScalarResult(Result):
    def scalars(self) -> "ScalarResult":
        return self

    def __iter__(self):
        return iter(row[0] for row in self._rows)


class CapturingSession:
    def __init__(self, results: list[Result]) -> None:
        self.results = iter(results)
        self.statements: list[object] = []
        self.commits = 0

    async def execute(self, statement: object) -> Result:
        self.statements.append(statement)
        return next(self.results)

    async def commit(self) -> None:
        self.commits += 1


@pytest.mark.asyncio
async def test_unsubscribe_update_is_user_scoped() -> None:
    user_id = uuid.uuid4()
    session = CapturingSession([Result(rowcount=0)])
    with pytest.raises(web_push.PushError, match="not found"):
        await web_push.unsubscribe(
            session,  # type: ignore[arg-type]
            user_id,
            "https://push.example.com/send/device-1",
        )
    compiled = session.statements[0].compile(dialect=postgresql.dialect())
    assert "push_subscriptions.user_id" in str(compiled)
    assert user_id in compiled.params.values()
    assert session.commits == 0


@pytest.mark.asyncio
async def test_claim_uses_skip_locked_and_recovers_only_expired_leases() -> None:
    session = CapturingSession([Result(), Result(rows=[])])
    now = datetime(2026, 9, 2, 12, tzinfo=UTC)
    claims = await web_push.claim_deliveries(
        session,  # type: ignore[arg-type]
        now=now,
        limit=10,
        lease_seconds=60,
        max_attempts=5,
    )
    sql = str(session.statements[1].compile(dialect=postgresql.dialect()))
    assert claims == []
    assert "FOR UPDATE OF web_push_deliveries SKIP LOCKED" in sql
    assert "web_push_deliveries.leased_until <=" in sql
    assert "lease_token=" in sql
    assert "push_subscriptions.disabled_at IS NULL" in sql
    stale_sql = str(session.statements[0].compile(dialect=postgresql.dialect()))
    assert "attempt_count >=" in stale_sql
    assert "lease_expired" in session.statements[0].compile(
        dialect=postgresql.dialect()
    ).params.values()


@pytest.mark.asyncio
async def test_materialization_is_idempotent_at_database_boundary() -> None:
    session = CapturingSession(
        [Result(rowcount=1), Result(), Result(rowcount=0), Result()]
    )
    now = datetime(2026, 9, 2, 12, tzinfo=UTC)
    assert await web_push.materialize_due_deliveries(
        session,  # type: ignore[arg-type]
        now=now,
        limit=10,
    ) == 1
    assert await web_push.materialize_due_deliveries(
        session,  # type: ignore[arg-type]
        now=now,
        limit=10,
    ) == 0
    insert_sql = str(session.statements[0].compile(dialect=postgresql.dialect()))
    assert "ON CONFLICT (intent_id, subscription_id) DO NOTHING" in insert_sql


@pytest.mark.asyncio
async def test_materialization_limits_only_missing_active_subscription_pairs() -> None:
    session = CapturingSession([Result(rowcount=10), Result()])
    now = datetime(2026, 9, 2, 12, tzinfo=UTC)
    assert await web_push.materialize_due_deliveries(
        session,  # type: ignore[arg-type]
        now=now,
        limit=10,
    ) == 10

    sql = str(session.statements[0].compile(dialect=postgresql.dialect()))
    assert "candidate_delivery_pairs" in sql
    assert "JOIN push_subscriptions" in sql
    assert "push_subscriptions.disabled_at IS NULL" in sql
    assert "NOT (EXISTS (SELECT *" in sql
    assert "web_push_deliveries.intent_id = notification_intents.id" in sql
    assert "web_push_deliveries.subscription_id = push_subscriptions.id" in sql
    assert "FOR UPDATE OF notification_intents SKIP LOCKED" in sql
    # Both filters precede LIMIT inside the CTE: any number of earlier intents
    # with no subscription or with existing deliveries cannot consume the batch.
    assert sql.index("NOT (EXISTS") < sql.index("LIMIT")
    assert 10 in session.statements[0].compile(dialect=postgresql.dialect()).params.values()


def claim(key: str, attempt_count: int = 1) -> web_push.DeliveryClaim:
    return web_push.DeliveryClaim(
        intent_id=uuid.uuid4(),
        subscription_id=uuid.uuid4(),
        lease_token=uuid.uuid4(),
        attempt_count=attempt_count,
        encrypted_subscription=web_push.encrypt_subscription(subscription(), key),
    )


@pytest.mark.asyncio
async def test_delivery_acceptance_is_token_guarded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key = Fernet.generate_key().decode()

    async def accepted(**_kwargs: object) -> object:
        return SimpleNamespace(status=201)

    async def public_endpoint(_endpoint: str) -> tuple[str, list]:
        return "push.example.com", [ip_address("8.8.8.8")]

    monkeypatch.setattr(web_push, "webpush_async", accepted)
    monkeypatch.setattr(web_push, "resolve_public_endpoint", public_endpoint)
    session = CapturingSession([Result(rowcount=1), Result(rowcount=1)])
    delivery = claim(key)
    outcome = await web_push.deliver_claim(
        session,  # type: ignore[arg-type]
        delivery,
        worker_settings(key),
    )
    completion = session.statements[0].compile(dialect=postgresql.dialect())
    assert outcome == "accepted"
    assert delivery.lease_token in completion.params.values()
    assert '"route":"/plan"' in web_push.PAYLOAD
    assert "meal" not in web_push.PAYLOAD.lower().replace("planned meal", "")

    stale_session = CapturingSession([Result(rowcount=0)])
    assert await web_push.deliver_claim(
        stale_session,  # type: ignore[arg-type]
        delivery,
        worker_settings(key),
    ) == "stale"
    assert len(stale_session.statements) == 1


@pytest.mark.asyncio
async def test_retry_is_bounded_and_410_disables_subscription(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key = Fernet.generate_key().decode()
    responses = iter([503, 410])

    async def rejected(**_kwargs: object) -> object:
        status = next(responses)
        raise WebPushException("rejected", response=SimpleNamespace(status=status))

    async def public_endpoint(_endpoint: str) -> tuple[str, list]:
        return "push.example.com", [ip_address("8.8.8.8")]

    monkeypatch.setattr(web_push, "webpush_async", rejected)
    monkeypatch.setattr(web_push, "resolve_public_endpoint", public_endpoint)
    settings = worker_settings(
        key,
        web_push_retry_base_seconds=10,
        web_push_retry_max_seconds=15,
        web_push_max_attempts=3,
    )

    retry_session = CapturingSession([Result(rowcount=1)])
    assert await web_push.deliver_claim(
        retry_session,  # type: ignore[arg-type]
        claim(key, attempt_count=2),
        settings,
    ) == "retry"
    assert web_push.retry_delay(settings, 3) == 15

    gone_session = CapturingSession([Result(rowcount=1), Result(rowcount=1)])
    assert await web_push.deliver_claim(
        gone_session,  # type: ignore[arg-type]
        claim(key),
        settings,
    ) == "disabled"
    disable_sql = str(gone_session.statements[1].compile(dialect=postgresql.dialect()))
    assert "UPDATE push_subscriptions" in disable_sql


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://push.example.com/send",
        "https://user@push.example.com/send",
        "https://push.example.com:8443/send",
        "https://localhost/send",
        "https://push.internal/send",
        "https://push.localdomain/send",
        "https://push.home.arpa/send",
        "https://10.0.0.1/send",
        "https://127.0.0.1/send",
        "https://169.254.1.1/send",
        "https://224.0.0.1/send",
        "https://0.0.0.0/send",
        "https://192.0.2.1/send",
        "https://[::1]/send",
    ],
)
def test_subscription_contract_rejects_unsafe_endpoint_shapes(endpoint: str) -> None:
    values = {
        "endpoint": endpoint,
        "expiration_time": None,
        "keys": {"p256dh": "key", "auth": "secret"},
    }
    with pytest.raises(ValidationError):
        PushSubscriptionCreate(**values)
    with pytest.raises(ValidationError):
        PushSubscriptionDelete(endpoint=endpoint)


class FakeLoop:
    def __init__(self, addresses: list[str] | None = None, error: OSError | None = None) -> None:
        self.addresses = addresses or []
        self.error = error

    async def getaddrinfo(self, host: str, port: int, **kwargs: object) -> list[tuple]:
        assert host == "push.example.com"
        assert port == 443
        assert kwargs == {
            "family": socket.AF_UNSPEC,
            "type": socket.SOCK_STREAM,
            "proto": socket.IPPROTO_TCP,
        }
        if self.error is not None:
            raise self.error
        return [
            (
                socket.AF_INET6 if ":" in address else socket.AF_INET,
                socket.SOCK_STREAM,
                socket.IPPROTO_TCP,
                "",
                (address, 443, 0, 0) if ":" in address else (address, 443),
            )
            for address in self.addresses
        ]


@pytest.mark.asyncio
async def test_endpoint_dns_accepts_only_exclusively_public_answers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        web_push.asyncio,
        "get_running_loop",
        lambda: FakeLoop(["8.8.8.8", "2606:4700:4700::1111"]),
    )
    host, addresses = await web_push.resolve_public_endpoint(
        "https://push.example.com/send/device"
    )
    assert host == "push.example.com"
    assert addresses == [ip_address("8.8.8.8"), ip_address("2606:4700:4700::1111")]

    monkeypatch.setattr(
        web_push.asyncio,
        "get_running_loop",
        lambda: FakeLoop(["10.0.0.1"]),
    )
    with pytest.raises(web_push.PushError, match="exclusively"):
        await web_push.resolve_public_endpoint("https://push.example.com/send/device")

    monkeypatch.setattr(
        web_push.asyncio,
        "get_running_loop",
        lambda: FakeLoop(["8.8.8.8", "10.0.0.1"]),
    )
    with pytest.raises(web_push.PushError, match="exclusively") as caught:
        await web_push.resolve_public_endpoint("https://push.example.com/send/device")
    assert caught.value.status_code == 422


@pytest.mark.asyncio
async def test_endpoint_literals_bypass_dns_and_must_be_public(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_loop() -> object:
        raise AssertionError("literal IP must not use DNS")

    monkeypatch.setattr(web_push.asyncio, "get_running_loop", unexpected_loop)
    host, addresses = await web_push.resolve_public_endpoint("https://8.8.8.8/send")
    assert host == "8.8.8.8"
    assert addresses == [ip_address("8.8.8.8")]
    with pytest.raises((ValidationError, ValueError)):
        await web_push.resolve_public_endpoint("https://127.0.0.1/send")


@pytest.mark.asyncio
async def test_delivery_resolver_pins_addresses_and_rejects_destination_changes() -> None:
    resolver = web_push._PinnedResolver(
        "push.example.com",
        [ip_address("8.8.8.8"), ip_address("2606:4700:4700::1111")],
    )
    resolved = await resolver.resolve("push.example.com", 443)
    assert [record["host"] for record in resolved] == [
        "8.8.8.8",
        "2606:4700:4700::1111",
    ]
    with pytest.raises(OSError, match="blocked"):
        await resolver.resolve("redirect.example.com", 443)
    with pytest.raises(OSError, match="blocked"):
        await resolver.resolve("push.example.com", 8443)


@pytest.mark.asyncio
async def test_subscription_revalidates_dns_before_database_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def unsafe(_endpoint: str) -> tuple[str, list]:
        raise web_push.PushError(422, "unsafe")

    class NoDatabaseAccess:
        async def scalar(self, _statement: object) -> object:
            raise AssertionError("unsafe endpoint reached the database")

    monkeypatch.setattr(web_push, "resolve_public_endpoint", unsafe)
    with pytest.raises(web_push.PushError, match="unsafe"):
        await web_push.upsert_subscription(
            NoDatabaseAccess(),  # type: ignore[arg-type]
            uuid.uuid4(),
            subscription(),
            Fernet.generate_key().decode(),
        )


@pytest.mark.asyncio
async def test_delivery_revalidates_dns_before_webpush(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key = Fernet.generate_key().decode()
    called = False

    async def unsafe(_endpoint: str) -> tuple[str, list]:
        raise web_push.PushError(422, "Push endpoint does not resolve exclusively to public addresses")

    async def should_not_send(**_kwargs: object) -> object:
        nonlocal called
        called = True
        return SimpleNamespace(status=201)

    monkeypatch.setattr(web_push, "resolve_public_endpoint", unsafe)
    monkeypatch.setattr(web_push, "webpush_async", should_not_send)
    session = CapturingSession([Result(rowcount=1)])
    outcome = await web_push.deliver_claim(
        session,  # type: ignore[arg-type]
        claim(key),
        worker_settings(key),
    )
    assert outcome == "failed"
    assert called is False
    completion = session.statements[0].compile(dialect=postgresql.dialect())
    assert "invalid_subscription" in completion.params.values()


def test_push_routes_require_cookie_session_not_automation_bearer() -> None:
    for route in push_routes.router.routes:
        dependency_calls = {dependency.call for dependency in route.dependant.dependencies}
        assert get_cookie_profile in dependency_calls
