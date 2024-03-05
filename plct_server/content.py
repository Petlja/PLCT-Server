from dataclasses import dataclass
import json
from pathlib import Path
from typing import Sequence, Optional
from plct_cli.project_config import get_project_config, ProjectConfigError
import os
from pydantic import BaseModel
from click import UsageError
import logging

import yaml

from . import ai

logger = logging.getLogger(__name__)

class CourseConfig(BaseModel):
    id: str
    title: str
    static_website_root: Path

class ContentConfig(BaseModel):
    course_project_dirs: Optional[Sequence[str]] = None
    verbose: Optional[bool] = None
    course_ids: Optional[list[str]] = None
    course_dict: Optional[dict[str, CourseConfig]] = None # course_id -> course_config


_current_content_config: ContentConfig = None

def get_content_config() -> ContentConfig:
    if _current_content_config is None:
        raise ValueError("Content configuration not initialized.")
    return _current_content_config

def configure(*, course_dirs: tuple[str] = None, verbose: bool = None) -> None:
    global _current_content_config

    content_config_file = os.environ.get("PLCT_SERVER_CONFIG_FILE")

    c_conf: ContentConfig = None
    if content_config_file:
        try:
            with open(content_config_file, 'r') as file:
                content_config_dict = json.load(file)
                c_conf = ContentConfig(**content_config_dict)
        except (OSError, ValueError, TypeError)as e:
            logger.error(f"Error loading the configuration file '{content_config_file}': {e}")
    else: 
        if course_dirs is None:
            logger.warn("The environvent variable PLCT_SERVER_CONFIG_FILE is not set.")
    
    if c_conf is None:
        c_conf = ContentConfig()
    
    if verbose is not None:
        c_conf.verbose = verbose
    
    if c_conf.verbose:
        package_logger = logging.getLogger(__name__.split('.')[0])
        package_logger.setLevel(logging.DEBUG)

    if course_dirs is None and c_conf.course_project_dirs is not None:
        course_dirs = c_conf.course_project_dirs
    
    if course_dirs:
        c_conf.course_project_dirs = course_dirs
        c_conf.course_ids = []
        c_conf.course_dict = {}
        for folder in course_dirs:
            if not Path(folder).is_dir():
                raise UsageError(f"Folder {folder} does not exist.")
            try:
                project_config = get_project_config(folder)
            except ProjectConfigError:
                raise UsageError(f"Folder {folder} is not a PLCT project.")
            if project_config.builder != "plct_builder":
                raise UsageError(f"Folder {folder} is not a PLCT project.")
            static_website_root = (Path(folder) / project_config.output_dir / 
                                    project_config.builder / "static_website")

            course_config_path =  static_website_root / "course.json"
            if not course_config_path.is_file():
                raise UsageError(f"Course configuration file {course_config_path} does not exist.")
            
            with open(course_config_path, 'r') as file:
                course_config = json.load(file)

            if "toc_tree" not in course_config:
                raise UsageError(f"Course configuration file {course_config_path} does not contain toc_tree.")
            toc_tree = course_config["toc_tree"]
            if "title" not in toc_tree:
                raise UsageError(f"Course configuration file {course_config_path} does not contain toc_tree.title.")
            if "meta_data" not in toc_tree:
                raise UsageError(f"Course configuration file {course_config_path} does not contain tpc_tree.meta_data.")
            if "alias" not in toc_tree["meta_data"]:
                raise UsageError(f"Course configuration file {course_config_path} does not contain toc_tree.meta_data.alias.")
            
            course_id = toc_tree["meta_data"]["alias"]
            course_config = CourseConfig(id=course_id, title=toc_tree["title"], 
                                            static_website_root=static_website_root)
            
            c_conf.course_ids.append(course_id)
            c_conf.course_dict[course_id] = course_config

    logger.debug(f"Content configuration: {c_conf} ")
    if c_conf.ai_context_dir:
        ai.init(c_conf.abspath(c_conf.ai_context_dir))

    #logger.debug(f"Content configuration: {c_conf} ")
    global _current_content_config
    _current_content_config = c_conf

