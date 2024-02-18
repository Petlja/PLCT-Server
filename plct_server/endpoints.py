"""This module contains the FastAPI endpoints for the PLCT server.
It is used in the `.main` module, but also can be integrated into
other FastAPI applications. """

import os
import logging
import importlib.resources as pkg_resources
from pathlib import Path
from fastapi import FastAPI, HTTPException, status, APIRouter, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.templating import Jinja2Templates
from plct_cli.project_config import ProjectConfig, get_project_config, ProjectConfigError
from .content import get_content_config, CourseConfig
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

router = APIRouter()

package_name = __name__.split('.')[0]

www_static = pkg_resources.files(package_name) / "www-static"
templates_dir = pkg_resources.files(package_name) / "templates"
templates = Jinja2Templates(directory=templates_dir)

logger.debug(f"www_static: {www_static}")

@router.get("/{full_path:path}")
async def read_html(request: Request, full_path: str):
    c_conf = get_content_config()
    logger.debug(f"full_path: '{full_path}'")
    if full_path == "":
        full_path = "index.html"
    if c_conf.single_course_mode:
        course_id = c_conf.course_ids[0]
        resource_path = full_path
    elif full_path != "index.html":
        path_segments = full_path.split('/')
        course_id = path_segments[0]
        resource_path = '/'.join(path_segments[1:])
    else: # full_path == "index.html" and not in single_course_mode
        return templates.TemplateResponse("index.html", {
            "request": request, "course_ids": c_conf.course_ids, 
            "course_dict": c_conf.course_dict})
    
    if course_id not in c_conf.course_dict:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Page {request.url.path} not found")
    
    course_config = c_conf.course_dict[course_id]
    static_website_root = course_config.static_website_root

    # Construct the file path
    file_path = os.path.join(static_website_root, resource_path)

    # Check if the file exists and is an HTML file
    if os.path.isfile(file_path):
        return FileResponse(file_path)
    else:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Page {request.url.path} not found")