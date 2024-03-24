from dataclasses import dataclass
import json
from typing import Sequence, Optional
from plct_cli.project_config import get_project_config, ProjectConfig, ProjectConfigError
import os
import glob
from pydantic import BaseModel
from click import UsageError
import logging

import yaml

from ..ioutils import read_json

from .course import CourseContent, TocItem, load_course
from ..ai import engine

logger = logging.getLogger(__name__)

class ConfigOptions(BaseModel):
    """Options from the configuration file and/or CLI attributes."""
    course_project_dirs: Sequence[str] = None
    ai_context_dir: str = None
    verbose: bool = None
    base_path: str = None
    api_key: str = None

class ServerContent:

    config_options: ConfigOptions
    course_dict: dict[str, CourseContent] # course_key -> CourseContent

    def __init__(self, conf: ConfigOptions):
        self.config_options = conf
        self.course_dict = {}
        if conf.course_project_dirs:
            for d in conf.course_project_dirs:
                dir = os.path.join(conf.base_path or "", d)
                if not os.path.isdir(dir):
                    raise UsageError(f"Folder {dir} does not exist.")
                course_content = load_course(dir)
                self.course_dict[course_content.course_key] = course_content
    
    def get_toc_item(self, course_key: str, item_path: list[str]) -> TocItem | None:
        course_content = self.course_dict.get(course_key)
        if course_content is None:
            return None
        item = course_content.root_toc_item
        for key in item_path:
            item = item.child_items.get(key)
            if item is None:
                return None
        return item
    
    def get_toc_list(self, course_key: str, item_path: list[str]) -> list[TocItem] | None:
        course_content = self.course_dict.get(course_key)
        if course_content is None:
            return None
        item = course_content.root_toc_item
        for key in item_path:
            item = item.child_items.get(key)
            if item is None:
                return None
        return list(item.child_items.values())

_server_content: ServerContent = None

def get_server_content() -> ServerContent:
    if _server_content is None:
        raise ValueError("Content configuration not initialized.")
    return _server_content

def configure(*, course_dirs: tuple[str] = None, verbose: bool = None,
              ai_context_dir: str = None) -> None:

    content_config_file = os.environ.get("PLCT_SERVER_CONFIG_FILE")
    conf: ConfigOptions = None
    if content_config_file:
        try:
            content_config_dict = read_json(content_config_file)
            conf = ConfigOptions(**content_config_dict)
            conf.base_path = os.path.dirname(content_config_file)
        except (OSError, ValueError, TypeError)as e:
            logger.error(f"Error loading the configuration file '{content_config_file}': {e}")
    else: 
        logger.warn("The environvent variable PLCT_SERVER_CONFIG_FILE is not set.")
    if conf is None:
        conf = ConfigOptions()
    if course_dirs:
        conf.course_project_dirs = course_dirs
    if ai_context_dir:
        conf.ai_context_dir = ai_context_dir
    if verbose is not None:
        conf.verbose = verbose
    logger.debug(f"ConfigOptions: {conf}")

    if conf.verbose:
        logging.basicConfig(level=logging.DEBUG)
    global _server_content
    _server_content = ServerContent(conf)
    if conf.ai_context_dir:
        dir = os.path.join(conf.base_path or "", conf.ai_context_dir)
        engine.init(dir)
    


