import asyncio
import logging
import json
from typing import Any, AsyncGenerator, List
from fastapi import APIRouter, Depends, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from openai import BadRequestError, OpenAIError, RateLimitError

from ..content.server import get_server_content
from ..ai import debug_stream
from ..ai.engine import get_ai_engine, ContextLengthError, QueryError
from .auth import require_auth

logger = logging.getLogger(__name__)

router = APIRouter()


class ChatHistoryItem(BaseModel):
    q: str = ""
    a: str = ""

class ChatInput(BaseModel):
    history: List[ChatHistoryItem] = []
    question: str = ""
    accessKey: str = ""
    model : str = ""
    contextAttributes: dict[str,str] = {}

class ChatModel(BaseModel):
    name: str
    display_name: str

class UiConfig(BaseModel):
    """What the SPA needs to know before it can draw itself."""
    debug_mode: bool

# What the reader is told while they wait, one per stage the engine announces. A wire
# contract: a stage with no message raises rather than streaming a blank one.
PROGRESS_MESSAGES = {
    "reading_page": "Čitam lekciju koju gledaš...",
    "preparing_answer": "Pripremam odgovor...",
    "retrieving": "Tražim relevantne delove sadržaja...",
    "analyzing": "Analiziram pronađeno...",
    "writing": "Pišem odgovor...",
}

# A search says what it is searching: the teacher knows all four places, so naming one
# says something the generic message cannot.
SEARCH_TARGETS = {
    "search_course": "materijal kursa",
    "search_current_page": "ostatak ove lekcije",
    "consult_teaching_literature": "stručnu literaturu o nastavi",
    "search_platform_docs": "uputstvo za petlja.org",
}

# What a failure says, under the name it is known by. Everything the reader can do nothing
# about collapses into the generic line; the two they can act on -- start over, or wait --
# are told apart. A wire contract, like the progress stages: the code is what lets the
# Petlja platform say the same thing in the course's language, which only it knows, and a
# code it has not heard of leaves it the message below to fall back on.
ERROR_MESSAGES = {
    "error": "Ima tehničkih problema sa pristupom OpenAI, malo sačekaj pa pokušaj ponovo",
    "context_length": ("Ovaj razgovor je predug da bi se nastavio. Osveži stranicu i "
                       "postavi pitanje u novom razgovoru"),
    "rate_limit": "Trenutno stiže previše pitanja. Sačekaj minut pa pokušaj ponovo",
}


def error_code(error: Exception) -> str:
    """Which failure this is, in the platform's terms.

    The upstream refusal is read as well as our own count: for a model with no encoding of
    its own the count is an estimate (`FALLBACK_ENCODING`), so a prompt can pass here and
    still be refused there.
    """
    if isinstance(error, ContextLengthError) or (
            isinstance(error, BadRequestError) and error.code == "context_length_exceeded"):
        return "context_length"
    if isinstance(error, RateLimitError):
        return "rate_limit"
    return "error"


def error_event(error: Exception) -> dict[str, str]:
    code = error_code(error)
    return {"type": "error", "code": code, "message": ERROR_MESSAGES[code]}


def progress_message(stage: str, detail: str | None) -> str:
    """The line the reader sees. Raises on an unknown stage; a tool with no phrase in
    `SEARCH_TARGETS` degrades to the generic line rather than breaking the stream."""
    if stage == "retrieving" and detail:
        targets = [SEARCH_TARGETS.get(name.strip()) for name in detail.split(",")]
        if all(targets):
            return "Pretražujem " + " i ".join(dict.fromkeys(targets)) + "..."
    return PROGRESS_MESSAGES[stage]

# The answer's own events are few and the consumer is a socket, so a short queue is
# enough to keep the pipeline and the client in step. A debug run adds one event per log
# record, which is a different order of traffic, and gets room to match.
QUEUE_SIZE = 20
DEBUG_QUEUE_SIZE = 500


def debug_mode_enabled() -> bool:
    """Whether this server tees the pipeline log into the answer stream."""
    return get_server_content().config_options.debug_mode


def encode_event(event: dict[str, Any]) -> bytes:
    return json.dumps(event, ensure_ascii=False).encode("utf-8") + b"\n"


async def stream_response(input: ChatInput) -> AsyncGenerator[bytes, None]:
    course_key = input.contextAttributes.get("course_key") or ""
    activity_key = input.contextAttributes.get("activity_key") or ""
    history = [(item.q, item.a) for item in input.history]
    ai_engine = get_ai_engine()
    debug = debug_mode_enabled()
    event_queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue(
        maxsize=DEBUG_QUEUE_SIZE if debug else QUEUE_SIZE)

    async def publish_progress(stage: str, detail: str | None = None) -> None:
        message = progress_message(stage, detail)
        # Noted before it is sent, so the trace reads in the order things happened.
        # `note` is inert outside a capture, so this needs no test for debug mode.
        debug_stream.note(f"the teacher now sees: {message}"
                          + (f" [{stage}: {detail}]" if detail else f" [{stage}]"))
        await event_queue.put({
            "type": "progress",
            "stage": stage,
            "message": message,
            **({"detail": detail} if detail else {}),
        })

    def publish_debug(event: dict[str, Any]) -> None:
        """Called from `logging`, which is synchronous: this must not block or raise.

        A trace line is worth less than the answer it describes, so a full queue drops
        the line rather than stalling the pipeline that is filling the queue.
        """
        try:
            event_queue.put_nowait(event)
        except asyncio.QueueFull:
            pass

    async def produce_events() -> None:
        # Bound here rather than around the task, so the capture lives in this task's
        # own context and one question's records never land in another's stream.
        with debug_stream.capture(publish_debug if debug else None):
            try:
                generated_answer, _ = await ai_engine.generate_answer(
                    history=history,
                    query=input.question,
                    course_key=course_key,
                    activity_key=activity_key,
                    model_name=input.model,
                    progress_callback=publish_progress)

                async for chunk in generated_answer:
                    await event_queue.put({"type": "content", "text": chunk})

                await event_queue.put({"type": "done"})
            except QueryError as error:
                logger.error(f"QueryError: {error}")
                await event_queue.put(error_event(error))
            except OpenAIError as error:
                logger.warning(f"Error while calling OpenAI API: {error}")
                await event_queue.put(error_event(error))
            except Exception as error:
                logger.exception("Unexpected error while streaming chat response")
                await event_queue.put(error_event(error))
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

@router.get("/api/ui-config")
async def get_ui_config() -> UiConfig:
    """Read before the chat is drawn: it decides whether the debug toggle is offered."""
    return UiConfig(debug_mode=debug_mode_enabled())

@router.get("/api/chat", dependencies=[Depends(require_auth)])
async def get_chat() -> Response:
    """The SPA's readiness probe: 200 once the caller may actually ask a question."""
    return Response(status_code=200)

@router.post("/api/chat", dependencies=[Depends(require_auth)])
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






