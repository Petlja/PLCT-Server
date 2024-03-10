import glob
import hashlib
import json
import logging
import os
from dataclasses import dataclass
import openai
from pydantic import BaseModel
from ..ioutils import read_json, read_str, write_str
from . import OPENAI_API_KEY

logger = logging.getLogger(__name__)

class ActivitySummary(BaseModel):
    title: str
    summary_text_path: str

class CourseSummary(BaseModel):
    course_key: str
    db_id: int = None
    title: str
    summary_text_path: str
    activities: dict[str, ActivitySummary]

class ChunkMetadata(BaseModel):
    course_key: str
    activity_key: str
    course_title: str
    lesson_title: str
    activity_title: str

class ContextDataset:
    base_path: str
    course_dict: dict[str, CourseSummary]

    def __init__(self, base_path: str, *, load: bool = False):
        self.base_path = base_path
        self.course_dict = {}
        if load:
            pattern = self._course_metadata_path('*')
            for json_path in glob.glob(pattern):
                if os.path.isfile(json_path):
                    course_summary = CourseSummary.model_validate_json(read_str(json_path))
                    self.course_dict[course_summary.course_key] = course_summary

    def _course_metadata_path(self, course_key: str):
        path = os.path.join(self.base_path, course_key,"summary.json")
        return path

    # Dataset creation API

    def store_course(self, *, course_key: str, course_title: str, summary_text, db_id: int = None):
        course_summary = CourseSummary(
            course_key=course_key, db_id=db_id, title=course_title,
            summary_text_path="summaries/course-summary.txt", activities={})
        self.course_dict[course_key] = course_summary
        summary_text_path = os.path.join(self.base_path, course_key, course_summary.summary_text_path)
        os.makedirs(os.path.dirname(summary_text_path), exist_ok=True)
        write_str(summary_text_path, summary_text)
        
    
    def store_activity(self,*, course_key: str, activity_key: str, activity_title: str, summary_text_rel_path: str, summary_text: str):
        if course_key not in self.course_dict:
            raise ValueError(f"Course {course_key} not found")
        summary_text_path = os.path.join(self.base_path, course_key, summary_text_rel_path)
        os.makedirs(os.path.dirname(summary_text_path), exist_ok=True)
        write_str(summary_text_path, summary_text)
        activity_summary = ActivitySummary(title=activity_title, summary_text_path=summary_text_rel_path)
        self.course_dict[course_key].activities[activity_key] = activity_summary
        

    def store_chunck(self, chunk_text: str, chunk_meta: ChunkMetadata, 
                     embeding_model:str, embeding_sizes: list[int]):
        chunk_hash = hashlib.sha256(chunk_text.encode('utf-8')).hexdigest()
        logger.info(f"Hash: {chunk_hash}, TextLengt: {len(chunk_text)}")
        hash_prefix = chunk_hash[:2]
        chunk_dir = os.path.join(self.base_path, "chunks", hash_prefix)
        os.makedirs(chunk_dir, exist_ok=True)
        chunk_text_path = os.path.join(chunk_dir, f"{chunk_hash}.txt")
        metadata_path = os.path.join(chunk_dir, f"{chunk_hash}.json")
        if not os.path.exists(chunk_text_path):
            write_str(chunk_text_path, chunk_text)
            chunk_meta_json_str = chunk_meta.model_dump_json(indent=2)
            write_str(metadata_path, chunk_meta_json_str)
        oa_cln = openai.OpenAI(api_key = OPENAI_API_KEY)
        for embeding_size in embeding_sizes:
            embeding_path = os.path.join(chunk_dir, f"{chunk_hash}-{embeding_model}-{embeding_size}.json")
            if not os.path.exists(embeding_path):
                response = oa_cln.embeddings.create(
                    input=chunk_text,
                    model=embeding_model,
                    dimensions=embeding_size,
                    encoding_format="float")
                embeding = response.data[0].embedding
                embeding_json_str = json.dumps(embeding)
                write_str(embeding_path, embeding_json_str)

    def flush_metadata(self):
        for course_key, course_summary in self.course_dict.items():
            json_file = self._course_metadata_path(course_key)
            course_summary_json = course_summary.model_dump_json(indent=2)
            write_str(json_file, course_summary_json)

    # Dataset retrieval API

    def get_embeddings_data(self, embedding_model, embedding_size) -> tuple[list[list[float]], list[str], list[dict]]:
        chunk_embedding_pattern = os.path.join(self.base_path, 
                f'chunks/*/*-{embedding_model}-{embedding_size}.json')
        #logger.debug(f"chunk_embedding_pattern: {chunk_embedding_pattern}") 
        embeddings=[]
        ids=[]
        metadatas=[]
        for path in glob.glob(chunk_embedding_pattern):
            filename = os.path.basename(path)
            dirname = os.path.dirname(path)
            chunk_hash = filename[:64]
            embeding = read_json(path)
            embeddings.append(embeding)
            chunk_meta = read_json(os.path.join(dirname, f"{chunk_hash}.json"))
            metadatas.append(chunk_meta)
            ids.append(chunk_hash)
        return embeddings, ids, metadatas
    
    def get_summary_texts(self, course_key: str, activity_key:str) -> tuple[str,str]:
        course_summary = self.course_dict.get(course_key)
        if course_summary is None:
            return None, None
        logger.debug(f"course_summary: {course_summary}")
        activity_summary = course_summary.activities.get(activity_key)
        if activity_summary is None:
            return None, None
        summary_base_dir = os.path.join(self.base_path, course_key)
        course_summary_path = os.path.join(
            summary_base_dir, course_summary.summary_text_path)
        course_summary_txt = read_str(course_summary_path)
        activity_summary_path = os.path.join(summary_base_dir, activity_summary.summary_text_path)
        activity_summary_txt = read_str(activity_summary_path)
        return course_summary_txt, activity_summary_txt
    
    def get_chunk_text(self, chunk_hash: str) -> str:
        hash_prefix = chunk_hash[:2]
        chunk_path = os.path.join(self.base_path, f'chunks/{hash_prefix}/{chunk_hash}.txt')
        chunk_str=read_str(chunk_path)
        return chunk_str

