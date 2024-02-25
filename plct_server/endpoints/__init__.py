import logging
from fastapi import APIRouter
from .basic import router as basic_router
from .api import router as api_router


logger = logging.getLogger(__name__)

router = APIRouter()

router.include_router(basic_router)
router.include_router(api_router)

