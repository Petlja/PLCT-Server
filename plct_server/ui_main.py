from fastapi import FastAPI
from .endpoints import get_ui_router
from .endpoints.auth import UiGate
from .content.server import configure

configure()
app = FastAPI()
app.add_middleware(UiGate)
app.include_router(get_ui_router())
