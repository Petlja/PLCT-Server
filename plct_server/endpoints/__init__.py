import logging
from fastapi import APIRouter
from .pages import router as pages_router
from .api import router as api_router


logger = logging.getLogger(__name__)

router = APIRouter()

router.include_router(pages_router)
router.include_router(api_router)

