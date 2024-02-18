from dataclasses import dataclass
import json
from pathlib import Path
from typing import Sequence, Optional
from plct_cli.project_config import ProjectConfig, get_project_config, ProjectConfigError
import os
from pydantic import BaseModel
from click import UsageError


class CourseConfig(BaseModel):
    id: str
    title: str
    static_website_root: Path

class ContentConfig(BaseModel):
    single_course_mode: Optional[bool] = False

    course_project_folders: Optional[Sequence[str]] = None

    course_ids: list[str]
    course_dict: dict[str, CourseConfig] # course_id -> course_config


_current_content_config: ContentConfig = None

def get_content_config() -> ContentConfig:
    global _current_content_config
    if _current_content_config is None:
        content_config_file = os.environ.get("PLCT_SERVER_CONFIG_FILE")
        if content_config_file is None:
            raise ValueError("Environment variable PLCT_SERVER_CONFIG_FILE is not set.")
        with open(content_config_file, 'r') as file:
            content_config_dict = json.load(file)
        _current_content_config = ContentConfig(**content_config_dict)
    return _current_content_config

def set_cli_folders(folders: tuple[str]) -> None:
    global _current_content_config
    
    if len(folders) == 0:
        content_config_file = os.environ.get("PLCT_SERVER_CONFIG_FILE")
        if content_config_file is None:
            folders = ('./',)
        else:
            with open(content_config_file, 'r') as file:
                content_config_dict = json.load(file)
            _current_content_config = ContentConfig(**content_config_dict)
            return

    c_conf = ContentConfig(course_project_folders=folders, course_ids=[], course_dict={})    
    if len(folders) == 1:
        c_conf.single_course_mode = True
    c_conf.course_project_folders = folders
    c_conf.course_ids = []
    c_conf.course_dict = {}
    for folder in folders:
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


    _current_content_config = c_conf

