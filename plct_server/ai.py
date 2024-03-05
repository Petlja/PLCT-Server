import json
import logging
import os
import glob
from typing import AsyncIterator
import chromadb
from openai import AsyncOpenAI, OpenAI
from pydantic import BaseModel

from .ai_templates import ( 
    preprocess_system_message_template, system_message_template, 
    system_message_summay_template, system_message_rag_template)

logger = logging.getLogger(__name__)

OPENAI_API_KEY = os.environ["CHATAI_OPENAI_API_KEY"]

class ActivitySummary(BaseModel):
    title: str
    summary_path: str

class ChunkMetadata(BaseModel):
    course_key: str
    activity_key: str
    course_title: str
    lesson_title: str
    activity_title: str

class CourseSummary(BaseModel):
    course_key: str
    db_id: int = None
    title: str
    sumary_path: str
    activities: dict[str, ActivitySummary]

ai_engine: "AiEngine" = None

def init(ai_context_dir: str):
    global ai_engine
    if ai_engine is not None:
        raise ValueError(f"{__name__} already initialized")
    ai_engine = AiEngine(ai_context_dir)

def get_engine() -> "AiEngine":
    global ai_engine
    if ai_engine is None:
        raise ValueError(f"{__name__} not initialized, call {__name__}.init first")
    return ai_engine

EMBEDING_SIZE = 256
EMBEDING_MODEL = "text-embedding-3-small"
CHROMADB_COLLECTION_NAME = f"{EMBEDING_MODEL}-{EMBEDING_SIZE}"

class AiEngine:
    def __init__(self, ai_context_dir: str):
        self.ai_context_dir = ai_context_dir
        self.ch_cli = chromadb.Client()
        self.course_summaries: dict[str,CourseSummary] = {}
        self._load_embeddings()
        self._load_course_summaries()

    def _load_embeddings(self):
        collection = self.ch_cli.create_collection(
            name=f"{CHROMADB_COLLECTION_NAME}",
            metadata={"hnsw:space": "ip"})
        embedings=[]
        ids=[]
        metadatas=[]

        chunk_embedding_pattern = os.path.join(self.ai_context_dir, 
                        f'chunks/*/*-{EMBEDING_MODEL}-{EMBEDING_SIZE}.json')
        #logger.debug(f"chunk_embedding_pattern: {chunk_embedding_pattern}") 
        for path in glob.glob(chunk_embedding_pattern):
            filename = os.path.basename(path)
            dirname = os.path.dirname(path)
            chunk_hash = filename[:64]
            with open(path, 'r') as f:
                embeding = json.load(f)
            embedings.append(embeding)
            with open(os.path.join(dirname, f"{chunk_hash}.json"), 'r', encoding='utf8') as f:
                chunk_meta = json.load(f)
            metadatas.append(chunk_meta)
            ids.append(chunk_hash)

        collection.add(
            embeddings=embedings,
            ids=ids,
            metadatas=metadatas
        )

    def _load_course_summaries(self):
        course_summary_pattern = os.path.join(self.ai_context_dir, "*/summary.json")
        for path in glob.glob(course_summary_pattern):
            course_dir = os.path.dirname(path)
            course_key = os.path.basename(course_dir)
            with open(path, 'r', encoding='utf8') as file:
                course_summary_txt = file.read()
            course_summary = CourseSummary.model_validate_json(course_summary_txt)
            assert course_summary.course_key == course_key
            self.course_summaries[course_key] = course_summary
    
    def get_summary_txt(self, course_key: str, activity_key:str) -> tuple[str,str]:
        course_summary = self.course_summaries.get(course_key)
        if course_summary is None:
            return None, None
        activity_summary = course_summary.activities.get(activity_key)
        if activity_summary is None:
            return None, None
        summary_base_dir = os.path.join(self.ai_context_dir, course_key)
        course_summary_path = os.path.join(summary_base_dir, course_summary.sumary_path)
        with open(course_summary_path, 'r', encoding='utf8') as file:
            course_summary_txt = file.read()
        activity_summary_path = os.path.join(summary_base_dir, activity_summary.summary_path)
        with open(activity_summary_path, 'r', encoding='utf8') as file:
            activity_summary_txt = file.read()
        return course_summary_txt, activity_summary_txt
    
    async def preprocess_query(self, qyery: str, course_key: str, activity_key: str) -> str:
        course_summary, lesson_summary = self.get_summary_txt(course_key, activity_key)
        system_message = preprocess_system_message_template.format(
            course_summary=course_summary,
            lesson_summary=lesson_summary
        )

        messages=[{"role": "system", "content": system_message},
              {"role": "user", "content": qyery}]
    
        client = AsyncOpenAI(api_key = OPENAI_API_KEY)

        completion = await client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=messages,
            stream=False,
            max_tokens=1000,
            temperature=0
        )

        preprocessed_query = qyery + '\n' + completion.choices[0].message.content
        return preprocessed_query
    
    async def make_system_message(self, qyery: str, course_key: str, activity_key: str) -> str:
        preprocessed_query = await self.preprocess_query(qyery, course_key, activity_key)
        
        course_summary, lesson_summary = self.get_summary_txt(course_key, activity_key)

        if course_summary is None or lesson_summary is None:
            summary_segment = ""
        else:
            summary_segment = system_message_summay_template.format(
                course_summary=course_summary,
                lesson_summary=lesson_summary
            )

        client = AsyncOpenAI(api_key = OPENAI_API_KEY)

        response = await client.embeddings.create(
            model=EMBEDING_MODEL,
            input=preprocessed_query,
            encoding_format="float",
            dimensions = EMBEDING_SIZE
        )

        query_embedding = response.data[0].embedding

        collection = self.ch_cli.get_collection(CHROMADB_COLLECTION_NAME)

        result =collection.query(
            query_embeddings=[query_embedding],
            n_results=2)

        chunk_strs = []
        for chunk_hash, dist, metadata in zip(result["ids"][0], result["distances"][0], result["metadatas"][0]):
            hash_prefix = chunk_hash[:2]
            chunk_path = os.path.join(self.ai_context_dir, f'chunks/{hash_prefix}/{chunk_hash}.txt')
            with open(chunk_path, 'r', encoding='utf8') as file:
                chunk_str = file.read()
            chunk_strs.append(chunk_str)

        rag_segment = system_message_rag_template.format(
            chunks='\n\n'.join(chunk_strs)
        )

        system_message = system_message_template + summary_segment + rag_segment

        return system_message

    async def generate_answer(self,*, history: list[tuple[str,str]], query: str,
                            course_key: str, activity_key: str) -> AsyncIterator[int]:
        
        system_message = await self.make_system_message(query, course_key, activity_key)
        
        messages=[{"role": "system", "content": system_message}]

        for item in history:
            messages.append({"role": "user", "content": item[0]})
            messages.append({"role": "assistant", "content": item[1]})
        messages.append({"role": "user", "content": query})

        client =  AsyncOpenAI(api_key = OPENAI_API_KEY)
        
        completion = await client.chat.completions.create(
            model="gpt-4-0125-preview",
            messages=messages,
            stream=True,
            max_tokens=2000,
            temperature=0
        )
    
        async def answer_generator():
            async for chunk in completion:
                yield chunk.choices[0].delta.content or ""

        return answer_generator()

        
                




 


