import logging
from fastapi import APIRouter



logger = logging.getLogger(__name__)

def get_ui_router() -> APIRouter:
    from .pages import router as pages_router
    from .ui_api import router as api_router

    router = APIRouter()

    router.include_router(pages_router)
    router.include_router(api_router)
    return router

def get_rag_router() -> APIRouter:
    from .rag_api import router as rag_router
    return rag_router

