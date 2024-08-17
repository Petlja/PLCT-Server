
import logging
import chromadb

from typing import AsyncIterator, Optional
from openai import AsyncAzureOpenAI
from pydantic import BaseModel

from .context_dataset import ContextDataset
from . import OPENAI_API_KEY

from .prompt_templates import ( 
    preprocess_system_message_template, system_message_template, 
    system_message_summary_template, system_message_rag_template,
    preprocess_user_message_template, system_message_condensed_history_template,
    compare_prompt, system_compare_template, condensed_history_template,
    new_condensed_history_template, no_condensed_history_template)

AZURE_ENDPOINT = "https://petljaopenaiservice.openai.azure.com"
API_VERSION = "2024-06-01"
MAX_HISTORY_LENGTH = 1

class QueryContext(BaseModel):
    chunk_metadata : list[dict[str,str]] = []
    system_message : str = ""

    def clear(self):
        self.activity_key.clear()
        self.activity_title.clear()
        self.system_message = ""
    
    def add_chunk_metadata(self, chunk_metadata: dict[str,str], distance: float):
        chunk_metadata["distance"] = str(distance)
        self.chunk_metadata.append(chunk_metadata)

    def get_all_chunk_activity_key(self) -> str:
        return [item["activity_key"] for item in self.chunk_metadata]
    
    
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

EMBEDDING_SIZE = 1536
EMBEDDING_MODEL = "text-embedding-3-small"
CHROMADB_COLLECTION_NAME = f"{EMBEDDING_MODEL}-{EMBEDDING_SIZE}"


class AiEngine:
    def __init__(self, base_url: str):
        logger.debug(f"ai_context_dir: {base_url}")
        self.ctx_data = ContextDataset(base_url)
        self.ch_cli = chromadb.Client()
        self.query_context = QueryContext()
        self._load_embeddings()

    def _load_embeddings(self):
        collection = self.ch_cli.create_collection(
            name=f"{CHROMADB_COLLECTION_NAME}",
            metadata={"hnsw:space": "ip"})

        logger.debug(f"Loading embeddings {EMBEDDING_MODEL}-{EMBEDDING_SIZE}")
        embeddings, ids, metadata = self.ctx_data.get_embeddings_data(EMBEDDING_MODEL, EMBEDDING_SIZE)

        max_batch_size = self.ch_cli.max_batch_size
        total_size = len(embeddings)
        logger.debug(f"Indexing embeddings {EMBEDDING_MODEL}-{EMBEDDING_SIZE} in batches of {max_batch_size}")
        for start_idx in range(0, total_size, max_batch_size):
            end_idx = min(start_idx + max_batch_size, total_size)
            
            batch_embeddings = embeddings[start_idx:end_idx]
            batch_ids = ids[start_idx:end_idx]
            batch_metadata = metadata[start_idx:end_idx]
            
            logger.debug(f"Finished loading embeddings in batch ({start_idx}-{end_idx})")
            collection.add(
                embeddings=batch_embeddings,
                ids=batch_ids,
                metadatas=batch_metadata
            )

        logger.debug(f"Embeddings loaded and indexed {EMBEDDING_MODEL}-{EMBEDDING_SIZE}")

    def _get_async_azure_openai_client(self) -> AsyncAzureOpenAI:
        return AsyncAzureOpenAI(
            azure_endpoint=AZURE_ENDPOINT,
            api_key=OPENAI_API_KEY,
            api_version=API_VERSION
        )
    #creates a more elaborated request using query, condensed history and latest history
    async def preprocess_query(self, history: list[tuple[str,str]], query: str, course_key: str, activity_key: str, condensed_history: str) -> str:
      
        course_summary, lesson_summary = self.ctx_data.get_summary_texts(
            course_key, activity_key)
        
        if condensed_history == "":
            condensed_history = no_condensed_history_template
        
        system_message = preprocess_system_message_template.format(
            course_summary=course_summary,
            lesson_summary=lesson_summary,
            condensed_history = condensed_history
        )

        preprocessed_user_message = preprocess_user_message_template.format(
            user_input=query
        )

        messages=[{"role": "system", "content": system_message}]
        for item in history:
            messages.append({"role": "user", "content": item[0]})
            messages.append({"role": "assistant", "content": item[1]})
        messages.append({"role": "user", "content": preprocessed_user_message})
    
        client = self._get_async_azure_openai_client()

        completion = await client.chat.completions.create(
            model="gpt-35-turbo",
            messages=messages,
            stream=False,
            max_tokens=1000,
            temperature=0
        )

        preprocessed_user_message = query + '\n' + completion.choices[0].message.content
        logger.debug(f"preprocessed_query: {preprocessed_user_message}")
        return preprocessed_user_message
    
    async def make_system_message(self, history: list[tuple[str,str]], qyery: str,
                                   course_key: str, activity_key: str, condensed_history: str) -> str:
        
        preprocessed_query = await self.preprocess_query(history, qyery, course_key, activity_key, condensed_history)
        
        course_summary, lesson_summary = self.ctx_data.get_summary_texts(course_key, activity_key)

        if course_summary is None or lesson_summary is None:
            summary_segment = ""
        else:
            summary_segment = system_message_summary_template.format(
                course_summary=course_summary,
                lesson_summary=lesson_summary
            )

        if condensed_history != "":
            condensed_segment = system_message_condensed_history_template.format(
                condensed_history=condensed_history
            )
        else:
            condensed_segment = no_condensed_history_template


        client = self._get_async_azure_openai_client()

        response = await client.embeddings.create(
            model='text-embedding-ada-002',
            input=preprocessed_query,
            encoding_format="float",
            dimensions = EMBEDDING_SIZE
        )

        query_embedding = response.data[0].embedding

        collection = self.ch_cli.get_collection(CHROMADB_COLLECTION_NAME)

        result =collection.query(
            query_embeddings=[query_embedding],
            where={"course_key": course_key},
            n_results=2)

        chunk_strs = []
        for chunk_hash, dist, metadata in zip(result["ids"][0], result["distances"][0], result["metadatas"][0]):
            self.query_context.add_chunk_metadata(metadata, dist)
            chunk_str = self.ctx_data.get_chunk_text(chunk_hash)
            chunk_strs.append(chunk_str)

        rag_segment = system_message_rag_template.format(
            chunks='\n\n'.join(chunk_strs)
        )

        system_message = system_message_template + summary_segment + condensed_segment + rag_segment

        self.query_context.system_message = system_message

        return system_message

    async def generate_answer(self,*, history: list[tuple[str,str]], query: str,
                            course_key: str, activity_key: str, condensed_history: str) -> AsyncIterator[int]:

        # If the history is too long, we only keep the last MAX_HISTORY_LENGTH items
        if (condensed_history != ""):
            history = history[-MAX_HISTORY_LENGTH:]
            
        system_message = await self.make_system_message(history, query, course_key, activity_key, condensed_history)
        
        messages=[{"role": "system", "content": system_message}]
        for item in history:
            messages.append({"role": "user", "content": item[0]})
            messages.append({"role": "assistant", "content": item[1]})
        messages.append({"role": "user", "content": query})

        client =  self._get_async_azure_openai_client()
        
        completion = await client.chat.completions.create(
            model="gpt-35-turbo",
            messages=messages,
            stream=True,
            max_tokens=2000,
            temperature=0
        )
    
        async def answer_generator():
            async for chunk in completion:
                if len(chunk.choices) > 0:
                    delta = chunk.choices[0].delta
                    if delta.content:
                        yield delta.content

        return answer_generator()
    
    async def generate_condensed_history(self, latestHistory: list[tuple[str,str]],
                                          condensed_history: str) -> str:
           
        if condensed_history != "":
            message = condensed_history_template.format(condensed_history=condensed_history,
                        latest_question=latestHistory[-1][0], latest_answer=latestHistory[-1][1])
        else:
            message = new_condensed_history_template.format(latestHistory[-2][0], latestHistory[-2][1],
                       latestHistory[-1][0], latestHistory[-1][1])   
            
        messages =[{"role": "user", "content": message}]

        client = self._get_async_azure_openai_client()

        completion = await client.chat.completions.create(
            model="gpt-35-turbo",
            messages=messages,
            stream=False,
            max_tokens=2000,
            temperature=0
        )

        return completion.choices[0].message.content
    
    async def compare_strings(self, response_text: str, benchmark_text: str) -> int:         
        compare_prompt_message = compare_prompt.format(
            current_text=response_text,
            benchmark_text=benchmark_text
        )

        messages = [
            {"role": "system", "content": system_compare_template},
            {"role": "user", "content": compare_prompt_message}
        ]

        client =  self._get_async_azure_openai_client()

        completion = await client.chat.completions.create(
            model="gpt-35-turbo",
            messages=messages,
            stream=False,
            max_tokens=50,
            temperature=0, 
        )

        response = completion.choices[0].message.content

        try:
            similarity_score = int(response)
        except ValueError:
            similarity_score = -1 
        return similarity_score
    

    def get_last_query_context(self):
        return self.query_context