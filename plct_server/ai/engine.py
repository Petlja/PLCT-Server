import logging
import tiktoken

from tiktoken import Encoding
from typing import AsyncIterator, Awaitable, Callable, Union
from openai import AsyncAzureOpenAI, AsyncOpenAI, omit

from plct_server.ai.client import AiClientFactory

from ..knowledge import BundleSource, COURSES_KEY, KnowledgeStore
from ..knowledge.course_db import CourseDB
from .language import dominant_script
from .model_conf import ModelConfig, ModelProvider, MODEL_CONFIGS_LIST
from .query_context import QueryContext, QueryError
from .tools import (Ask, Command, Evidence, PageContext, PLATFORM_COURSE_KEY, ToolLoop,
                    bundle_search_tool, current_page, offering, read_commands,
                    render_course_map)
from .tools.course_tools import (course_search_tool, current_page_search_tool,
                                 platform_search_tool)
from .tools.evidence import DEFAULT_MAX_EVIDENCE_TOKENS
from .prompt_templates import (CONTEXT_COURSE, CONTEXT_MAP, CONTEXT_PAGE,
                               NO_COURSE_CONTEXT, PAGE_EXCERPT, PAGE_SUMMARY_ONLY,
                               PAGE_WHOLE, REQUIRED_SOURCE, SCOPE, SCRIPT_INSTRUCTION,
                               SYSTEM_HEADER, SYSTEM_RULES)
from . import narration

logger = logging.getLogger(__name__)

ai_engine: "AiEngine" = None

def init(*, store: KnowledgeStore, client_factory: AiClientFactory) -> None:
    global ai_engine
    if ai_engine is None:
        ai_engine = AiEngine(store=store,
                             client_factory=client_factory)
    else:
        raise ValueError(f"{__name__} already initialized")


def get_ai_engine() -> "AiEngine":
    global ai_engine
    if ai_engine is None:
        raise ValueError(f"{__name__} not initialized, call {__name__}.init first")
    return ai_engine

def create_message(system: str, history: list[tuple[str, str]],
                   query: str) -> list[dict[str, str]]:
    messages = [{"role": "system", "content": system}]
    for item in history:
        messages.append({"role": "user", "content": item[0]})
        messages.append({"role": "assistant", "content": item[1]})
    messages.append({"role": "user", "content": query})
    return messages

CHAT_MODEL = "gpt-4o-mini"        # when the request names no model
MAX_ANSWER_TOKENS = 2000          # reserved out of the chat model's context window

FALLBACK_ENCODING = "o200k_base"

ProgressCallback = Callable[[str, str | None], Awaitable[None]]

# Every stage this engine publishes, in the order one run goes through them. Owned here,
# worded by the endpoint; a stage with nothing to say it fails in `tests/test_ui_api.py`.
PROGRESS_STAGES = ("reading_page", "preparing_answer", "retrieving", "analyzing",
                   "writing")


async def report_progress(progress_callback: ProgressCallback | None, stage: str,
                          detail: str | None = None) -> None:
    if progress_callback:
        await progress_callback(stage, detail)


# ---------------------------------------------------------------- what a request costs

# The prompt as its reader thinks of it: a label, and the parts `QueryContext` measured
# under it. Grouped by why something is in the prompt, not by which template produced it.
PROMPT_PARTS: list[tuple[str, tuple[str, ...]]] = [
    ("the page they are on", ("page",)),
    ("course summary and map", ("course_summary", "course_map")),
    ("how to answer", ("header", "rules", "required_tool")),
    ("the conversation so far", ("history",)),
    ("their question", ("user_query",)),
]

# `QueryContext` files one part per tool call under this prefix, keyed by the call itself.
TOOL_PART_PREFIX = "tool: "


def evidence_budget(*, context_size: int, history_tokens: int) -> int:
    return max(0, min(DEFAULT_MAX_EVIDENCE_TOKENS,
                      context_size - history_tokens - MAX_ANSWER_TOKENS))


def _page_note(page: PageContext | None, *, in_prompt: bool) -> str:
    """Why the page cost what it cost. When it did not fit, the size it was refused at is
    what says whether that was reasonable, so a partial page reports both."""
    if not in_prompt:
        return "no course open, or not one in the index"
    if page is None:
        return "no indexed text for it -- only its summary went in"
    if page.whole:
        return f"delivered in full, all {narration.plural(page.total, 'section')}"
    return (f"delivered in part -- {narration.count(page.used)} of "
            f"{narration.plural(page.total, 'section')}, because whole it would have "
            f"taken ~{narration.tok(page.full_tokens)}")


def _prompt_rows(sizes: dict[str, int], *, page: PageContext | None,
                 exchanges: int) -> list:
    """The prompt broken into the parts it is made of, largest concern first."""
    notes = {"the page they are on": _page_note(page, in_prompt="page" in sizes)}
    if exchanges:
        notes["the conversation so far"] = narration.plural(exchanges, "earlier exchange")
    return [(label, narration.tok(sum(sizes.get(key, 0) for key in keys)),
             notes.get(label, ""))
            for label, keys in PROMPT_PARTS]


def log_initial_context(*, config: ModelConfig, sizes: dict[str, int],
                        page: PageContext | None, tools: list, exchanges: int,
                        evidence: Evidence, require: str | None = None) -> None:
    """What the model is being given before it has asked for anything -- written before the
    first request, because this is the one number a run can still be stopped over."""
    prompt = sum(sizes.values())
    rows = _prompt_rows(sizes, page=page, exchanges=exchanges) + [
        narration.RULE,
        ("sent to the model", narration.tok(prompt),
         f"of the model's {narration.tok(config.context_size)} window "
         f"({narration.share(prompt, config.context_size)}), with "
         f"{narration.tok(MAX_ANSWER_TOKENS)} of the rest held back for the answer"),
        ("evidence budget", narration.tok(evidence.max_tokens),
         f"{narration.tok(evidence.tokens)} of it already spent on the page, "
         f"{narration.tok(evidence.remaining)} left to search with"
         + ("" if evidence.max_tokens >= DEFAULT_MAX_EVIDENCE_TOKENS else
            f" -- down from {narration.tok(DEFAULT_MAX_EVIDENCE_TOKENS)}, the "
            "conversation has taken the rest of the window")),
    ]
    where = f' -- the teacher is on "{page.title}"' if page and page.title else ""
    offered = (f"{narration.plural(len(tools), 'tool')} it may call: "
               + ", ".join(tool.name for tool in tools) if tools
               else "no tools -- it answers from the above alone")
    logger.info("%s", narration.block(
        f"initial context for {config.name}{where}",
        narration.table(rows),
        narration.INDENT + offered,
        narration.INDENT + f"the teacher asked for {require} by name, so the prompt "
        "asks for it and the first turn has to gather, from it or any other tool"
        if require else ""))


def log_total_budget(*, config: ModelConfig, sizes: dict[str, int],
                     page: PageContext | None, exchanges: int, evidence: Evidence,
                     result, prompt_tokens: int) -> None:
    """Everything the finished answer cost, in the columns the run opened with plus what
    the tools sent back -- the only part of the prompt the model chose the size of.

    `sent to the model` is measured on the last turn, not summed from the rows above it:
    the transcript stores tool payloads indented, and the request also carries the model's
    own tool-call messages. Close to the column total, not equal to it.
    """
    tool_results = sum(size for name, size in sizes.items()
                       if name.startswith(TOOL_PART_PREFIX))
    rows = _prompt_rows(sizes, page=page, exchanges=exchanges) + [
        ("what the tools sent back", narration.tok(tool_results),
         f"from {narration.plural(result.calls, 'call')} in "
         f"{narration.plural(result.rounds, 'round')}"),
        narration.RULE,
        ("sent to the model", narration.tok(prompt_tokens),
         f"on the last turn, of the model's {narration.tok(config.context_size)} window "
         f"({narration.share(prompt_tokens, config.context_size)})"),
        ("evidence spent", narration.tok(evidence.tokens),
         f"of the {narration.tok(evidence.max_tokens)} budget "
         f"({narration.share(evidence.tokens, evidence.max_tokens)}), "
         f"{narration.tok(evidence.remaining)} left"),
    ]
    logger.info("%s", narration.block(
        f"answered after {narration.plural(result.rounds, 'tool round')} and "
        f"{narration.plural(result.calls, 'call')}, from "
        f"{narration.plural(len(evidence.delivered), 'passage')} of material",
        narration.table(rows)))


class AiEngine:


    _model_config_dict: dict[str, ModelConfig] = dict()

    def __init__(self, *, store: KnowledgeStore, client_factory: AiClientFactory):
        self.client_factory = client_factory
        self.store = store
        self.courses = store.source(COURSES_KEY)
        self.ctx_data = self.courses.ctx
        self._encodings: dict[str, Encoding] = {}
        self.fallback_encoding: Encoding = tiktoken.get_encoding(FALLBACK_ENCODING)
        self._load_model_configs()

        self.course_db = CourseDB(self.courses)
        self.bundles = [s for s in map(store.source, store.keys())
                        if isinstance(s, BundleSource)]
        for bundle in self.bundles:
            logger.info("bundle '%s' (%s) is offered as %s()", bundle.key,
                        bundle.knowledge_unit, offering(bundle).name)
        if not self.bundles:
            logger.info("no aikt-bundle sources loaded -- no literature tool is offered")

    def add_model_config(self, model_config: ModelConfig) -> None:
        if model_config.display_name is None:
            model_config.display_name = model_config.name.split("/")[-1]
        self._model_config_dict[model_config.name] = model_config
        model_config.order = len(self._model_config_dict)

    def get_chat_models(self) -> list[ModelConfig]:
        chat_models = [m for m in self._model_config_dict.values() if m.type == "chat"]
        chat_models.sort(key=lambda m: m.order)
        return chat_models

    def _load_model_configs(self):
        server_vllm_models = self.client_factory.list_vllm_models()
        configured_vllm_models = set()
        for model_config in MODEL_CONFIGS_LIST:
            if model_config.provider == ModelProvider.VLLM:
                if model_config.name in server_vllm_models:
                    self.add_model_config(model_config)
                    configured_vllm_models.add(model_config.name)
                    logger.info(f"Added configured vLLM model '{model_config.name}'")
            else:
                self.add_model_config(model_config)
                logger.info(f"Added configured model '{model_config.name}' for default provider")
        for model_name in set(server_vllm_models) - configured_vllm_models:
            context_size = server_vllm_models[model_name] or 128_000
            self.add_model_config(ModelConfig(
                name=model_name,
                provider=ModelProvider.VLLM,
                type="chat",
                context_size=context_size
            ))
            logger.info(f"Auto-added vLLM model '{model_name}' (context_size={context_size})")

        estimated = sorted(m.name for m in self._model_config_dict.values()
                           if m.type == "chat" and m.encoding is None)
        if estimated:
            logger.info("token counts for %s are estimates taken with %s -- these models "
                        "tokenize with their own vocabularies: %s",
                        "these models" if len(estimated) > 1 else "this model",
                        FALLBACK_ENCODING, ", ".join(estimated))


    def get_model_config(self, model_name: str) -> ModelConfig:
        model_config = self._model_config_dict.get(model_name)
        if not model_config:
            raise ValueError(f"Model '{model_name}' not found in configuration")
        return model_config

    def _encoding_for(self, config: ModelConfig) -> Encoding:
        name = config.encoding
        if name is None:
            return self.fallback_encoding
        encoding = self._encodings.get(name)
        if encoding is None:
            encoding = self._encodings[name] = tiktoken.get_encoding(name)
        return encoding

    def _get_async_openai_client(self, requested_model: str | None) -> Union[AsyncOpenAI, AsyncAzureOpenAI]:
        logger.debug(f"Creating AI client")
        model_config = self.get_model_config(requested_model)
        return self.client_factory.get_client(model_config)

    def count_tokens(self, text: str, encoding: Encoding | None = None) -> int:
        """Tokens in `text`, measured with `encoding` -- the fallback when none is given."""
        return len((encoding or self.fallback_encoding).encode(text))

    async def _create_embedding(self, input: str, *, model: str,
                                dimensions: int) -> list[float]:
        """One query vector. `model` and `dimensions` are required and come from the source
        being searched -- see `KnowledgeSource.query_embedder`."""
        client = self._get_async_openai_client(requested_model=model)
        config = self.get_model_config(model)
        token_limit = config.context_size

        used = self.count_tokens(input, self._encoding_for(config))
        if used > token_limit:
            raise QueryError((
                f"Embedding input too large for model. Tokens used: {used}",
                f"Model token limit: {token_limit}"))

        response = await client.embeddings.create(
            model=config.name,
            input=input,
            encoding_format="float",
            dimensions=dimensions
        )
        return response.data[0].embedding

    # ------------------------------------------------------------------ the prompt

    async def _context_parts(self, query: str, course_key: str, activity_key: str,
                             evidence: Evidence
                             ) -> tuple[list[dict[str, str]], PageContext | None]:
        """Course summary, course map, and the page the teacher is on -- as named parts.

        Separate rather than one string because each is also a size, and `log_initial_context`
        reports them apart. Joined with a newline they are the segment they used to be.

        The `PageContext` comes back out because the tools need it: whether the page went in
        whole decides whether `search_course` still searches it.
        """
        course_summary, activity_summary = self.ctx_data.get_summary_texts(
            course_key, activity_key)
        if not course_summary:
            return [{"name": "course_summary", "message": NO_COURSE_CONTEXT}], None

        course_map = render_course_map(self.course_db, course_key,
                                       current=activity_key)

        page = await current_page(
            course_key=course_key, activity_key=activity_key, query=query,
            source=self.courses, db=self.course_db,
            embed=self.courses.query_embedder(self._create_embedding),
            evidence=evidence)
        summary = activity_summary or "(no summary for this page)"
        if page is None:
            page_segment = PAGE_SUMMARY_ONLY.format(summary=summary)
        elif page.whole:
            page_segment = PAGE_WHOLE.format(text=page.text)
        else:
            page_segment = PAGE_EXCERPT.format(total=page.total, used=page.used,
                                               summary=summary, text=page.text)
        return [
            {"name": "course_summary",
             "message": CONTEXT_COURSE.format(course_summary=course_summary)},
            {"name": "course_map", "message": CONTEXT_MAP.format(course_map=course_map)},
            {"name": "page", "message": CONTEXT_PAGE.format(page=page_segment)},
        ], page

    async def system_message_parts(self, query: str, course_key: str, activity_key: str,
                                   evidence: Evidence
                                   ) -> tuple[list[dict[str, str]], PageContext | None]:
        """The named parts of the system message, in the order they are joined.

        Returned rather than joined here because the last part depends on the tool list,
        and the tool list depends on the `PageContext` this call produces.
        """
        context, page = await self._context_parts(query, course_key, activity_key,
                                                  evidence)
        rules = SYSTEM_RULES.format(
            script_instruction=SCRIPT_INSTRUCTION.format(script=dominant_script(query)),
            scope=SCOPE)
        parts = ([{"name": "header", "message": SYSTEM_HEADER}] + context
                 + [{"name": "rules", "message": rules}])
        return parts, page

    # ------------------------------------------------------------------ the tools

    def _build_tools(self, course_key: str, activity_key: str,
                     page: PageContext | None, evidence: Evidence) -> list:
        """The tools this request is offered. `page` decides whether one of them exists."""
        tools = []
        course = dict(source=self.courses, db=self.course_db,
                      embed=self.courses.query_embedder(self._create_embedding),
                      evidence=evidence)
        if course_key and course_key in self.ctx_data.course_dict:
            tools.append(course_search_tool(
                course_key=course_key, exclude_activity=activity_key, **course))
            if page is not None and not page.whole:
                tools.append(current_page_search_tool(
                    course_key=course_key, only_activity=activity_key, **course))
        for bundle in self.bundles:
            tools.append(bundle_search_tool(
                source=bundle, embed=bundle.query_embedder(self._create_embedding),
                evidence=evidence))
        if PLATFORM_COURSE_KEY in self.ctx_data.course_dict:
            tools.append(platform_search_tool(
                source=self.courses, db=self.course_db,
                embed=self.courses.query_embedder(self._create_embedding),
                evidence=evidence))
        return tools

    def _required_tool(self, ask: Ask, tools: list) -> Command | None:
        """What the first turn must fetch, of what the teacher asked for.

        A command whose tool this request does not offer -- no bundle loaded, a model
        configured without tools -- is dropped rather than raised: the teacher still asked
        a question, and it is still answerable without the material they hoped for.
        """
        offered = {tool.name for tool in tools}
        for word, command in zip(ask.commands, ask.requires):
            if command.tool in offered:
                logger.info("the teacher wrote /%s, so the prompt asks for %s and the "
                            "first turn has to gather -- pinned to that tool only if "
                            "it gathers without it", word, command.tool)
                return command
            logger.info("the teacher wrote /%s, but %s is not offered for this question -- "
                        "answering without it", word, command.tool)
        return None

    # ------------------------------------------------------------------ answering

    async def generate_answer(self,*, history: list[tuple[str,str]], query: str,
                            course_key: str, activity_key: str, model_name,
                            progress_callback: ProgressCallback | None = None
                            ) -> tuple[AsyncIterator[str], QueryContext]:
        query_context = QueryContext()
        model = model_name or CHAT_MODEL
        config = self.get_model_config(model)
        client = self._get_async_openai_client(requested_model=model)

        encoding = self._encoding_for(config)

        def count(text: str) -> int:
            return self.count_tokens(text, encoding)

        evidence = Evidence(count_tokens=count, max_tokens=evidence_budget(
            context_size=config.context_size,
            history_tokens=sum(count(item[0] + item[1]) for item in history)))
        # Read before anything searches with the question: `ask.query` is the sentence
        # without the commands, and it is that sentence the page is searched with.
        ask = read_commands(query)
        await report_progress(progress_callback, "reading_page")
        parts, page = await self.system_message_parts(
            ask.query, course_key, activity_key, evidence)

        tools = (self._build_tools(course_key, activity_key, page, evidence)
                 if config.supports_tools else [])
        if not config.supports_tools:
            logger.info("model '%s' is configured without tool support -- answering in one "
                        "turn from the page and course map alone", config.name)
        demand = self._required_tool(ask, tools)
        require = demand.tool if demand else None
        if demand:
            parts.append({"name": "required_tool",
                          "message": REQUIRED_SOURCE.format(source=demand.source)})

        query_context.add_system_message_parts(parts, encoding)
        messages = create_message("\n".join(part["message"] for part in parts),
                                  history, ask.query)
        for item in history:
            query_context.add_encoding_length("history", item[0] + item[1], encoding)
        query_context.add_encoding_length("user_query", ask.query, encoding)

        log_initial_context(config=config, sizes=query_context.token_size, page=page,
                            tools=tools, exchanges=len(history), evidence=evidence,
                            require=require)

        # The last turn's prompt size, kept for the closing report.
        turn = 0
        prompt_tokens = 0

        async def complete(*, messages, tools, stream, tool_choice=None):
            nonlocal turn, prompt_tokens
            used = sum(count(m.get("content") or "") for m in messages)
            if used > config.context_size - MAX_ANSWER_TOKENS:
                raise QueryError((
                    f"Context too large for model. Tokens used: {used}",
                    f"Response tokens: {MAX_ANSWER_TOKENS}",
                    f"Model token limit: {config.context_size}"))
            turn += 1
            grew = used - prompt_tokens
            prompt_tokens = used
            logger.info("turn %d: %s go to the model%s, %s", turn, narration.tok(used),
                        f" (+{narration.tok(grew)} since the turn before)"
                        if turn > 1 else "",
                        f"{narration.plural(len(tools or []), 'tool')} offered"
                        + (", and it has to gather from at least one of them before it "
                           "answers" if tool_choice == "required"
                           else f", and it has to call {require}" if tool_choice else "")
                        if tools
                        else "no tools this time -- it has to answer from what it has")
            return await client.chat.completions.create(
                model=config.name,
                messages=messages,
                stream=stream,
                max_completion_tokens=MAX_ANSWER_TOKENS,
                temperature=0,
                # `omit` drops the field entirely; `None` would send "tools": null,
                # which the vLLM servers reject.
                tools=tools if tools else omit,
                tool_choice=tool_choice or omit,
                extra_body=config.extra_body)

        # Fetched, then read, then written up: three stages, because the reader waits
        # through all three and one "working..." says only that the server is alive.
        def names(calls) -> str:
            return ", ".join(call["name"] for call in calls)

        async def on_round(calls) -> None:
            await report_progress(progress_callback, "retrieving", names(calls))

        async def on_results(calls) -> None:
            await report_progress(progress_callback, "analyzing", names(calls))

        async def on_answer() -> None:
            await report_progress(progress_callback, "writing")

        loop = ToolLoop(complete=complete, tools=tools, require=require,
                        on_round=on_round, on_results=on_results, on_answer=on_answer)

        async def answer_generator():
            async for delta in loop.stream(messages):
                yield delta
            for label, payload in loop.result.transcript:
                query_context.add_system_message_parts(
                    [{"name": f"{TOOL_PART_PREFIX}{label}", "message": payload}], encoding)
            query_context.set_chunk_metadata(evidence.provenance)
            log_total_budget(config=config, sizes=query_context.token_size, page=page,
                             exchanges=len(history), evidence=evidence,
                             result=loop.result, prompt_tokens=prompt_tokens)

        await report_progress(progress_callback, "preparing_answer")
        return answer_generator(), query_context
