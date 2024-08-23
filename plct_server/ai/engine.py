
import logging
import chromadb
import tiktoken

from tiktoken import Encoding
from typing import Any, AsyncIterator, Coroutine, Union
from openai import AsyncAzureOpenAI
from openai.resources.chat.completions import ChatCompletion

from .conf import MODEL_CONFIGS, ModelConfig
from .context_dataset import ContextDataset
from .query_context import QueryContext, QueryError
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

def get_async_azure_openai_client(config: ModelConfig) -> AsyncAzureOpenAI:
    logger.debug(f"Creating Azure OpenAI client for model {config.name}")
    return AsyncAzureOpenAI(
        api_key=OPENAI_API_KEY,
        azure_endpoint=config.azure_endpoint,
        azure_deployment=config.azure_deployment_name,
        api_version=config.api_version
    )

def create_message(system : str, history: list[dict[str, str]], query):
    messages = [{"role": "system", "content": system}]
    for item in history:
        messages.append({"role": "user", "content": item[0]})
        messages.append({"role": "assistant", "content": item[1]})
    messages.append({"role": "user", "content": query})
    return messages

CHAT_MODEL = "gpt-4o-mini"
EMBEDDING_MODEL = "text-embedding-3-large"
EMBEDDING_SIZE = 1536
CDB_COLLECTION_NAME = f"{EMBEDDING_MODEL}-{EMBEDDING_SIZE}"


class AiEngine:
    def __init__(self, base_url: str):
        logger.debug(f"ai_context_dir: {base_url}")
        self.ctx_data = ContextDataset(base_url)
        self.ch_cli = chromadb.Client()
        self.encoding : Encoding = tiktoken.encoding_for_model(EMBEDDING_MODEL) 
        self._load_embeddings()
        self.default_chat_config = CHAT_MODEL
        self.default_embedding_config = EMBEDDING_MODEL

    def _load_embeddings(self):
        collection = self.ch_cli.create_collection(
            name=f"{CDB_COLLECTION_NAME}",
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

    def _get_model_config(self, model_name: str) -> ModelConfig:
        conf = MODEL_CONFIGS.get(model_name)
        if not conf:
            raise ValueError(f"Model configuration for {model_name} not found")
        return conf
    
    async def _handle_query_submission(self, message: list[dict[str, str]], max_tokens: int, stream : bool,
                                        model_name : str = None) -> Union[str, Coroutine[Any, Any, ChatCompletion]]:
        model = model_name or self.default_chat_config
        config = self._get_model_config(model)
        client = get_async_azure_openai_client(
            config = config
        )

        def encode_message_content(message: list[dict[str, str]]) -> int:
            total_length = 0
            for msg in message:
                total_length += len(self.encoding.encode(msg["content"]))
            return total_length
        
        token_limit = config.context_size

        if encode_message_content(message) > token_limit - max_tokens:
            raise QueryError((
                f"Context too large for model. Tokens used: {encode_message_content(message)}",
                f"Response tokens: {max_tokens}",
                f"Model token limit: {token_limit}"
            ))

        completion = await client.chat.completions.create(
            model=config.name,
            messages=message,
            stream=stream,
            max_tokens=max_tokens,
            temperature=0
        )

        if stream:
            return completion
        else:
            return completion.choices[0].message.content
        

    async def _create_embedding(self, input: str, encoding_format: str, dimensions: int) -> str:
        config = self._get_model_config(self.default_embedding_config)
        client = get_async_azure_openai_client(
            config = config
        )

        token_limit = config.context_size

        if len(self.encoding.encode(input)) > token_limit:
            raise QueryError((
                f"Embedding input too large for model. Tokens used: {len(self.encoding.encode(input))}",
                f"Model token limit: {token_limit}"))
    
        response = await client.embeddings.create(
            model=config.name,
            input=input,
            encoding_format=encoding_format,
            dimensions=dimensions
        )
        return response.data[0].embedding

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

        response = await self._handle_query_submission(
            message= messages,
            max_tokens= 1000,
            stream= False)

        preprocessed_user_message = query + '\n' + response
        logger.debug(f"preprocessed_query: {preprocessed_user_message}")
        return preprocessed_user_message
    
    async def make_system_message(self, history: list[tuple[str,str]], query: str,
                                   course_key: str, activity_key: str, condensed_history: str, query_context : QueryContext = None) -> str:
                
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
            history = [history.pop()]
        else:
            condensed_segment = ""

        preprocessed_query = await self.preprocess_query(history, query, course_key, activity_key, condensed_history)
        logger.debug(f"Query after elaboration: {preprocessed_query}")

        query_embedding = await self._create_embedding(
            input=preprocessed_query,
            encoding_format="float",
            dimensions=EMBEDDING_SIZE
        )

        collection = self.ch_cli.get_collection(CDB_COLLECTION_NAME)

        result =collection.query(
            query_embeddings=[query_embedding],
            where={"course_key": course_key},
            n_results=2)

        chunk_strs : list[str, str] = []
        chunk_metadata : list[dict[str, str]] = []
        chunk_hash : str
        dist : float
        metadata : dict[str, str]
        for chunk_hash, dist, metadata in zip(result["ids"][0], result["distances"][0], result["metadatas"][0]):
            metadata["distance"] = str(dist)
            chunk_metadata.append(metadata)
            chunk_str = self.ctx_data.get_chunk_text(chunk_hash)
            chunk_strs.append(chunk_str)


        logger.debug(f"chunk_metadata: {chunk_metadata}")

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
            query_context.set_chunk_metadata(chunk_metadata)

        return system_message

    async def generate_answer(self,*, history: list[tuple[str,str]], query: str,
                            course_key: str, activity_key: str, condensed_history: str, model_name) -> tuple[AsyncIterator[int], QueryContext]:
        query_context = QueryContext()

        if condensed_history:
            history = [history.pop()]
            
        system_message = await self.make_system_message(history, query, course_key, activity_key, condensed_history, query_context)
        
        messages = create_message(system_message, history, query)

        for item in history:
            query_context.add_encoding_length("history", item[0] + item[1], self.encoding) 
        query_context.add_encoding_length("user_query", query, self.encoding)

        response = await self._handle_query_submission(
            message= messages,
            max_tokens= 2000, 
            stream=True,
            model_name=model_name)
    
        async def answer_generator():
            async for chunk in response:
                if len(chunk.choices) > 0:
                    delta = chunk.choices[0].delta
                    if delta.content:
                        yield delta.content

        return answer_generator(), query_context
    
    async def generate_condensed_history(self, history: list[tuple[str,str]],
                                          condensed_history: str) -> str:
        if len(history) < 2:
            return ""
        
        if condensed_history:
            latest_user_question, latest_assistant_explanation = history.pop()
            message = condensed_history_template.format(
                condensed_history=condensed_history,
                latest_user_question=latest_user_question,
                latest_assistant_explanation=latest_assistant_explanation
            )
        else:
            previous_user_question_2, previous_assistant_explanation_2 = history.pop()
            previous_user_question_1, previous_assistant_explanation_1 = history.pop()
            message = new_condensed_history_template.format(
                previous_user_question_1=previous_user_question_1,
                previous_assistant_explanation_1=previous_assistant_explanation_1,
                previous_user_question_2=previous_user_question_2,
                previous_assistant_explanation_2=previous_assistant_explanation_2
            )

        messages = create_message(
            system= condensed_history_system,
            history=[],
            query=message)

        response = await self._handle_query_submission(
            message=messages, 
            max_tokens= 1000, 
            stream=False)
        logger.debug(f"condensed_history: {response}")

        return response
    
    async def compare_strings(self, response_text: str, benchmark_text: str) -> int:         
        compare_prompt_message = compare_prompt.format(
            current_text=response_text,
            benchmark_text=benchmark_text
        )

        messages = create_message(
            system= system_compare_template,
            history=[],
            query=compare_prompt_message)

        response = await self._handle_query_submission(
            message=messages,
            max_tokens= 50, 
            stream=False)

        try:
            similarity_score = int(response)
        except ValueError:
            similarity_score = -1 
        logger.debug(f"similarity_score: {similarity_score}")
        return similarity_score