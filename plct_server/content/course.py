import json
import logging
import os
import yaml

from .fileset import FileSet

from ..ioutils import read_json, read_yaml

logger = logging.getLogger(__name__)

class TocItem:
    level: int
    key: str
    title: str
    child_items: dict[str, 'TocItem']

    def __init__(self, level: int, key: str, title: str, child_items: dict[str, 'TocItem']):
        self.level = level
        self.key = key
        self.title = title
        self.child_items = child_items

class CourseContent:
    course_key: str
    root_toc_item: TocItem
    html_fs: FileSet

    @property
    def title(self) -> str:
        return self.root_toc_item.title

    def __init__(self, course_key: str, root_toc_item: TocItem, html_fs: FileSet):
        self.course_key = course_key
        self.root_toc_item = root_toc_item
        self.html_fs = html_fs

class  CourseLoadError(Exception):
    pass

def load_course(course_fs: FileSet) -> CourseContent:
    logger.debug(f"load_course: {course_fs}")
    config = course_fs.read_yaml("plct_config.yaml")
    if config != None:
        output_dir = config.get("output_dir")
        if output_dir is None:
            raise CourseLoadError(f"Configuration file does not contain output_dir.")
        builder = config.get("builder")
        if builder is None:
            raise CourseLoadError(f"Configuration file does not contain builder.")   
        if builder == "plct_builder":
            html_fs = course_fs.subdir(f"{output_dir}/{builder}/static_website")
            return course_from_plct_build(html_fs)
        else:
            cc = CourseLoadError(f"Builder {builder} not supported.")
            if cc is not None:
                return cc
            raise CourseLoadError(f"Course configuration file course.json does not exist in {html_fs}.")
    else:
        html_fs = course_fs.subdir("_build")
        cc = course_from_index_yaml(html_fs)
        if cc is not None:
            return cc
        cc = course_from_index_yaml(course_fs)
        if cc is not None:
            return cc
        cc = course_from_plct_build(course_fs) 
        if cc is not None:
            return cc
        raise CourseLoadError(f"Can't find course project in {course_fs}.")


def course_from_plct_build(html_fs: FileSet) -> CourseContent:
    course_json = html_fs.read_json("course.json")
    if course_json == None:
        return None
    #print(course_json)
    if "toc_tree" not in course_json:
        raise CourseLoadError(f"Course configuration file does not contain toc_tree.")
    root_toc_dict = course_json["toc_tree"]
    if "title" not in root_toc_dict:
        raise CourseLoadError(f"Course configuration file does not contain toc_tree.title.")
    if "meta_data" not in root_toc_dict:
        raise CourseLoadError(f"Course configuration file does not contain tpc_tree.meta_data.")
    if "alias" not in root_toc_dict["meta_data"]:
        raise CourseLoadError(f"Course configuration file does not contain toc_tree.meta_data.alias.")
    course_key = root_toc_dict["meta_data"]["alias"]

    def load_toc_item(toc_dict: dict[str, str], level: int) -> TocItem:
        key = toc_dict.get("guid") or toc_dict.get("docname")
        if key is None:
            raise CourseLoadError(f"Course configuration file contains a toc item without guid or docname.")
        title = toc_dict.get("title")
        if title is None:
            raise CourseLoadError(f"Course configuration file contains a toc item without title.")
        item = TocItem(level=level, key=key, title=title, child_items={})
        if "children" in toc_dict:
            for child_toc_dict in toc_dict["children"]:
                child_item = load_toc_item(child_toc_dict, level+1)
                item.child_items[child_item.key] = child_item
        return item
    
    root_item = load_toc_item(root_toc_dict, 0)
    course_json = CourseContent(course_key=course_key, root_toc_item=root_item, 
                                    html_fs=html_fs)
    return course_json

def course_from_index_yaml(html_fs: FileSet) -> None:
        petljadoc_config = html_fs.read_yaml("index.yaml")
        if petljadoc_config is None:
            return None
        if "title" not in petljadoc_config:
            raise CourseLoadError(f"Course configuration file does not contain title.")
        if "courseId" not in petljadoc_config:
            raise CourseLoadError(f"Course configuration file does not contain courseId.")
        title = petljadoc_config["title"]
        course_key = petljadoc_config["courseId"]
        root_toc_item = TocItem(level=0, key="index", title=title, child_items={})

        lessons = petljadoc_config.get("lessons")
        if lessons is None:
            raise CourseLoadError(f"Course configuration file does not contain lessons.")
        for lesson in lessons:
            lesson_title = lesson.get("title")
            lesson_key = lesson.get("guid")
            if lesson_key is None:
                raise CourseLoadError(f"Lesson {lesson_title} does not contain guid.")
            lesson_item = TocItem(level=1, key=lesson_key, title=lesson_title, child_items={})
            root_toc_item.child_items[lesson_key] = lesson_item
            activities = lesson.get("activities")
            if activities is None:
                raise CourseLoadError(f"Lesson {lesson_title} does not contain activities.")
            for activity in activities:
                activity_title = activity.get("title")
                activity_key = activity.get("guid")
                if activity_key is None:
                    raise CourseLoadError(f"Activity {activity_title} does not contain guid.")
                activity_item = TocItem(level=2, key=activity_key, title=activity_title, child_items={})
                lesson_item.child_items[activity_key] = activity_item
        course_content = CourseContent(course_key=course_key, root_toc_item=root_toc_item,
                                        html_fs=html_fs)
        return course_content





         