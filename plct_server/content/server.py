import json
import httpx
import os
import logging


from pathlib import Path
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Sequence
from urllib.parse import urljoin, urlparse
from urllib.request import url2pathname
from plct_server.ai.client import AiClientFactory
from plct_server.ai.conf import ModelProvider
from .fileset import FileSet, LocalFileSet
from ..ioutils import  read_str
from .course import CourseContent, TocItem, load_course
from ..ai import engine

ENV_NAME_OPENAI_API_KEY = "CHATAI_OPENAI_API_KEY"
ENV_NAME_AZURE_API_KEY = "CHATAI_AZURE_API_KEY"
ENV_NAME_VLLM_API_KEY = "CHATAI_VLLM_API_KEY"

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
                parsed_url = urlparse(p)
                if parsed_url.scheme == "" or parsed_url.scheme == "file":
                    urlPath = Path(url2pathname(parsed_url.path))
                    if not urlPath.anchor:
                        course_fs = FileSet.from_base_url(conf.content_url).subdir(urlPath.as_posix())
                    else:
                        course_fs = LocalFileSet(urlPath.as_posix())
                    
                else:    
                    course_fs = FileSet.from_base_url(p)
                logger.info(f"Loading course from {course_fs}")
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

def load_config(*, course_urls: tuple[str] = None, config_file: str = None, verbose: bool = None,
                ai_ctx_url: str = None, azure_default_ai_endpoint: str = None) -> ConfigOptions:
    """Load and resolve configuration from file, CLI args, and environment variables."""
    logger.debug(f"Loading config with course_urls: {course_urls}, config_file: {config_file}, verbose: {verbose}, ai_ctx_url: {ai_ctx_url}, azure_default_ai_endpoint: {azure_default_ai_endpoint}")
    conf: ConfigOptions = None
    cfg_file = config_file or os.environ.get("PLCT_SERVER_CONFIG_FILE") 
    default_course_urls = "plct-server-config.json"
    if cfg_file is None and os.path.isfile(default_course_urls):
        cfg_file = default_course_urls
    if cfg_file:
        logger.debug(f"Loading configuration file '{cfg_file}'")
        cfg_parsed_url = urlparse(cfg_file)
        if cfg_parsed_url.scheme == "":
            cfg_parsed_url = urlparse(Path(os.path.abspath(cfg_parsed_url.path)).as_uri())
        logger.debug(f"Parsed configuration file URL: {cfg_parsed_url}")
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
        elif cfg_parsed_url.scheme == "file":
                fname = url2pathname(cfg_parsed_url.path)
                try:
                    cfg_text = read_str(fname)
                except OSError as e:
                    logger.error(f"Error loading the configuration file '{cfg_file}': {e}")
        else:
            logger.error(f"Error loading the configuration file '{cfg_file}': "
                            f"unsupported scheme {cfg_parsed_url.scheme}.")
        if cfg_text is not None:
            try:
                cfg_dict = json.loads(cfg_text)
                conf = ConfigOptions(**cfg_dict)
                cfg_url = cfg_parsed_url.geturl()
                logger.debug(f"Configuration loaded from '{cfg_url}'")
                conf.content_url = urljoin(cfg_url, conf.content_url or ".")
                logger.debug(f"Content URL set to '{conf.content_url}'")
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
    if conf.verbose is not None:
        level = logging.DEBUG if conf.verbose else logging.INFO
        logging.getLogger().setLevel(level)
    logger.debug(f"ConfigOptions: {conf}")
    return conf

def init_server_content(conf: ConfigOptions) -> None:
    """Initialize the ServerContent singleton from the given configuration."""
    global _server_content
    _server_content = ServerContent(conf)

def init_ai_engine(conf: ConfigOptions) -> None:
    """Initialize the AI engine: resolve API keys, create client factory, and start the engine."""
    azure_api_key = os.getenv(ENV_NAME_AZURE_API_KEY)
    openai_api_key = os.getenv(ENV_NAME_OPENAI_API_KEY)
    vllm_api_key = os.getenv(ENV_NAME_VLLM_API_KEY)
    
    if azure_api_key:
        default_provider = ModelProvider.AZURE
    elif openai_api_key:
        default_provider = ModelProvider.OPENAI
    else:
        raise ValueError("Neither Azure nor OpenAI API key found in environment variables")
    
    client_factory = AiClientFactory(
        default_provider=default_provider,
        openai_api_key=openai_api_key,
        azure_api_key=azure_api_key,
        vllm_api_key=vllm_api_key,
        azure_default_ai_endpoint=conf.azure_default_ai_endpoint
    )

    if conf.ai_ctx_url:
        logger.info(f"Initializing AI engine with context URL: {conf.ai_ctx_url}")
        engine.init(ai_ctx_url=conf.ai_ctx_url, client_factory=client_factory)
        course_keys = engine.get_ai_engine().ctx_data.course_dict.keys()
        logger.info(f"Courses in AI Context: {', '.join(course_keys)}")

def configure(*, course_urls: tuple[str] = None, config_file: str = None, verbose: bool = None,
              ai_ctx_url: str = None, azure_default_ai_endpoint: str = None) -> None:
    """Umbrella method that loads config, initializes server content, and starts the AI engine."""
    conf = load_config(course_urls=course_urls, config_file=config_file, verbose=verbose,
                       ai_ctx_url=ai_ctx_url, azure_default_ai_endpoint=azure_default_ai_endpoint)
    init_server_content(conf)
    init_ai_engine(conf)


