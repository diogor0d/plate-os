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

logger = logging.getLogger("plateos")


async def seed_default_profile() -> None:
    """Single-user system: ensure exactly one profile row exists (decision D11)."""
    s = get_settings()
    async with SessionLocal() as session:
        existing = (
            await session.execute(select(UserProfile).limit(1))
        ).scalar_one_or_none()
        if existing is None:
            session.add(
                UserProfile(
                    weight_kg=s.default_weight_kg,
                    height_cm=s.default_height_cm,
                    timezone=s.default_user_timezone,
                )
            )
            await session.commit()
            logger.info("Seeded default user profile")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    try:
        await seed_default_profile()
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

    if profile_count != 1:
        logger.error("Readiness requires exactly one profile; found %s", profile_count)
        return JSONResponse({"status": "not_ready"}, status_code=503)
    return {"status": "ready"}
