"""This module contains the FastAPI endpoints for the PLCT server.
It is used in the `.main` module, but also can be integrated into
other FastAPI applications. """

import os
import logging
import importlib.resources as pkg_resources
from pathlib import Path
from fastapi import FastAPI, HTTPException, status, APIRouter
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from plct_cli.project_config import ProjectConfig, get_project_config, ProjectConfigError
from .content import get_content_config, CourseConfig

logger = logging.getLogger(__name__)

router = APIRouter()

package_name = __name__.split('.')[0]

www_static = pkg_resources.files(package_name) / "www-static"

logger.info(f"www_static: {www_static}")

@router.get("/{full_path:path}")
async def read_html(full_path: str):
    c_conf = get_content_config()
    logger.info(f"full_path: {full_path}, c_conf: {c_conf}")
    if c_conf.single_course_mode:
        course_id = c_conf.course_ids[0]
        resource_path = full_path
    else:
        path_segments = full_path.split('/')
        course_id = path_segments[0]
        resource_path = '/'.join(path_segments[1:])
    
    if course_id not in c_conf.course_dict:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Course {course_id} not found")
    
    course_config = c_conf.course_dict[course_id]
    static_website_root = course_config.static_website_root

    # Construct the file path
    file_path = os.path.join(static_website_root, resource_path)

    # Check if the file exists and is an HTML file
    if os.path.isfile(file_path):
        return FileResponse(file_path)
    else:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Page not found")