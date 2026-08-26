import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import func, select

from app.api.routes.router import api_router
from app.config import get_settings
from app.db import SessionLocal
from app.middleware import RequestBodyLimitMiddleware
from app.models import MealLog, MealLogMutation, UserProfile
from app.services.accounts import hash_password

logger = logging.getLogger("plateos")


async def ensure_bootstrap_accounts() -> None:
    """Seed the admin account, or backfill credentials onto a pre-0003 row
    (decision D36). Password material comes only from env/secret files."""
    s = get_settings()
    async with SessionLocal() as session:
        users = (
            (await session.execute(select(UserProfile).order_by(UserProfile.created_at)))
            .scalars()
            .all()
        )
        if not users:
            session.add(
                UserProfile(
                    username=s.admin_username,
                    password_hash=hash_password(s.app_password),
                    is_admin=True,
                    weight_kg=s.default_weight_kg,
                    height_cm=s.default_height_cm,
                    timezone=s.default_user_timezone,
                )
            )
            await session.commit()
            logger.info("Seeded bootstrap admin account")
            return

        primary = users[0]
        needs_hash = primary.password_hash is None
        needs_username = primary.username is None
        if needs_hash or needs_username:
            if needs_username:
                taken = await session.scalar(
                    select(UserProfile.id).where(UserProfile.username == s.admin_username)
                )
                primary.username = s.admin_username if taken is None else "admin"
            if needs_hash:
                primary.password_hash = hash_password(s.app_password)
            primary.is_admin = True
            await session.commit()
            logger.info("Backfilled credentials for existing account")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    try:
        await ensure_bootstrap_accounts()
    except Exception as exc:  # noqa: BLE001 - development may boot while DB starts
        if get_settings().environment == "production":
            raise
        logger.warning("Profile seeding skipped (DB unreachable?): %s", exc)
    yield


app = FastAPI(title="PlateOS API", version="0.1.0", lifespan=lifespan)

settings = get_settings()
app.add_middleware(RequestBodyLimitMiddleware, max_bytes=settings.max_request_body_bytes)
if settings.environment == "development":
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(api_router)


@app.get("/api/health", tags=["meta"])
async def health():
    return {"status": "ok"}


@app.get("/api/ready", tags=["meta"])
async def ready():
    """Readiness: expected schema is queryable and one profile exists."""
    try:
        async with SessionLocal() as session:
            profile_count = await session.scalar(select(func.count()).select_from(UserProfile))
            # Probe columns introduced by the current schema, including on empty tables.
            await session.scalar(select(MealLog.calories_per_100).limit(1))
            await session.scalar(select(MealLogMutation.request_fingerprint).limit(1))
    except Exception:  # noqa: BLE001 - return a stable status without leaking DB details
        logger.exception("Readiness database check failed")
        return JSONResponse({"status": "not_ready"}, status_code=503)

    if profile_count < 1:
        logger.error("Readiness requires at least one account; found %s", profile_count)
        return JSONResponse({"status": "not_ready"}, status_code=503)
    return {"status": "ready"}
