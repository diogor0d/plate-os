"""Isolated polling process for the Web Push outbox."""

import asyncio
import logging
import signal
from datetime import UTC, datetime

from app.config import get_settings
from app.db import SessionLocal, engine
from app.services.web_push import (
    DeliveryClaim,
    claim_deliveries,
    deliver_claim,
    materialize_due_deliveries,
)
from app.services.routines import generate_notification_horizon

logger = logging.getLogger("plateos.web_push")


async def run() -> None:
    settings = get_settings()
    if settings.process_role != "worker":
        if settings.environment == "production":
            raise RuntimeError("Web Push worker requires PLATEOS_PROCESS_ROLE=worker")
        logger.info("Web Push worker disabled")
        return
    if not all(
        (
            settings.web_push_public_key,
            settings.web_push_private_key,
            settings.web_push_subscription_key,
            settings.web_push_vapid_subject,
        )
    ):
        logger.info("Web Push worker disabled because push configuration is absent")
        return

    stopping = asyncio.Event()
    loop = asyncio.get_running_loop()
    for name in ("SIGINT", "SIGTERM"):
        sig = getattr(signal, name, None)
        if sig is not None:
            try:
                loop.add_signal_handler(sig, stopping.set)
            except NotImplementedError:
                signal.signal(sig, lambda *_args: loop.call_soon_threadsafe(stopping.set))

    logger.info("Web Push worker started")
    while not stopping.is_set():
        try:
            now = datetime.now(UTC)
            async with SessionLocal() as session:
                await generate_notification_horizon(session, now=now)
                await materialize_due_deliveries(
                    session, now=now, limit=settings.web_push_batch_size
                )
                claims = await claim_deliveries(
                    session,
                    now=now,
                    limit=settings.web_push_batch_size,
                    lease_seconds=settings.web_push_lease_seconds,
                    max_attempts=settings.web_push_max_attempts,
                )

            async def deliver_one(claim: DeliveryClaim) -> None:
                try:
                    async with SessionLocal() as session:
                        outcome = await deliver_claim(session, claim, settings)
                        logger.info("Web Push delivery outcome=%s", outcome)
                except Exception:  # noqa: BLE001 - isolate one delivery from its batch
                    logger.exception("Web Push delivery processing failed")

            if claims:
                await asyncio.gather(*(deliver_one(claim) for claim in claims))
        except Exception:  # noqa: BLE001 - keep polling after transient DB/provider failures
            logger.exception("Web Push polling cycle failed")
        try:
            await asyncio.wait_for(stopping.wait(), timeout=settings.web_push_poll_seconds)
        except TimeoutError:
            pass
    await engine.dispose()
    logger.info("Web Push worker stopped")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run())
