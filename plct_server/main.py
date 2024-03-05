from fastapi import FastAPI
from .endpoints import router
from . import content

content.configure()
app = FastAPI()
app.include_router(router)
