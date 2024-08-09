import json
import logging
import os
import glob
from typing import AsyncIterator, Optional, Tuple
import chromadb
from openai import AsyncOpenAI, OpenAI
from pydantic import BaseModel

from plct_server.content.fileset import FileSet
from .context_dataset import ContextDataset
from . import OPENAI_API_KEY

from .prompt_templates import ( 
    preprocess_system_message_template, system_message_template, 
    system_message_summay_template, system_message_rag_template,
    preprocess_user_message_template, compare_prompt)

logger = logging.getLogger(__name__)

ai_engine: "AiEngine" = None

def init(base_url: str):
    global ai_engine
    if ai_engine is None:
        ai_engine = AiEngine(base_url)
    else:
        raise ValueError(f"{__name__} already initialized")
    

def get_ai_engine() -> "AiEngine":
    global ai_engine
    if ai_engine is None:
        raise ValueError(f"{__name__} not initialized, call {__name__}.init first")
    return ai_engine

class QueryMetadata(BaseModel):
    activity_key: str
    activity_title: str
    system_message : Optional[str] = None

EMBEDING_SIZE = 1536
EMBEDING_MODEL = "text-embedding-3-small"
CHROMADB_COLLECTION_NAME = f"{EMBEDING_MODEL}-{EMBEDING_SIZE}"

class AiEngine:
    def __init__(self, base_url: str):
        logger.debug(f"ai_context_dir: {base_url}")
        self.ctx_data = ContextDataset(base_url)
        self.ch_cli = chromadb.Client()
        #self.course_summaries: dict[str,CourseSummary] = {}
        self._load_embeddings()
        #self._load_course_summaries()

    def _load_embeddings(self):
        collection = self.ch_cli.create_collection(
            name=f"{CHROMADB_COLLECTION_NAME}",
            metadata={"hnsw:space": "ip"})

        logger.debug(f"Loading embeddings {EMBEDING_MODEL}-{EMBEDING_SIZE}")
        embeddings, ids, metadatas = self.ctx_data.get_embeddings_data(EMBEDING_MODEL, EMBEDING_SIZE)

        max_batch_size = self.ch_cli.max_batch_size
        total_size = len(embeddings)
        
        for start_idx in range(0, total_size, max_batch_size):
            end_idx = min(start_idx + max_batch_size, total_size)
            
            batch_embeddings = embeddings[start_idx:end_idx]
            batch_ids = ids[start_idx:end_idx]
            batch_metadatas = metadatas[start_idx:end_idx]
            
            logger.debug(f"Indexing embeddings {EMBEDING_MODEL}-{EMBEDING_SIZE} for batch {start_idx} to {end_idx}")
            collection.add(
                embeddings=batch_embeddings,
                ids=batch_ids,
                metadatas=batch_metadatas
            )

        logger.debug(f"Embeddings loaded and indexed {EMBEDING_MODEL}-{EMBEDING_SIZE}")

    async def preprocess_query(self, history: list[tuple[str,str]], qyery: str, course_key: str, activity_key: str) -> str:
        course_summary, lesson_summary = self.ctx_data.get_summary_texts(
            course_key, activity_key)
        
        system_message = preprocess_system_message_template.format(
            course_summary=course_summary,
            lesson_summary=lesson_summary
        )

        preprocessed_user_message = preprocess_user_message_template.format(
            user_input=qyery
        )

        messages=[{"role": "system", "content": system_message}]
        for item in history:
            messages.append({"role": "user", "content": item[0]})
            messages.append({"role": "assistant", "content": item[1]})
        messages.append({"role": "user", "content": preprocessed_user_message})
    
        client = AsyncOpenAI(api_key = OPENAI_API_KEY)

        completion = await client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=messages,
            stream=False,
            max_tokens=1000,
            temperature=0
        )

        preprocessed_user_message = qyery + '\n' + completion.choices[0].message.content
        logger.debug(f"preprocessed_query: {preprocessed_user_message}")
        return preprocessed_user_message
    
    async def make_system_message(self, history: list[tuple[str,str]], qyery: str, course_key: str, activity_key: str) -> Tuple[str, QueryMetadata]:    
        preprocessed_query = await self.preprocess_query(history, qyery, course_key, activity_key)
        
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
            where={"course_key": course_key},
            n_results=2)

        chunk_strs = []
        query_metadata : QueryMetadata = None

        for chunk_hash, dist, metadata in zip(result["ids"][0], result["distances"][0], result["metadatas"][0]):
            query_metadata = QueryMetadata(
                activity_key=metadata["activity_key"],
                activity_title=metadata["activity_title"],
            )
            chunk_str = self.ctx_data.get_chunk_text(chunk_hash)
            chunk_strs.append(chunk_str)

        rag_segment = system_message_rag_template.format(
            chunks='\n\n'.join(chunk_strs)
        )

        system_message = system_message_template + summary_segment + rag_segment
        query_metadata.system_message = system_message

        return system_message, query_metadata

    async def generate_answer(self,*, history: list[tuple[str,str]], query: str,
                            course_key: str, activity_key: str) -> AsyncIterator[int]:
        
        system_message, _ = await self.make_system_message(history, query, course_key, activity_key)
        
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
    
    async def generate_answer_with_info(self, *, history: list[tuple[str, str]], query: str,
                                    course_key: str, activity_key: str) -> tuple[AsyncIterator[int], dict[str,str]]:
    
        system_message_result, metadata= await self.make_system_message(history, query, course_key, activity_key)
        
        messages = [{"role": "system", "content": system_message_result}]
        for item in history:
            messages.append({"role": "user", "content": item[0]})
            messages.append({"role": "assistant", "content": item[1]})
        messages.append({"role": "user", "content": query})

        client = AsyncOpenAI(api_key=OPENAI_API_KEY)
        
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

        return answer_generator(), metadata


    async def compare_strings(self, response_text: str, benchmark_text: str) -> int:
        client = AsyncOpenAI(api_key=OPENAI_API_KEY)

        messages = [
            {"role": "system", "content": "Given the following answers to the same question, compare them based on the accuracy and completeness of the information they convey. The goal is to assess how well the key concepts, facts, and details are preserved across the different responses. The comparison should focus on the transferred information, not on the exact wording used. Please provide a similarity score or qualitative assessment of how closely the information in these answers aligns. Your answer should be a single number representing the similarity score, where 0 means the information is completely different and 5 means the information is very similar."},
            {"role": "user", "content": compare_prompt.format(current_text=response_text, benchmark_text=benchmark_text)}
        ]

        completion = await client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=messages,
            stream=False,
            max_tokens=50,
            temperature=0
        )

        response = completion.choices[0].message.content.strip()

        try:
            similarity_score = int(response)
        except ValueError:
            similarity_score = -1 
        return similarity_score