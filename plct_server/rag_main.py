from fastapi import FastAPI
from .endpoints import get_ui_router, get_rag_router
from .content.server import configure

configure()
app = FastAPI()
app.include_router(get_rag_router())