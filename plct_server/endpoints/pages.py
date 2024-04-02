"""This module contains the FastAPI endpoints for the PLCT server.
It is used in the `.main` module, but also can be integrated into
other FastAPI applications. """

import os
import posixpath
import logging
import importlib.resources as pkg_resources
from pathlib import Path
from fastapi import FastAPI, HTTPException, status, APIRouter, Request
from fastapi.routing import Mount
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from plct_cli.project_config import ProjectConfig, get_project_config, ProjectConfigError
from ..content.server import get_server_content
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

router = APIRouter()

package_name = __name__.split('.')[0]
parent_module_full_name = '.'.join(__name__.split('.')[:-1])



front_app_dir = pkg_resources.files(package_name) / "front-app" / "build"
templates_dir = pkg_resources.files(parent_module_full_name) / "jinja-templates"
templates = Jinja2Templates(directory=templates_dir)

logger.debug(f"front_app_dir: {front_app_dir}")


def safe_join(base_directory:str, relative_path:str):

    # Normalize the path to remove any '../' or './' components
    normalized_path = os.path.normpath(relative_path)

    # Join the base directory with the normalized relative path
    final_path = os.path.join(base_directory, normalized_path)

    # Check if the final path is within the base directory
    if not (os.path.commonprefix([final_path, base_directory]) == base_directory):
        raise ValueError("Path traversal attempt detected")

    return final_path

def safe_url_join(base_url:str, relative_path:str):
    base_url_parsed = urlparse(base_url)
    new_path = safe_join(base_url_parsed.path, relative_path)
    new_url = base_url_parsed._replace(path=new_path).geturl()
    return new_url

def not_found_page(request: Request):
    return templates.TemplateResponse(
        "404.html", {"request": request}, 
        status_code=status.HTTP_404_NOT_FOUND)

@router.get("/app/{full_path:path}")
async def read_app(request: Request, full_path: str):
    try:
        file_path = safe_join(str(front_app_dir), full_path)
    except ValueError:
        return not_found_page(request)

    if os.path.isfile(file_path):
        return FileResponse(file_path)
    else:
        if '.' not in full_path:
            # requested path may be a client-side route
            index_path = os.path.join(front_app_dir, 'index.html')
            return FileResponse(index_path)
        return not_found_page(request)

@router.get("/index.html")
@router.get("/")
async def read_index(request: Request):
    return RedirectResponse(url="app/")

@router.get("/course/{path_param:path}")
async def read_course_file(request: Request, path_param: str):
    srv_cnt = get_server_content()
    logger.debug(f"path_param: '{path_param}'")

    path_segments = posixpath.normpath(path_param).split('/')
    course_key = path_segments[0]
    course_rel_path = '/'.join(path_segments[1:])
    logger.debug(f"course_id: '{course_key}', course_rel_path: '{course_rel_path}'")

    if course_key not in srv_cnt.course_dict:
        logger.debug(f"course_id '{course_key}' not found in course_dict")
        return not_found_page(request)
    
    course_content = srv_cnt.course_dict[course_key]

    return course_content.html_fs.fastapi_response(request, course_rel_path)

    
