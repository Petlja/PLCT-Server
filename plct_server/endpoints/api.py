import logging
import os
from typing import List
from fastapi import APIRouter, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from openai import OpenAIError

from ..content import get_content_config
from ..ai import get_engine

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

    get_content_config()
    ai_engine = get_engine()

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

    




