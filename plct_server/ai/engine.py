import json
import logging
import os
import glob
from typing import AsyncIterator
import chromadb
from openai import AsyncOpenAI, OpenAI, AzureOpenAI, AsyncAzureOpenAI
from pydantic import BaseModel

from plct_server.content.fileset import FileSet
from .context_dataset import ContextDataset
from . import OPENAI_API_KEY

from .prompt_templates import ( 
    preprocess_system_message_template, system_message_template, 
    system_message_summay_template, system_message_rag_template,
    preprocess_user_message_template, system_message_condensed_history_template)

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

        logger.debug(f"Indexing embeddings {EMBEDING_MODEL}-{EMBEDING_SIZE}")
        collection.add(
            embeddings=embeddings,
            ids=ids,
            metadatas=metadatas
        )
        logger.debug(f"Embeddings loaded and indexed {EMBEDING_MODEL}-{EMBEDING_SIZE}")


    #creates a more elaborated request using query, condnsed history and latest history
    async def preprocess_query(self, history: list[tuple[str,str]], qyery: str, course_key: str, activity_key: str, condensed_history: str) -> str:
      
        course_summary, lesson_summary = self.ctx_data.get_summary_texts(
            course_key, activity_key)
        
        system_message = preprocess_system_message_template.format(
            course_summary=course_summary,
            lesson_summary=lesson_summary,
            condensed_history = condensed_history
        )

        preprocessed_user_message = preprocess_user_message_template.format(
            user_input=qyery
        )

        messages=[{"role": "system", "content": system_message}]
        for item in history:
            messages.append({"role": "user", "content": item[0]})
            messages.append({"role": "assistant", "content": item[1]})
        messages.append({"role": "user", "content": preprocessed_user_message})
    
        client = AsyncAzureOpenAI(
            azure_endpoint = "https://petljaopenaiservice.openai.azure.com", 
            api_key= OPENAI_API_KEY,  
            api_version="2024-06-01"
        )

        completion = await client.chat.completions.create(
            model="gpt-35-turbo",
            messages=messages,
            stream=False,
            max_tokens=1000,
            temperature=0
        )

        preprocessed_user_message = qyery + '\n' + completion.choices[0].message.content
        logger.debug(f"preprocessed_query: {preprocessed_user_message}")
        return preprocessed_user_message
    
    async def make_system_message(self, history: list[tuple[str,str]], qyery: str, course_key: str, activity_key: str, condensed_history: str) -> str:
        preprocessed_query = await self.preprocess_query(history, qyery, course_key, activity_key, condensed_history)
        
        course_summary, lesson_summary = self.ctx_data.get_summary_texts(course_key, activity_key)

        if course_summary is None or lesson_summary is None:
            summary_segment = ""
        else:
            summary_segment = system_message_summay_template.format(
                course_summary=course_summary,
                lesson_summary=lesson_summary
            )


        if(condensed_history != ""):
            condensed_segment = system_message_condensed_history_template.format(
                condensed_history=condensed_history
            )
        else:
            condensed_segment = ""

        
        client = AsyncAzureOpenAI(
            azure_endpoint = "https://petljaopenaiservice.openai.azure.com", 
            api_key= OPENAI_API_KEY,  
            api_version="2024-06-01"
        )

        response = await client.embeddings.create(
            model='text-embedding-ada-002',
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
        for chunk_hash, dist, metadata in zip(result["ids"][0], result["distances"][0], result["metadatas"][0]):
            chunk_str = self.ctx_data.get_chunk_text(chunk_hash)
            chunk_strs.append(chunk_str)

        rag_segment = system_message_rag_template.format(
            chunks='\n\n'.join(chunk_strs)
        )

        system_message = system_message_template + summary_segment + condensed_segment + rag_segment

        return system_message

    async def generate_answer(self,*, history: list[tuple[str,str]], query: str,
                            course_key: str, activity_key: str, condensed_history: str = "") -> AsyncIterator[int]:

        if (condensed_history != ""):
            history = history[-1:]
            
        system_message = await self.make_system_message(history, query, course_key, activity_key, condensed_history)
        


        messages=[{"role": "system", "content": system_message}]
        for item in history:
            messages.append({"role": "user", "content": item[0]})
            messages.append({"role": "assistant", "content": item[1]})
        messages.append({"role": "user", "content": query})

        client =  AsyncAzureOpenAI(
            azure_endpoint = "https://petljaopenaiservice.openai.azure.com", 
            api_key= OPENAI_API_KEY,  
            api_version="2024-06-01"
        )
        
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
    
    async def generate_condensed_history(self, latestHistory: list[tuple[str,str]], condensed_history: str) -> str:
        if (condensed_history != ""):
            message = f"User and Assistant have discussed various topics. This is the summary: {condensed_history}"
            message = message  + f"Latest conversion include this user question: {latestHistory[-1][0]}." \
                    f" Assistant explained: {latestHistory[-1][1]}." \
                    f" Provide me new summary based on previous summary and latest question and answer in the language of the latest question"
        else:
            message = f"Here is two previous interacions with assistant." \
                    f"User question: {latestHistory[-2][0]}" \
                    f"Assistant explained: {latestHistory[-2][1]}" \
                    f"User question: {latestHistory[-1][0]}" \
                    f"Assistant explained: {latestHistory[-1][1]}" \
                    f"Provide me a summary based on previous questions and explanations in the language of the latest question"

        messages =[{"role": "user", "content": message}]
        client =  AsyncAzureOpenAI(
            azure_endpoint = "https://petljaopenaiservice.openai.azure.com", 
            api_key= OPENAI_API_KEY,  
            api_version="2024-06-01"
        )

        completion = await client.chat.completions.create(
            model="gpt-35-turbo",
            messages=messages,
            stream=False,
            max_tokens=2000,
            temperature=0
        )

        return completion.choices[0].message.content
    

   
