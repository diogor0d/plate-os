from fastapi import APIRouter

from app.api.routes import (
    analytics,
    auth,
    chat,
    food,
    meals,
    profile,
    push,
    routines,
    settings,
    users,
    vision,
)

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(profile.router)
api_router.include_router(push.router)
api_router.include_router(settings.router)
api_router.include_router(food.router)
api_router.include_router(meals.router)
api_router.include_router(routines.router)
api_router.include_router(analytics.router)
api_router.include_router(vision.router)
api_router.include_router(chat.router)
