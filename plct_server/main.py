import logging
import importlib.resources as pkg_resources
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

logger = logging.getLogger(__name__)

app = FastAPI()

package_name = __name__.split('.')[0]

www_static = pkg_resources.files(package_name) / "www-static"

logger.info(f"www_static: {www_static}")

app.mount("/ui", StaticFiles(directory=www_static), name="www-static")

app.mount("/primer", StaticFiles(directory="../plct-testing/etit1/build/plct_builder/static_website"), name="primer")

@app.get("/")
async def root():
    return{"message": "Hello, world!"}



