
import logging
import chromadb
import tiktoken

from typing import AsyncIterator
from openai import AsyncAzureOpenAI
from pydantic import BaseModel
from tiktoken import Encoding
from .context_dataset import ContextDataset
from . import OPENAI_API_KEY

from .prompt_templates import ( 
    preprocess_system_message_template, system_message_template, 
    system_message_summary_template, system_message_rag_template,
    preprocess_user_message_template, system_message_condensed_history_template,
    compare_prompt, system_compare_template, condensed_history_template,
    new_condensed_history_template, condensed_history_template,
    preprocess_system_message_template_with_history, condensed_history_system)

    
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

def get_async_azure_openai_client() -> AsyncAzureOpenAI:
    return AsyncAzureOpenAI(
        azure_endpoint=AZURE_ENDPOINT,
        api_key=OPENAI_API_KEY,
        api_version=API_VERSION
    )

def create_message(system : str, history: list[dict[str, str]], query):
    messages = [{"role": "system", "content": system}]
    for item in history:
        messages.append({"role": "user", "content": item[0]})
        messages.append({"role": "assistant", "content": item[1]})
    messages.append({"role": "user", "content": query})
    return messages

CDB_EMBEDDING_SIZE = 1536
CDB_EMBEDDING_MODEL = "text-embedding-3-small"
CHROMADB_COLLECTION_NAME = f"{CDB_EMBEDDING_MODEL}-{CDB_EMBEDDING_SIZE}"
AZURE_MODEL_TOKEN_LIMIT = 8193
AZURE_ENDPOINT = "https://petljaopenaiservice.openai.azure.com"
API_VERSION = "2024-06-01"
MAX_HISTORY_LENGTH = 1
RESPONSE_MAX_TOKENS = 2000
PREPROCESS_QUERY_MAX_TOKENS = 1000
LLM_MODEL = "gpt-35-turbo"
LLM_EMBEDDING_MODEL = "text-embedding-ada-002"
class QueryError(Exception):
    pass

class QueryContext(BaseModel):
    chunk_metadata : list[dict[str,str]] = []
    system_message : str = ""
    token_size : dict[str,int] = {}

    def add_chunk_metadata(self, chunk_metadata: dict[str,str], distance: float):
        chunk_metadata["distance"] = str(distance)
        self.chunk_metadata.append(chunk_metadata)

    def get_all_chunk_activity_keys(self) -> str:
        return [item["activity_key"] for item in self.chunk_metadata]
            
    def add_encoding_length(self, name: str, message: str, encoding: Encoding) -> None:
        if name not in self.token_size:
            self.token_size[name] = 0
        self.token_size[name] += len(encoding.encode(message))
    
    def get_encoding_length(self) -> int:
        return sum(self.token_size.values())
    
    def log_encoding_length(self) -> None:
        for name, size in self.token_size.items():
            logger.debug(f"Encoding length for {name}: {size}")

    def add_system_message_parts(self,parts: list[dict[str, str]], encoding: Encoding) -> None:
        for part in parts:
            self.add_encoding_length(part["name"], part["message"], encoding)
            self.system_message += part["message"]

class AiEngine:
    def __init__(self, base_url: str):
        logger.debug(f"ai_context_dir: {base_url}")
        self.ctx_data = ContextDataset(base_url)
        self.ch_cli = chromadb.Client()
        self.encoding : Encoding = tiktoken.encoding_for_model(CDB_EMBEDDING_MODEL) 
        self._load_embeddings()

    def _load_embeddings(self):
        collection = self.ch_cli.create_collection(
            name=f"{CHROMADB_COLLECTION_NAME}",
            metadata={"hnsw:space": "ip"})

        logger.debug(f"Loading embeddings {CDB_EMBEDDING_MODEL}-{CDB_EMBEDDING_SIZE}")
        embeddings, ids, metadata = self.ctx_data.get_embeddings_data(CDB_EMBEDDING_MODEL, CDB_EMBEDDING_SIZE)

        max_batch_size = self.ch_cli.max_batch_size
        total_size = len(embeddings)
        logger.debug(f"Indexing embeddings {CDB_EMBEDDING_MODEL}-{CDB_EMBEDDING_SIZE} in batches of {max_batch_size}")
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

        logger.debug(f"Embeddings loaded and indexed {CDB_EMBEDDING_MODEL}-{CDB_EMBEDDING_SIZE}")

    async def _create_query(self, message: list[dict[str, str]], model: str, max_tokens: int, stream : bool) -> str:
        client = get_async_azure_openai_client()

        def encode_message_content(message: list[dict[str, str]]) -> int:
            total_length = 0
            for msg in message:
                total_length += len(self.encoding.encode(msg["content"]))
            return total_length
        
        if encode_message_content(message) > AZURE_MODEL_TOKEN_LIMIT - RESPONSE_MAX_TOKENS:
            raise QueryError(f"Context too large for model. Tokens used{encode_message_content(message)}\nResponse tokens: {RESPONSE_MAX_TOKENS}\nModel token limit: {AZURE_MODEL_TOKEN_LIMIT}")


        completion = await client.chat.completions.create(
            model=model,
            messages=message,
            stream=stream,
            max_tokens=max_tokens,
            temperature=0
        )
        return completion.choices[0].message.content

    async def _create_embedding(self, model: str, input: str, encoding_format: str, dimensions: int) -> str:
        client = get_async_azure_openai_client()

        if self.encoding.encode(input) > AZURE_MODEL_TOKEN_LIMIT:
            raise QueryError(f"Embedding input too large for model. Tokens used: {len(self.encoding.encode(input))}\nModel token limit: {AZURE_MODEL_TOKEN_LIMIT}")
    
        response = await client.embeddings.create(
            model=model,
            input=input,
            encoding_format=encoding_format,
            dimensions=dimensions
        )
        return response.data[0].embedding
    #creates a more elaborated request using query, condensed history and latest history
    async def preprocess_query(self, history: list[tuple[str,str]], query: str, course_key: str, activity_key: str, condensed_history: str) -> str:
      
        course_summary, lesson_summary = self.ctx_data.get_summary_texts(
            course_key, activity_key)
        
        if condensed_history:
            system_message = preprocess_system_message_template_with_history.format(
                course_summary=course_summary,
                lesson_summary=lesson_summary,
                condensed_history = condensed_history
            )    
        else:
          system_message = preprocess_system_message_template.format(
                course_summary=course_summary,
                lesson_summary=lesson_summary,
            ) 


        preprocessed_user_message = preprocess_user_message_template.format(
            user_input=query
        )

        messages = create_message(system_message, history, query)  

        responese = self._create_query(
            message= messages,
            model= LLM_MODEL,
            max_tokens= PREPROCESS_QUERY_MAX_TOKENS,
            stream= False)

        preprocessed_user_message = query + '\n' + responese
        logger.debug(f"preprocessed_query: {preprocessed_user_message}")
        return preprocessed_user_message
    
    async def make_system_message(self, history: list[tuple[str,str]], query: str,
                                   course_key: str, activity_key: str, condensed_history: str, query_context : QueryContext = None) -> str:
        
        preprocessed_query = await self.preprocess_query(history, query, course_key, activity_key, condensed_history)
        
        course_summary, lesson_summary = self.ctx_data.get_summary_texts(course_key, activity_key)

        if course_summary is None or lesson_summary is None:
            summary_segment = ""
        else:
            summary_segment = system_message_summary_template.format(
                course_summary=course_summary,
                lesson_summary=lesson_summary
            )

        if condensed_history:
            condensed_segment = system_message_condensed_history_template.format(condensed_history=condensed_history)
        else:
            condensed_segment = ""


        query_embedding = self._create_embedding(
            model=LLM_EMBEDDING_MODEL,
            input=preprocessed_query,
            encoding_format="float",
            dimensions=CDB_EMBEDDING_SIZE
        )

        collection = self.ch_cli.get_collection(CHROMADB_COLLECTION_NAME)

        result =collection.query(
            query_embeddings=[query_embedding],
            where={"course_key": course_key},
            n_results=2)

        chunk_strs = []
        for chunk_hash, dist, metadata in zip(result["ids"][0], result["distances"][0], result["metadatas"][0]):
            if query_context:
                query_context.add_chunk_metadata(metadata, dist)
            chunk_str = self.ctx_data.get_chunk_text(chunk_hash)
            chunk_strs.append(chunk_str)

        rag_segment = system_message_rag_template.format(
            chunks='\n\n'.join(chunk_strs)
        )

        system_message = system_message_template + summary_segment + condensed_segment + rag_segment

        if query_context:
            query_context.add_system_message_parts(
                [
                    {"name": "system_message_template", "message": system_message},
                    {"name": "summary_segment", "message": summary_segment},
                    {"name": "condensed_segment", "message": condensed_segment},
                    {"name": "rag_segment", "message": rag_segment}
                ],
                self.encoding
            )

        return system_message

    async def generate_answer(self,*, history: list[tuple[str,str]], query: str,
                            course_key: str, activity_key: str, condensed_history: str) -> tuple[AsyncIterator[int], QueryContext]:
        query_context = QueryContext()

        if condensed_history:
            history = history[-MAX_HISTORY_LENGTH:]
            
        system_message = await self.make_system_message(history, query, course_key, activity_key, condensed_history, query_context)
        
        messages = create_message(system_message, history, query)

        for item in history:
            query_context.add_encoding_length("history", item[0] + item[1], self.encoding) 
            query_context.add_encoding_length("user_query", query, self.encoding)

        completion = self._create_query(
            message= messages,
            model= LLM_MODEL,
            max_tokens= RESPONSE_MAX_TOKENS, 
            stream=True)
    
        async def answer_generator():
            async for chunk in completion:
                if len(chunk.choices) > 0:
                    delta = chunk.choices[0].delta
                    if delta.content:
                        yield delta.content

        return answer_generator(), query_context
    
    async def generate_condensed_history(self, latestHistory: list[tuple[str,str]],
                                          condensed_history: str) -> str:
        if condensed_history:
            message = condensed_history_template.format(
                condensed_history=condensed_history,
                latest_user_question=latestHistory[-1][0],
                latest_assistant_explanation=latestHistory[-1][1])
        else:
            message = new_condensed_history_template.format(
                previous_user_question_1 = latestHistory[-2][0],
                previous_assistant_explanation_1 =latestHistory[-2][1],
                previous_user_question_2 = latestHistory[-1][0],
                previous_assistant_explanation_2 = latestHistory[-1][1])   
            
        messages = create_message(
            system= condensed_history_system,
            history=[],
            query=message)

        respones = self._create_query(
            message=messages, 
            model=LLM_MODEL, 
            max_tokens=RESPONSE_MAX_TOKENS, 
            stream=False)
        logger.debug(f"condensed_history: {respones}")

        return respones
    
    async def compare_strings(self, response_text: str, benchmark_text: str) -> int:         
        compare_prompt_message = compare_prompt.format(
            current_text=response_text,
            benchmark_text=benchmark_text
        )

        messages = create_message(
            system= system_compare_template,
            history=[],
            query=compare_prompt_message)

        response = self._create_query(
            message=messages,
            model= LLM_MODEL,
            max_tokens= 50, 
            stream=False)

        try:
            similarity_score = int(response)
        except ValueError:
            similarity_score = -1 
        logger.debug(f"similarity_score: {similarity_score}")
        return similarity_score