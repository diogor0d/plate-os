from fastapi import APIRouter

from app.api.routes import analytics, auth, chat, food, meals, profile, vision

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(profile.router)
api_router.include_router(food.router)
api_router.include_router(meals.router)
api_router.include_router(analytics.router)
api_router.include_router(vision.router)
api_router.include_router(chat.router)
