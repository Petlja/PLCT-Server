import logging
import os
from typing import List
from fastapi import APIRouter, Depends, HTTPException, Header, Response, Security
from fastapi.responses import StreamingResponse
from fastapi.security import APIKeyHeader
from pydantic import BaseModel
from openai import OpenAIError

from ..content.server import get_server_content
from ..ai.engine import get_ai_engine

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

    if input.condensed_history:
        input.history = input.history[-1:]
        new_condensed_history = await ai_engine.generate_condensed_history(latestHistory=input.history, condensed_history=input.condensed_history)
        system_message = await ai_engine.make_system_message(input.history, input.query, input.course_key, input.activity_key, new_condensed_history)
    else:
        system_message = await ai_engine.make_system_message(input.history, input.query, input.course_key, input.activity_key, input.condensed_history)
        if len(input.history) > 1:
            new_condensed_history = await ai_engine.generate_condensed_history(latestHistory=input.history, condensed_history=input.condensed_history)

    return RagSystemMessageResponse(message=system_message, condensed_history=new_condensed_history)

    

    