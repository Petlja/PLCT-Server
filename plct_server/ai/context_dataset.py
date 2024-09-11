import glob
import hashlib
import io
import json
import logging
import os
from dataclasses import dataclass
import re
import openai
from pydantic import BaseModel
import zstandard as zstd

from ..content.fileset import FileSet, LocalFileSet
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
    toc_text_path : str
    activities: dict[str, ActivitySummary]

class ChunkMetadata(BaseModel):
    course_key: str
    activity_key: str
    course_title: str
    lesson_title: str
    activity_title: str

class ContextDatasetBuilder:
    base_dir: str
    
    course_dict: dict[str, CourseSummary]

    def __init__(self, base_dir: str):
        self.base_dir = base_dir
        self.course_dict = {}

    def add_course(self, *, course_key: str, course_title: str, summary_text, toc_str:str, db_id: int = None):
        course_summary = CourseSummary(
            course_key=course_key, db_id=db_id, title=course_title,
            summary_text_path="summaries/course-summary.txt",
            toc_text_path="summaries/course-toc.txt", activities={})
        self.course_dict[course_key] = course_summary
        summary_text_path = os.path.join(self.base_dir, course_key, course_summary.summary_text_path)
        toc_text_path = os.path.join(self.base_dir, course_key, course_summary.toc_text_path)
        os.makedirs(os.path.dirname(summary_text_path), exist_ok=True)
        write_str(summary_text_path, summary_text)
        write_str(toc_text_path, toc_str)
        
    
    def add_activity(self,*, course_key: str, activity_key: str, activity_title: str, summary_text_rel_path: str, summary_text: str):
        if course_key not in self.course_dict:
            raise ValueError(f"Course {course_key} not found")
        summary_text_path = os.path.join(self.base_dir, course_key, summary_text_rel_path)
        os.makedirs(os.path.dirname(summary_text_path), exist_ok=True)
        write_str(summary_text_path, summary_text)
        activity_summary = ActivitySummary(title=activity_title, summary_text_path=summary_text_rel_path)
        self.course_dict[course_key].activities[activity_key] = activity_summary
        

    def add_chunck(self, chunk_text: str, chunk_meta: ChunkMetadata, 
                     embeding_model:str, embeding_sizes: list[int]):
        str_for_hash = "\n".join([chunk_meta.course_key, chunk_text]).encode('utf-8')
        chunk_hash = hashlib.sha256(str_for_hash).hexdigest()
        logger.info(f"Hash: {chunk_hash}, TextLengt: {len(chunk_text)}")
        hash_prefix = chunk_hash[:2]
        chunk_dir = os.path.join(self.base_dir, "chunks", hash_prefix)
        os.makedirs(chunk_dir, exist_ok=True)
        chunk_text_path = os.path.join(chunk_dir, f"{chunk_hash}.txt")
        metadata_path = os.path.join(chunk_dir, f"{chunk_hash}.json")
        if not os.path.exists(chunk_text_path):
            write_str(chunk_text_path, chunk_text)
            chunk_meta_json_str = chunk_meta.model_dump_json(indent=2)
            write_str(metadata_path, chunk_meta_json_str)
        oa_cln = openai.AzureOpenAI(
            azure_endpoint = "https://petljaopenaiservicev2.openai.azure.com", 
            api_key= OPENAI_API_KEY,  
            api_version="2023-05-15",
            azure_deployment= 'text-embedding-3-large'
        )
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

    def flush_changes(self):
        for course_key, course_summary in self.course_dict.items():
            json_file = os.path.join(self.base_dir, course_key, "summary.json")
            course_summary_json = course_summary.model_dump_json(indent=2)
            write_str(json_file, course_summary_json)

    def update_index(self):
        course_keys = []
        cpurse_pattern = os.path.join(self.base_dir, "*/summary.json")
        for json_path in glob.glob(cpurse_pattern):
            if os.path.isfile(json_path):
                course_summary = CourseSummary.model_validate_json(read_str(json_path))
                course_keys.append(course_summary.course_key)

        chunk_embedding_pattern = os.path.join(self.base_dir, 
                f'chunks/*/*-*.json')

        chunk_dict = {}
        for path in glob.glob(chunk_embedding_pattern):
            filename = os.path.basename(path)
            dirname = os.path.dirname(path)
            chunk_hash = filename[:64]
            embedding_type = filename[65:].split('.')[0]

            emb_data = chunk_dict.get(embedding_type)
            if emb_data is None:
                emb_data = {
                    "ids":[], 
                    "embeddings":[], 
                    "metadatas":[] }
                chunk_dict[embedding_type] = emb_data

            emb_data["ids"].append(chunk_hash)
            embeding = read_json(path)
            emb_data["embeddings"].append(embeding)
            metadata_path = os.path.join(dirname, f"{chunk_hash}.json")
            metadata = read_json(metadata_path)
            emb_data["metadatas"].append(metadata)

        index = {
            "courses": course_keys,
            "emb_types": list(chunk_dict.keys())
        }

        index_path = os.path.join(self.base_dir, "index.json")
        write_str(index_path, json.dumps(index, indent=2))
        for embedding_type, emb_data in chunk_dict.items():
            emb_path = os.path.join(self.base_dir, f"emb-{embedding_type}.json.zst")
            emb_str = json.dumps(emb_data, indent=2,
                                    separators=(',', ': '))
            logger.info(embedding_type)
            emb_str = re.sub(r'(?<=\d,)\s+|(?<=\d)\s+|(?<=\[)\s+(?=[\d-])', '', emb_str)
            with zstd.open(emb_path, 'wt', encoding='utf-8') as f:
                f.write(emb_str)


class ContextDataset:
    fs: FileSet
    course_dict: dict[str, CourseSummary]
    loaded_index: dict

    def __init__(self, base_url: str):
        self.fs = FileSet.from_base_url(base_url)
        self.course_dict = {}
        self.loaded_index = self.fs.read_json("index.json")
        for course_key in self.loaded_index["courses"]:
            summary_str = self.fs.read_str(f"{course_key}/summary.json")
            course_summary = CourseSummary.model_validate_json(summary_str)
            self.course_dict[course_summary.course_key] = course_summary

    def get_embeddings_data(self, embedding_model, embedding_size) -> tuple[list[list[float]], list[str], list[dict]]:
        embedding_type = f"{embedding_model}-{embedding_size}"
        emb_path = f"emb-{embedding_type}.json.zst"
        b = self.fs.read_bytes(emb_path)
        with zstd.open(io.BytesIO(b), 'rt', encoding="utf-8") as f:
           emb_str = f.read()
        b = None
        emb_data = json.loads(emb_str)
        embeddings= emb_data["embeddings"]
        ids= emb_data["ids"]
        metadatas= emb_data["metadatas"]
        return embeddings, ids, metadatas
    
    def get_summary_texts(self, course_key: str, activity_key:str) -> tuple[str,str]:
        course_summary = self.course_dict.get(course_key)
        if course_summary is None:
            return None, None
        logger.debug(f"course_summary: {course_summary}")
        activity_summary = course_summary.activities.get(activity_key)
        if activity_summary is None:
            return None, None
        course_summary_path = f"{course_key}/{course_summary.summary_text_path}"
        course_summary_txt = self.fs.read_str(course_summary_path)
        activity_summary_path =  f"{course_key}/{activity_summary.summary_text_path}"
        activity_summary_txt = self.fs.read_str(activity_summary_path)
        return course_summary_txt, activity_summary_txt
    
    def get_toc_text(self, course_key: str) -> str:
        course_summary = self.course_dict.get(course_key)
        if course_summary is None:
            return None
        course_toc_path = f"{course_key}/{course_summary.toc_text_path}"
        course_toc_txt = self.fs.read_str(course_toc_path)
        return course_toc_txt

    def get_chunk_text(self, chunk_hash: str) -> str:
        hash_prefix = chunk_hash[:2]
        chunk_path = f'chunks/{hash_prefix}/{chunk_hash}.txt'
        chunk_str=self.fs.read_str(chunk_path)
        return chunk_str

