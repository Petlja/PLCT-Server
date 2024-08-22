import logging
import os
import json
from typing import AsyncGenerator, List
from fastapi import APIRouter, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from openai import OpenAIError

from ..content.server import get_server_content
from ..ai.engine import get_ai_engine, QueryError

logger = logging.getLogger(__name__)

router = APIRouter()


class ChatHistoryItem(BaseModel):
    q: str = ""
    a: str = ""

class ChatInput(BaseModel):
    history: List[ChatHistoryItem] = []
    question: str = ""
    accessKey: str = ""
    condensedHistory: str = "" 
    contextAttributes: dict[str,str] = {}

async def stream_response(answer, condensed_history) -> AsyncGenerator[bytes, None]:
    metadata = {
        "condensed_history": condensed_history
    }

    yield json.dumps(metadata).encode('utf-8') + b'\n'

    async for chunk in answer:
        yield chunk.encode('utf-8')

logger = logging.getLogger(__name__)
OPENAI_API_KEY = os.environ["CHATAI_OPENAI_API_KEY"]


@router.get("/api/chat")
async def get_chat() -> Response:
    return Response(status_code=200)

@router.post("/api/chat")
async def post_question(response: Response, input: ChatInput) -> Response:
    response.media_type = "text/plain; charset=utf-8"
    logger.debug(f"Chat input: {input}")
    logger.debug(f"Context attributes: {input.contextAttributes}")
    
    course_key = input.contextAttributes.get("course_key")
    activity_key = input.contextAttributes.get("activity_key")
    history = [(item.q, item.a) for item in input.history]


    ai_engine = get_ai_engine()
    try:           
        generated_answer, _ = await ai_engine.generate_answer(
            history=history, 
            query=input.question, 
            course_key=course_key, 
            activity_key=activity_key, 
            condensed_history=input.condensedHistory)  
        
        new_condensed_history = await ai_engine.generate_condensed_history(
            history=history, 
            condensed_history=input.condensedHistory)

        return StreamingResponse(
            stream_response(
                generated_answer,
                new_condensed_history),
            media_type="text/plain")
    
    except QueryError as e:
        logger.error(f"QueryError: {e}")
        return Response("Ima tehničkih problema sa pristupom OpenAI, malo sačekaj pa pokušaj ponovo",
                         media_type="text/plain")
    except OpenAIError as e:
        logger.warn(f"Error while calling OpenAI API: {e}")
        return Response("Ima tehničkih problema sa pristupom OpenAI, malo sačekaj pa pokušaj ponovo",
                         media_type="text/plain")
    

class CourseItem(BaseModel):
    title: str
    course_key: str

@router.get("/api/courses")
async def get_courses() -> List[CourseItem]:
    srv_cnt = get_server_content()

    courses = [CourseItem(title=course.title, course_key=course.course_key) for course in srv_cnt.course_dict.values()]
    return courses

class TocItemRequest(BaseModel):
    key: str
    item_path: list[str]

class TocItemResponse(BaseModel):
    key: str
    title: str

@router.post("/api/toc-item")
async def get_toc_item(input: TocItemRequest) -> TocItemResponse:
    srv_cnt = get_server_content()
    item = srv_cnt.get_toc_item(input.key, input.item_path)
    if item is None:
        return TocItemResponse(key="", title="")
    return TocItemResponse(key=item.key, title=item.title)

@router.post("/api/toc-list")
async def get_toc_list(response: Response, input: TocItemRequest) -> List[TocItemResponse]:
    srv_cnt = get_server_content()
    items = srv_cnt.get_toc_list(input.key, input.item_path)
    if items is None:
        return []
    return [TocItemResponse(key=item.key, title=item.title) for item in items]






