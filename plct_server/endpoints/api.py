import logging
from datetime import datetime
import os
from typing import List, Optional
from fastapi import APIRouter, Body, HTTPException, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from openai import AsyncOpenAI




logger = logging.getLogger(__name__)

router = APIRouter()


class ChatHistoryItem(BaseModel):
    q: str = ""
    a: str = ""

class ChatInput(BaseModel):
    history: List[ChatHistoryItem] = []
    question: str = ""
    accessKey: str = ""

logger = logging.getLogger(__name__)
# logger.setLevel(logging.DEBUG)

system_message = (
    "Keep in the context of learning to code in Python.\n\n"
    "Format output with Markdown.\n\n"
    "Odgovori na postavljeno pitanje na srpskom, latinicom.\n\n"
    "Avoid Python builtin functions sum, min, and max.\n\n"
    "Uvek pokušaj da daš primer u Pajtonu i objašnjenje.\n\n"
    "Ako nisi siguran, odgovori 'nisam siguran, pokušaj da preformulišeš pitanje'."
)

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

    try:
        client = AsyncOpenAI(api_key = OPENAI_API_KEY)
        messages=[{"role": "system", "content": system_message}]
        for item in input.history:
            messages.append({"role": "user", "content": item.q})
            messages.append({"role": "assistant", "content": item.a})
        messages.append({"role": "user", "content": input.question})
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

    




