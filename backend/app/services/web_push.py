"""Encrypted Web Push subscriptions and leased outbox delivery."""

import asyncio
import hashlib
import json
import socket
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from ipaddress import IPv4Address, IPv6Address, ip_address
from typing import Any

import aiohttp
from aiohttp import ClientError
from cryptography.fernet import Fernet, InvalidToken
from pywebpush import WebPushException, webpush_async
from pydantic import HttpUrl, TypeAdapter
from sqlalchemy import and_, exists, literal, or_, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, parse_vapid_private_key
from app.models import NotificationIntent, PushSubscription, WebPushDelivery
from app.schemas.push import (
    PushSubscriptionCreate,
    _is_public_address,
    _validate_endpoint_shape,
)

PAYLOAD = json.dumps(
    {"title": "PlateOS", "body": "A planned meal is coming up.", "route": "/plan"},
    separators=(",", ":"),
)


class PushError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail


@dataclass(frozen=True)
class DeliveryClaim:
    intent_id: uuid.UUID
    subscription_id: uuid.UUID
    lease_token: uuid.UUID
    attempt_count: int
    encrypted_subscription: bytes


def endpoint_fingerprint(endpoint: str) -> str:
    return hashlib.sha256(endpoint.encode("utf-8")).hexdigest()


async def resolve_public_endpoint(endpoint: str) -> tuple[str, list[IPv4Address | IPv6Address]]:
    """Resolve every endpoint address and reject any non-public destination."""
    parsed = _validate_endpoint_shape(TypeAdapter(HttpUrl).validate_python(endpoint))
    host = parsed.host
    if host is None:  # The schema already rejects this; retain a defensive service boundary.
        raise PushError(422, "Push endpoint is invalid")
    normalized_host = host.rstrip(".").lower()
    try:
        literal = ip_address(normalized_host.strip("[]"))
    except ValueError:
        try:
            infos = await asyncio.get_running_loop().getaddrinfo(
                normalized_host,
                443,
                family=socket.AF_UNSPEC,
                type=socket.SOCK_STREAM,
                proto=socket.IPPROTO_TCP,
            )
        except OSError as exc:
            raise PushError(422, "Push endpoint cannot be resolved safely") from exc
        addresses = list(dict.fromkeys(ip_address(info[4][0]) for info in infos))
    else:
        addresses = [literal]
    if not addresses or any(not _is_public_address(address) for address in addresses):
        raise PushError(422, "Push endpoint does not resolve exclusively to public addresses")
    return normalized_host, addresses


class _PinnedResolver(aiohttp.abc.AbstractResolver):
    def __init__(self, host: str, addresses: list[IPv4Address | IPv6Address]) -> None:
        self.host = host
        self.addresses = addresses

    async def resolve(
        self, host: str, port: int = 0, family: socket.AddressFamily = socket.AF_INET
    ) -> list[dict[str, Any]]:
        if host.rstrip(".").lower() != self.host or port != 443:
            raise OSError("Web Push redirect or destination change blocked")
        return [
            {
                "hostname": host,
                "host": str(address),
                "port": port,
                "family": socket.AF_INET6 if address.version == 6 else socket.AF_INET,
                "proto": socket.IPPROTO_TCP,
                "flags": 0,
            }
            for address in self.addresses
        ]

    async def close(self) -> None:
        return None


async def _send_push(subscription: dict[str, Any], settings: Settings) -> Any:
    endpoint = subscription.get("endpoint")
    if not isinstance(endpoint, str):
        raise PushError(500, "Stored push subscription is invalid")
    try:
        host, addresses = await resolve_public_endpoint(endpoint)
    except (ValueError, TypeError) as exc:
        raise PushError(422, "Push endpoint is invalid") from exc

    async def reject_redirect(
        _session: aiohttp.ClientSession,
        _context: object,
        _params: object,
    ) -> None:
        raise ClientError("Web Push redirects are not allowed")

    trace = aiohttp.TraceConfig()
    trace.on_request_redirect.append(reject_redirect)
    connector = aiohttp.TCPConnector(resolver=_PinnedResolver(host, addresses), use_dns_cache=False)
    async with aiohttp.ClientSession(connector=connector, trace_configs=[trace]) as client:
        return await webpush_async(
            subscription_info=subscription,
            data=PAYLOAD,
            vapid_private_key=parse_vapid_private_key(settings.web_push_private_key_value or ""),
            vapid_claims={"sub": str(settings.web_push_vapid_subject)},
            ttl=300,
            timeout=settings.web_push_request_timeout_seconds,
            aiohttp_session=client,
        )


def encrypt_subscription(body: PushSubscriptionCreate, key: str) -> bytes:
    raw = body.model_dump(mode="json", exclude={"device_name"})
    return Fernet(key.encode("ascii")).encrypt(
        json.dumps(raw, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )


def decrypt_subscription(value: bytes, key: str) -> dict[str, Any]:
    try:
        raw = Fernet(key.encode("ascii")).decrypt(value)
        parsed = json.loads(raw)
    except (InvalidToken, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise PushError(500, "Stored push subscription cannot be decrypted") from exc
    if not isinstance(parsed, dict):
        raise PushError(500, "Stored push subscription is invalid")
    return parsed


async def list_subscriptions(session: AsyncSession, user_id: uuid.UUID) -> list[PushSubscription]:
    result = await session.execute(
        select(PushSubscription)
        .where(PushSubscription.user_id == user_id)
        .order_by(PushSubscription.created_at)
    )
    return list(result.scalars().all())


async def upsert_subscription(
    session: AsyncSession, user_id: uuid.UUID, body: PushSubscriptionCreate, key: str
) -> PushSubscription:
    endpoint = str(body.endpoint)
    await resolve_public_endpoint(endpoint)
    fingerprint = endpoint_fingerprint(endpoint)
    existing = await session.scalar(
        select(PushSubscription).where(PushSubscription.endpoint_fingerprint == fingerprint)
    )
    encrypted = encrypt_subscription(body, key)
    if existing is not None:
        if existing.user_id != user_id:
            raise PushError(409, "Push endpoint is already registered")
        existing.encrypted_subscription = encrypted
        existing.device_name = body.device_name
        existing.disabled_at = None
        existing.updated_at = datetime.now(UTC)
        subscription = existing
    else:
        subscription = PushSubscription(
            user_id=user_id,
            endpoint_fingerprint=fingerprint,
            encrypted_subscription=encrypted,
            device_name=body.device_name,
        )
        session.add(subscription)
    await session.commit()
    await session.refresh(subscription)
    return subscription


async def unsubscribe(session: AsyncSession, user_id: uuid.UUID, endpoint: str) -> None:
    result = await session.execute(
        update(PushSubscription)
        .where(
            PushSubscription.user_id == user_id,
            PushSubscription.endpoint_fingerprint == endpoint_fingerprint(endpoint),
            PushSubscription.disabled_at.is_(None),
        )
        .values(disabled_at=datetime.now(UTC), updated_at=datetime.now(UTC))
    )
    if result.rowcount == 0:
        raise PushError(404, "Push subscription not found")
    await session.commit()


async def materialize_due_deliveries(
    session: AsyncSession, *, now: datetime, limit: int
) -> int:
    already_materialized = exists().where(
        WebPushDelivery.intent_id == NotificationIntent.id,
        WebPushDelivery.subscription_id == PushSubscription.id,
    )
    candidates = (
        select(
            NotificationIntent.id.label("intent_id"),
            PushSubscription.id.label("subscription_id"),
        )
        .join(PushSubscription, PushSubscription.user_id == NotificationIntent.user_id)
        .where(
            NotificationIntent.scheduled_for <= now,
            NotificationIntent.expires_at > now,
            NotificationIntent.cancelled_at.is_(None),
            PushSubscription.disabled_at.is_(None),
            ~already_materialized,
        )
        .order_by(NotificationIntent.scheduled_for, NotificationIntent.id, PushSubscription.id)
        .limit(limit)
        .with_for_update(skip_locked=True, of=NotificationIntent)
        .cte("candidate_delivery_pairs")
    )
    source = select(
        candidates.c.intent_id,
        candidates.c.subscription_id,
        literal("pending"),
        literal(0),
        literal(now),
    )
    statement = (
        pg_insert(WebPushDelivery)
        .from_select(
            ["intent_id", "subscription_id", "status", "attempt_count", "next_attempt_at"],
            source,
        )
        .on_conflict_do_nothing(
            index_elements=[WebPushDelivery.intent_id, WebPushDelivery.subscription_id]
        )
    )
    result = await session.execute(statement)
    inserted = result.rowcount

    await session.execute(
        update(WebPushDelivery)
        .where(
            WebPushDelivery.status.in_(("pending", "retry", "leased")),
            exists().where(
                NotificationIntent.id == WebPushDelivery.intent_id,
                or_(
                    NotificationIntent.expires_at <= now,
                    NotificationIntent.cancelled_at.is_not(None),
                ),
            ),
        )
        .values(status="expired", completed_at=now, leased_until=None, lease_token=None)
    )
    await session.commit()
    return inserted


async def claim_deliveries(
    session: AsyncSession,
    *,
    now: datetime,
    limit: int,
    lease_seconds: int,
    max_attempts: int,
) -> list[DeliveryClaim]:
    await session.execute(
        update(WebPushDelivery)
        .where(
            WebPushDelivery.status == "leased",
            WebPushDelivery.leased_until <= now,
            WebPushDelivery.attempt_count >= max_attempts,
        )
        .values(
            status="failed",
            completed_at=now,
            leased_until=None,
            lease_token=None,
            error_code="lease_expired",
        )
    )
    eligible = (
        select(WebPushDelivery.intent_id, WebPushDelivery.subscription_id)
        .join(NotificationIntent, NotificationIntent.id == WebPushDelivery.intent_id)
        .join(PushSubscription, PushSubscription.id == WebPushDelivery.subscription_id)
        .where(
            or_(
                and_(
                    WebPushDelivery.status.in_(("pending", "retry")),
                    WebPushDelivery.next_attempt_at <= now,
                ),
                and_(WebPushDelivery.status == "leased", WebPushDelivery.leased_until <= now),
            ),
            NotificationIntent.cancelled_at.is_(None),
            NotificationIntent.expires_at > now,
            PushSubscription.disabled_at.is_(None),
            PushSubscription.user_id == NotificationIntent.user_id,
            WebPushDelivery.attempt_count < max_attempts,
        )
        .order_by(WebPushDelivery.next_attempt_at)
        .limit(limit)
        .with_for_update(skip_locked=True, of=WebPushDelivery)
        .cte("claimable_deliveries")
    )
    token = uuid.uuid4()
    claimed = (
        update(WebPushDelivery)
        .where(
            tuple_(WebPushDelivery.intent_id, WebPushDelivery.subscription_id).in_(select(eligible))
        )
        .values(
            status="leased",
            leased_until=now + timedelta(seconds=lease_seconds),
            lease_token=token,
            attempt_count=WebPushDelivery.attempt_count + 1,
        )
        .returning(
            WebPushDelivery.intent_id,
            WebPushDelivery.subscription_id,
            WebPushDelivery.attempt_count,
        )
        .cte("claimed_deliveries")
    )
    rows = (
        await session.execute(
            select(
                claimed.c.intent_id,
                claimed.c.subscription_id,
                claimed.c.attempt_count,
                PushSubscription.encrypted_subscription,
            ).join(PushSubscription, PushSubscription.id == claimed.c.subscription_id)
        )
    ).all()
    await session.commit()
    return [DeliveryClaim(row[0], row[1], token, row[2], row[3]) for row in rows]


def retry_delay(settings: Settings, attempt_count: int) -> int:
    return min(
        settings.web_push_retry_max_seconds,
        settings.web_push_retry_base_seconds * (2 ** max(0, attempt_count - 1)),
    )


async def _finish(
    session: AsyncSession,
    claim: DeliveryClaim,
    *,
    now: datetime,
    status: str,
    status_code: int | None,
    error_code: str | None,
    next_attempt_at: datetime | None = None,
) -> bool:
    values: dict[str, Any] = {
        "status": status,
        "last_status_code": status_code,
        "error_code": error_code,
        "leased_until": None,
        "lease_token": None,
    }
    if next_attempt_at is not None:
        values["next_attempt_at"] = next_attempt_at
    else:
        values["completed_at"] = now
    if status == "accepted":
        values["accepted_at"] = now
    result = await session.execute(
        update(WebPushDelivery)
        .where(
            WebPushDelivery.intent_id == claim.intent_id,
            WebPushDelivery.subscription_id == claim.subscription_id,
            WebPushDelivery.status == "leased",
            WebPushDelivery.lease_token == claim.lease_token,
        )
        .values(**values)
    )
    return result.rowcount == 1


async def deliver_claim(session: AsyncSession, claim: DeliveryClaim, settings: Settings) -> str:
    now = datetime.now(UTC)
    try:
        subscription = decrypt_subscription(
            claim.encrypted_subscription, settings.web_push_subscription_key_value or ""
        )
        response = await _send_push(subscription, settings)
        status_code = int(response.status)
    except PushError:
        status_code = None
        retryable = False
        error_code = "invalid_subscription"
    except WebPushException as exc:
        response = exc.response
        status_code = getattr(response, "status", getattr(response, "status_code", None))
        retryable = status_code is None or status_code == 429 or status_code >= 500
        error_code = "transport_error" if status_code is None else f"http_{status_code}"
    except (ClientError, OSError, TimeoutError):
        status_code = None
        retryable = True
        error_code = "transport_error"
    else:
        retryable = False
        error_code = None

    if status_code in (404, 410):
        finished = await _finish(
            session, claim, now=now, status="disabled", status_code=status_code,
            error_code=f"http_{status_code}",
        )
        if finished:
            await session.execute(
                update(PushSubscription)
                .where(PushSubscription.id == claim.subscription_id)
                .values(disabled_at=now, updated_at=now)
            )
        await session.commit()
        return "disabled" if finished else "stale"
    if status_code is not None and 200 <= status_code < 300:
        finished = await _finish(
            session, claim, now=now, status="accepted", status_code=status_code, error_code=None
        )
        if finished:
            await session.execute(
                update(PushSubscription)
                .where(PushSubscription.id == claim.subscription_id)
                .values(last_success_at=now, updated_at=now)
            )
        await session.commit()
        return "accepted" if finished else "stale"
    if retryable and claim.attempt_count < settings.web_push_max_attempts:
        finished = await _finish(
            session,
            claim,
            now=now,
            status="retry",
            status_code=status_code,
            error_code=error_code,
            next_attempt_at=now + timedelta(seconds=retry_delay(settings, claim.attempt_count)),
        )
        await session.commit()
        return "retry" if finished else "stale"
    finished = await _finish(
        session, claim, now=now, status="failed", status_code=status_code, error_code=error_code
    )
    await session.commit()
    return "failed" if finished else "stale"
