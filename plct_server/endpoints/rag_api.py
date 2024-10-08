import logging
from typing import List
from fastapi import APIRouter, HTTPException, Response, Security
from fastapi.security import APIKeyHeader
from openai import OpenAIError
from pydantic import BaseModel

from ..content.server import get_server_content
from ..ai.engine import QueryError, get_ai_engine

logger = logging.getLogger(__name__)

router = APIRouter()

class RagSystemMessageRequest(BaseModel):
    history: List[tuple[str,str]] = []
    query: str = ""
    course_key: str = ""
    activity_key: str = ""
    condensed_history: str = ""

class RagSystemMessageResponse(BaseModel):
    message: str = ""
    condensed_history: str = ""
    followup_questions: List[str] = []

api_key_header_scheme = APIKeyHeader(name="X-Auth-Key", auto_error=False)

def get_api_key(api_key_header: str = Security(api_key_header_scheme)) -> str:
    srv_cnt = get_server_content()
    api_key = srv_cnt.config_options.api_key
    logger.debug(f"api_key_header: {api_key_header}, api_key: {api_key}")
    if api_key_header and api_key and api_key_header == api_key:
        return api_key_header
    raise HTTPException(status_code=401, detail="Unauthorized")
    

@router.post("/api/rag-system-message")
async def rag_system_message(response: Response, input: RagSystemMessageRequest,
                             key: str =  Security(get_api_key)) -> RagSystemMessageResponse:
    response.media_type = "application/json"
    new_condensed_history = ""
    ai_engine = get_ai_engine()
    try:                  
        system_message, followup_questions = await ai_engine.make_system_message(
                history=input.history, 
                query=input.query, 
                course_key=input.course_key, 
                activity_key=input.activity_key, 
                condensed_history=input.condensed_history)
        
        new_condensed_history = await ai_engine.generate_condensed_history(
            history=input.history, 
            condensed_history=input.condensed_history)
        
    except QueryError as e:
        logger.error(f"QueryError: {e}")
        return HTTPException(status_code=500, detail="QueryError")
    
    except OpenAIError as e:
        logger.error(f"OpenAIError: {e}")
        return HTTPException(status_code=500, detail="OpenAIError")
    
    return RagSystemMessageResponse(message=system_message, 
                                    condensed_history=new_condensed_history, 
                                    followup_questions=followup_questions)

    

    