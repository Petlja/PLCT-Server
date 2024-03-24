import logging
import os
from typing import List
from fastapi import APIRouter, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from openai import OpenAIError

from ..content.server import get_server_content
from ..ai.engine import get_ai_engine

logger = logging.getLogger(__name__)

router = APIRouter()


class ChatHistoryItem(BaseModel):
    q: str = ""
    a: str = ""

class ChatInput(BaseModel):
    history: List[ChatHistoryItem] = []
    question: str = ""
    accessKey: str = ""
    contextAttributes: dict[str,str] = {}

logger = logging.getLogger(__name__)
# logger.setLevel(logging.DEBUG)


OPENAI_API_KEY = os.environ["CHATAI_OPENAI_API_KEY"]


@router.post("/api/chat")
async def post_question(response: Response, input: ChatInput):
    response.media_type = "text/plain; charset=utf-8"
    # access_control = AccessControlService()  # Update this according to your access control service implementation
    #db_context_factory = AiPetljaDbContextFactory()  # Update this according to your database context factory implementation

    #if not access_control.is_access_allowed(input.accessKey):
    #    return "Pristup četu nije onogućen"
    # elif access_control.is_quota_exceeded(input.accessKey):
    #    return "Ispunjena je tvoja kvota pitanja u tekućem satu, prokušaj malo kasnije"

    logger.debug(f"Chat input: {input}")
    if input.question == "_test":
        return Response("_OK", media_type="text/plain")

    ai_engine = get_ai_engine()

    logger.debug(f"Context attributes: {input.contextAttributes}")
    course_key = input.contextAttributes.get("course_key")
    activity_key = input.contextAttributes.get("activity_key")
    history = [(item.q, item.a) for item in input.history]

    try:
        g = await ai_engine.generate_answer(
            history=history, query=input.question, 
            course_key=course_key, activity_key=activity_key)
        return StreamingResponse(g, media_type="text/plain")
    except OpenAIError as e:
        logger.warn(f"Error while calling OpenAI API: {e}")
        return Response("Ima tehničkih problema sa pristupom OpenAI, malo sačekaj pa pokušaj ponovo",
                         media_type="text/plain")

    # try:
    #     with db_context_factory.create_context() as db:
    #         log_item = ChatLog(
    #             access_key=input.accessKey,
    #             question=input.question,
    #             full_context="",
    #             answer=result_text,
    #             answer_html="",
    #             timestamp=datetime.now()
    #         )
    #         db.add(log_item)
    #         db.commit()
    # except Exception as e:
    #     logger.error(f"Database error: {e}")

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






