import json
import logging
import os
import glob
from typing import AsyncIterator
import chromadb
from openai import AsyncOpenAI, OpenAI
from pydantic import BaseModel
from .context_dataset import ContextDataset
from . import OPENAI_API_KEY

from .prompt_templates import ( 
    preprocess_system_message_template, system_message_template, 
    system_message_summay_template, system_message_rag_template,
    preprocess_user_message_template)

logger = logging.getLogger(__name__)

ai_engine: "AiEngine" = None

def init(ai_context_dir: str):
    global ai_engine
    if ai_engine is not None:
        raise ValueError(f"{__name__} already initialized")
    ai_engine = AiEngine(ai_context_dir)

def get_ai_engine() -> "AiEngine":
    global ai_engine
    if ai_engine is None:
        raise ValueError(f"{__name__} not initialized, call {__name__}.init first")
    return ai_engine

EMBEDING_SIZE = 256
EMBEDING_MODEL = "text-embedding-3-small"
CHROMADB_COLLECTION_NAME = f"{EMBEDING_MODEL}-{EMBEDING_SIZE}"

class AiEngine:
    def __init__(self, ai_context_dir: str):
        logger.debug(f"ai_context_dir: {ai_context_dir}")
        self.ctx_data = ContextDataset(ai_context_dir, load=True)
        self.ch_cli = chromadb.Client()
        #self.course_summaries: dict[str,CourseSummary] = {}
        self._load_embeddings()
        #self._load_course_summaries()

    def _load_embeddings(self):
        collection = self.ch_cli.create_collection(
            name=f"{CHROMADB_COLLECTION_NAME}",
            metadata={"hnsw:space": "ip"})

        embeddings, ids, metadatas = self.ctx_data.get_embeddings_data(EMBEDING_MODEL, EMBEDING_SIZE)

        collection.add(
            embeddings=embeddings,
            ids=ids,
            metadatas=metadatas
        )

    async def preprocess_query(self, qyery: str, course_key: str, activity_key: str) -> str:
        course_summary, lesson_summary = self.ctx_data.get_summary_texts(
            course_key, activity_key)
        system_message = preprocess_system_message_template.format(
            course_summary=course_summary,
            lesson_summary=lesson_summary
        )

        preprocessed_query = preprocess_user_message_template.format(
            user_input=qyery
        )
        messages=[{"role": "system", "content": system_message},
              {"role": "user", "content": preprocessed_query}]
    
        client = AsyncOpenAI(api_key = OPENAI_API_KEY)

        completion = await client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=messages,
            stream=False,
            max_tokens=1000,
            temperature=0
        )

        preprocessed_query = qyery + '\n' + completion.choices[0].message.content
        logger.debug(f"preprocessed_query: {preprocessed_query}")
        return preprocessed_query
    
    async def make_system_message(self, qyery: str, course_key: str, activity_key: str) -> str:
        preprocessed_query = await self.preprocess_query(qyery, course_key, activity_key)
        
        course_summary, lesson_summary = self.ctx_data.get_summary_texts(course_key, activity_key)

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
            chunk_str = self.ctx_data.get_chunk_text(chunk_hash)
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

