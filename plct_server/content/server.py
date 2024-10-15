from dataclasses import dataclass
from enum import Enum
from urllib.parse import urljoin, urlparse
import json
from typing import Sequence, Optional
import httpx
from plct_cli.project_config import get_project_config, ProjectConfig, ProjectConfigError
import os
import glob
from pydantic import BaseModel, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from click import UsageError
import logging

import yaml

from .fileset import FileSet

from ..ioutils import read_json, read_str

from .course import CourseContent, TocItem, load_course
from ..ai import engine

logger = logging.getLogger(__name__)

class ConfigOptions(BaseSettings):
    """Options from the configuration file and/or CLI attributes."""
    model_config = SettingsConfigDict(env_prefix='plct_')

    content_url: str | None = None
    course_paths: Sequence[str] = []

    @field_validator('course_paths', mode='before')
    def split_string(cls, v):
        if isinstance(v, str):
            l = [s.strip() for s in v.split(',')]
            if len(l) == 1 and l[0] == "":
                return []
            return l
        return v
    
    ai_ctx_url: str | None = None
    verbose: bool | None = None
    api_key: str | None = None
    azure_default_ai_endpoint: str | None = None

class ServerContent:

    config_options: ConfigOptions
    course_dict: dict[str, CourseContent] # course_key -> CourseContent

    def __init__(self, conf: ConfigOptions):
        self.config_options = conf
        self.course_dict = {}
        if conf.course_paths:
            for p in conf.course_paths:
                course_fs = FileSet.from_base_url(urljoin(conf.content_url+'/', p))
                course_content = load_course(course_fs)
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

def configure(*, course_urls: tuple[str] = None, config_file: str = None, verbose: bool = None,
              ai_ctx_url: str = None, azure_default_ai_endpoint: str = None) -> None:
    logger.debug(f"verbose: {verbose}")
    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    conf: ConfigOptions = None
    cfg_file = config_file or os.environ.get("PLCT_SERVER_CONFIG_FILE")
    if cfg_file:
        logger.debug(f"Loading configuration file '{cfg_file}'")
        cfg_parsed_url = urlparse(cfg_file)
        cfg_text: str = None
        if cfg_parsed_url.scheme == "http" or cfg_parsed_url.scheme == "https":
            try:
                cfg_text = httpx.get(cfg_file).text
            except httpx.RequestError as e:
                # Handle request errors (e.g., network issues)
                logger.error(f"Error loading the configuration file '{cfg_file}': " 
                             f"HTTP request error: {e}")
            except httpx.HTTPStatusError as e:
                # Handle HTTP status errors (e.g., 404, 500)
                logger.error(f"Error loading the configuration file '{cfg_file}': "
                             f"HTTP status error: {e.response.status_code}")
        else:
            if cfg_parsed_url.scheme == "file":
                fname = cfg_parsed_url.path
            elif cfg_parsed_url.scheme == "":
                fname = cfg_file
            else:
                logger.error(f"Error loading the configuration file '{cfg_file}': "
                             f"unsupported scheme {cfg_parsed_url.scheme}.")
            try:
                cfg_text = read_str(fname)
            except OSError as e:
                logger.error(f"Error loading the configuration file '{cfg_file}': {e}")
        if cfg_text is not None:
            try:
                cfg_dict = json.loads(cfg_text)
                conf = ConfigOptions(**cfg_dict)
                if cfg_parsed_url.scheme == "":
                    cfg_parsed_url = cfg_parsed_url._replace(
                        scheme="file",
                        path=os.path.abspath(cfg_parsed_url.path).replace(os.sep, '/'))
                cfg_url = cfg_parsed_url.geturl()
                conf.content_url = urljoin(cfg_url, conf.content_url)
                conf.ai_ctx_url = urljoin(cfg_url, conf.ai_ctx_url)
            except (OSError, ValueError, TypeError)as e:
                logger.error(f"Error loading the configuration file '{cfg_file}': {e}")
    if conf is None:
        conf = ConfigOptions()
    if course_urls:
        conf.course_urls = course_urls
    if ai_ctx_url:
        conf.ai_ctx_url = ai_ctx_url
    if verbose:
        conf.verbose = verbose
    if azure_default_ai_endpoint:
        conf.azure_default_ai_endpoint = azure_default_ai_endpoint
    if conf.verbose:
        logging.basicConfig(level=logging.DEBUG)
    logger.debug(f"ConfigOptions: {conf}")
    global _server_content
    _server_content = ServerContent(conf)
    if conf.ai_ctx_url:
        engine.init(ai_ctx_url=conf.ai_ctx_url, azure_default_ai_endpoint=conf.azure_default_ai_endpoint)
    


