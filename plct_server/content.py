from dataclasses import dataclass
import json
from typing import Sequence, Optional
from plct_cli.project_config import get_project_config, ProjectConfigError
import os
import glob
from pydantic import BaseModel
from click import UsageError
import logging

import yaml

from . import ai

logger = logging.getLogger(__name__)


class CourseAiContext(BaseModel):
    summary: str
    activity_summary: dict[str, str] # activity_id -> summary

class CourseConfig(BaseModel):
    id: str
    title: str
    static_website_root: str
    ai_context: CourseAiContext = None


class ContentConfig(BaseModel):

    # Original config values from the config file and/or CLI options
    course_project_dirs: Sequence[str] = None
    ai_context_dir: str = None
    verbose: bool = None
    base_path: str = None

    # Attributes derived from the original config values
    course_ids: list[str] = None
    course_dict: dict[str, CourseConfig] = None # course_key -> course_config

    def abspath(self, path: str) -> str:
        """Return the absolute path of a file or directory relative to the base path."""
        if os.path.isabs(path):
            return path
        if self.base_path is None:
            return os.path.abspath(path)
        return os.path.abspath(os.path.join(self.base_path, path))

_current_content_config: ContentConfig = None

def get_content_config() -> ContentConfig:
    if _current_content_config is None:
        raise ValueError("Content configuration not initialized.")
    return _current_content_config

def configure(*, course_dirs: tuple[str] = None, verbose: bool = None,
              ai_context_dir: str = None) -> None:

    content_config_file = os.environ.get("PLCT_SERVER_CONFIG_FILE")

    c_conf: ContentConfig = None
    if content_config_file:
        try:
            with open(content_config_file, 'r') as file:
                content_config_dict = json.load(file)
                c_conf = ContentConfig(**content_config_dict)
                c_conf.base_path = os.path.dirname(content_config_file)
        except (OSError, ValueError, TypeError)as e:
            logger.error(f"Error loading the configuration file '{content_config_file}': {e}")
    else: 
        if course_dirs is None:
            logger.warn("The environvent variable PLCT_SERVER_CONFIG_FILE is not set.")
    
    if c_conf is None:
        c_conf = ContentConfig()

    if course_dirs:
        c_conf.course_project_dirs = course_dirs
    
    if ai_context_dir:
        c_conf.ai_context_dir = ai_context_dir

    if verbose is not None:
        c_conf.verbose = verbose

    _apply_conf(c_conf)

def _apply_conf(c_conf: ContentConfig) -> None:

    if c_conf.verbose:
        logging.basicConfig(level=logging.DEBUG)
    
    if c_conf.course_project_dirs:
        c_conf.course_ids = []
        c_conf.course_dict = {}
        for folder in c_conf.course_project_dirs:
            if not os.path.isdir(folder):
                raise UsageError(f"Folder {folder} does not exist.")
            try:
                project_config = get_project_config(folder)
            except ProjectConfigError:
                raise UsageError(f"Folder {folder} is not a PLCT project.")
            if project_config.builder != "plct_builder":
                raise UsageError(f"Folder {folder} is not a PLCT project.")
            static_website_root = os.path.join(
                c_conf.abspath(folder), project_config.output_dir, 
                project_config.builder, "static_website")

            course_config_path =  os.path.join(static_website_root, "course.json")
            if not os.path.isfile(course_config_path):
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



