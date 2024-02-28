import logging
from datetime import datetime
import os
from typing import List, Optional
from fastapi import APIRouter, Body, HTTPException, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from openai import AsyncOpenAI

from ..content import get_content_config

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

system_message_template = (
    "Keep in the context of learning to code in Python.\n\n"
    "Format output with Markdown.\n\n"
    "Avoid Python builtin functions sum, min, and max.\n\n"
    "Always try to give example in python and explanation.\n\n"
    "If you are not sure, answer that you are not sure and that you can't help.\n\n"
    #"Never answer outside of the Python context.\n\n"
    "Allways answer in the language of the question.\n\n"
)

system_message_context_template = (
    "Consider the question in the context of the folowing course and lesson.\n\n"
    "Here is the course summery delimited by triple quotes:\n\n"
    "'''\n"
    "{course_summary}\n"
    "'''\n\n"
    "Here is the lesson summery delimited by triple quotes:\n"
    "'''\n\n"
    "{lesson_summary}\n"
    "'''\n\n"
)

OPENAI_API_KEY = os.environ["CHATAI_OPENAI_API_KEY"]

def system_message_context(course_key: str, activity_key: str) -> str:
    if course_key is None or activity_key is None:
        return ""
    cnt_conf = get_content_config()
    course_conf = cnt_conf.course_dict.get(course_key)
    if course_conf is None or course_conf.ai_context is None:
        return ""
    course_summary = course_conf.ai_context.summary
    lesson_summary = course_conf.ai_context.activity_summary.get(activity_key)
    if course_summary is None or lesson_summary is None:
        return ""
    return system_message_context_template.format(
            course_summary=course_summary,
            lesson_summary=lesson_summary)

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

    
    client = AsyncOpenAI(api_key = OPENAI_API_KEY)
    cnt_conf = get_content_config()
    system_message = system_message_template
    logger.debug(f"Context attributes: {input.contextAttributes}")
    course_key = input.contextAttributes.get("course_key")
    activity_key = input.contextAttributes.get("activity_key")
    if course_key and activity_key:
        system_message += system_message_context(course_key, activity_key)
        
    messages=[{"role": "system", "content": system_message}]


    for item in input.history:
        messages.append({"role": "user", "content": item.q})
        messages.append({"role": "assistant", "content": item.a})
    messages.append({"role": "user", "content": input.question})

    try:
        completion = await client.chat.completions.create(
            model="gpt-4-0125-preview",
            messages=messages,
            stream=True,
            max_tokens=2000,
            temperature=0,
            stop=["\nQ:", "\nA:"],
        )

        async def response_generator():
            async for chunk in completion:
                yield chunk.choices[0].delta.content or ""

        return StreamingResponse(response_generator(), media_type="text/plain")
    except Exception as e:
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

    




