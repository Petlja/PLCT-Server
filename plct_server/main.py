from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from .endpoints import router

app = FastAPI()

app.include_router(router)
