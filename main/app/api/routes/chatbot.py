"""하위 호환: 라우터 본문은 ``app.routers.chatbot`` 으로 이동."""

from app.routers.chatbot import router

__all__ = ["router"]
