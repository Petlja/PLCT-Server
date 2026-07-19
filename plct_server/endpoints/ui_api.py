import asyncio
import logging
import json
from typing import Any, AsyncGenerator, List
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
    model : str = ""
    contextAttributes: dict[str,str] = {}

class ChatModel(BaseModel):
    name: str
    display_name: str

PROGRESS_MESSAGES = {
    "classifying": "Analiziram pitanje...",
    "embedding": "Pripremam pretragu...",
    "retrieving": "Tražim relevantne delove sadržaja...",
    "preparing_answer": "Pripremam odgovor...",
    "condensing_history": "Ažuriram kontekst razgovora...",
    "generating_answer": "Generišem odgovor...",
}
ERROR_MESSAGE = "Ima tehničkih problema sa pristupom OpenAI, malo sačekaj pa pokušaj ponovo"


def encode_event(event: dict[str, Any]) -> bytes:
    return json.dumps(event, ensure_ascii=False).encode("utf-8") + b"\n"


async def stream_response(input: ChatInput) -> AsyncGenerator[bytes, None]:
    course_key = input.contextAttributes.get("course_key")
    activity_key = input.contextAttributes.get("activity_key")
    history = [(item.q, item.a) for item in input.history]
    ai_engine = get_ai_engine()
    event_queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue(maxsize=20)

    async def publish_progress(stage: str) -> None:
        await event_queue.put({
            "type": "progress",
            "stage": stage,
            "message": PROGRESS_MESSAGES[stage],
        })

    async def produce_events() -> None:
        try:
            generated_answer, followup_questions, _ = await ai_engine.generate_answer(
                history=history,
                query=input.question,
                course_key=course_key,
                activity_key=activity_key,
                condensed_history=input.condensedHistory,
                model_name=input.model,
                progress_callback=publish_progress)

            await publish_progress("condensing_history")
            new_condensed_history = await ai_engine.generate_condensed_history(
                history=history,
                condensed_history=input.condensedHistory)

            await event_queue.put({
                "type": "metadata",
                "condensed_history": new_condensed_history,
                "followup_questions": followup_questions,
            })
            await publish_progress("generating_answer")

            async for chunk in generated_answer:
                await event_queue.put({"type": "content", "text": chunk})

            await event_queue.put({"type": "done"})
        except QueryError as error:
            logger.error(f"QueryError: {error}")
            await event_queue.put({"type": "error", "message": ERROR_MESSAGE})
        except OpenAIError as error:
            logger.warning(f"Error while calling OpenAI API: {error}")
            await event_queue.put({"type": "error", "message": ERROR_MESSAGE})
        except Exception:
            logger.exception("Unexpected error while streaming chat response")
            await event_queue.put({"type": "error", "message": ERROR_MESSAGE})
        finally:
            await event_queue.put(None)

    producer_task = asyncio.create_task(produce_events())
    try:
        while True:
            event = await event_queue.get()
            if event is None:
                break
            yield encode_event(event)
    finally:
        if not producer_task.done():
            producer_task.cancel()
        await asyncio.gather(producer_task, return_exceptions=True)

logger = logging.getLogger(__name__)


@router.get("/api/models")
async def get_models() -> List[ChatModel]:
    ai_engine = get_ai_engine()
    chat_models = ai_engine.get_chat_models()
    result = [ChatModel(name=model.name, display_name=model.display_name) for model in chat_models]
    return result

@router.get("/api/chat")
async def get_chat() -> Response:
    return Response(status_code=200)

@router.post("/api/chat")
async def post_question(input: ChatInput) -> Response:
    logger.debug(f"Chat input: {input}")
    logger.debug(f"Context attributes: {input.contextAttributes}")
    return StreamingResponse(
        stream_response(input),
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-cache",
            "X-Content-Type-Options": "nosniff",
            "X-Accel-Buffering": "no",
        })
    

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






