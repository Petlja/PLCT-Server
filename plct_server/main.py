import os
import logging
import importlib.resources as pkg_resources
from pathlib import Path
from fastapi import FastAPI, HTTPException, status
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from plct_cli.project_config import ProjectConfig, get_project_config, ProjectConfigError


logger = logging.getLogger(__name__)

app = FastAPI()

package_name = __name__.split('.')[0]

www_static = pkg_resources.files(package_name) / "www-static"

logger.info(f"www_static: {www_static}")

#app.mount("/ui", StaticFiles(directory=www_static), name="www-static")

#app.mount("/primer", StaticFiles(directory="../plct-testing/etit1/build/plct_builder/static_website"), name="primer")

static_website_root : Path
project_config : ProjectConfig

def set_cli_folders(folders: tuple[str]) -> None:
    global static_website_root, project_config

    # Will be generalized to process multiple folders later

    if len(folders) > 1:
        logger.warning(f"Currently only single folder is supported. Ignoring the rest: {folders[1:]}")
    project_folder = folders[0]
    project_config = get_project_config(project_folder)
    static_website_root = Path(project_folder) / project_config.output_dir / project_config.builder
    if project_config.builder == "plct_builder":
        static_website_root /=  "static_website"
    logger.info(f"static_website_root: {static_website_root}")

@app.get("/{full_path:path}")
async def read_html(full_path: str):
    # Construct the file path
    file_path = os.path.join(static_website_root, full_path)

    # Check if the file exists and is an HTML file
    if os.path.isfile(file_path):
        return FileResponse(file_path)
    else:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Page not found")

