from fastapi import FastAPI
from .endpoints import router
from .content.server import configure

configure()
app = FastAPI()
app.include_router(router)
