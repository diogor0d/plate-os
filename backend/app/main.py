import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from app.api.routes.router import api_router
from app.config import get_settings
from app.db import SessionLocal
from app.models import UserProfile

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
    except Exception as exc:  # noqa: BLE001 - allow boot without DB for --help etc.
        logger.warning("Profile seeding skipped (DB unreachable?): %s", exc)
    yield


app = FastAPI(title="PlateOS API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # Vite dev server only; prod is same-origin
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.get("/api/health", tags=["meta"])
async def health():
    return {"status": "ok"}
