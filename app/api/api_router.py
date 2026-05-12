from fastapi import APIRouter
from app.api import api_auth, api_healthcheck, api_user, api_session, api_message

router = APIRouter()

router.include_router(api_healthcheck.router, tags=["health-check"], prefix="/healthcheck")
router.include_router(api_auth.router, prefix="/auth", tags=["auth"])
router.include_router(api_user.router, tags=["user"], prefix="/user")
router.include_router(api_session.router, tags=["chat"], prefix="/chat")
router.include_router(api_message.router, tags=["message"], prefix="/message")