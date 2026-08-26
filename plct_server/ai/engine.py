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
from .tools import (Evidence, PLATFORM_COURSE_KEY, ToolLoop, bundle_search_tool,
                    current_page, offering, render_course_map)
from .tools.course_tools import course_search_tool, platform_search_tool
from .prompt_templates import (CONTEXT_SEGMENT, NO_COURSE_CONTEXT, PAGE_EXCERPT,
                               PAGE_SUMMARY_ONLY, PAGE_WHOLE, SCOPE, SCRIPT_INSTRUCTION,
                               SYSTEM_HEADER, SYSTEM_RULES)

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


async def report_progress(progress_callback: ProgressCallback | None, stage: str,
                          detail: str | None = None) -> None:
    if progress_callback:
        await progress_callback(stage, detail)


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

    async def _context_segment(self, query: str, course_key: str, activity_key: str,
                               evidence: Evidence) -> str:
        """Course summary, course map, and the page the teacher is on -- as text."""
        course_summary, activity_summary = self.ctx_data.get_summary_texts(
            course_key, activity_key)
        if not course_summary:
            return NO_COURSE_CONTEXT

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
        return CONTEXT_SEGMENT.format(course_summary=course_summary,
                                      course_map=course_map, page=page_segment)

    async def make_system_message(self, query: str, course_key: str, activity_key: str,
                                  evidence: Evidence,
                                  query_context: QueryContext | None = None,
                                  encoding: Encoding | None = None) -> str:
        context = await self._context_segment(query, course_key, activity_key, evidence)
        rules = SYSTEM_RULES.format(
            script_instruction=SCRIPT_INSTRUCTION.format(script=dominant_script(query)),
            scope=SCOPE)
        if query_context:
            query_context.add_system_message_parts(
                [{"name": "header", "message": SYSTEM_HEADER},
                 {"name": "context", "message": context},
                 {"name": "rules", "message": rules}],
                encoding or self.fallback_encoding)
        return SYSTEM_HEADER + "\n" + context + "\n" + rules

    # ------------------------------------------------------------------ the tools

    def _build_tools(self, course_key: str, activity_key: str,
                     evidence: Evidence) -> list:
        tools = []
        if course_key and course_key in self.ctx_data.course_dict:
            tools.append(course_search_tool(
                course_key=course_key, activity_key=activity_key,
                source=self.courses, db=self.course_db,
                embed=self.courses.query_embedder(self._create_embedding),
                evidence=evidence))
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

        evidence = Evidence(count_tokens=count)
        system_message = await self.make_system_message(query, course_key, activity_key,
                                                        evidence, query_context, encoding)
        messages = create_message(system_message, history, query)
        for item in history:
            query_context.add_encoding_length("history", item[0] + item[1], encoding)
        query_context.add_encoding_length("user_query", query, encoding)

        tools = (self._build_tools(course_key, activity_key, evidence)
                 if config.supports_tools else [])
        if not config.supports_tools:
            logger.info("model '%s' is configured without tool support -- answering in one "
                        "turn from the page and course map alone", config.name)

        async def complete(*, messages, tools, stream):
            used = sum(count(m.get("content") or "") for m in messages)
            if used > config.context_size - MAX_ANSWER_TOKENS:
                raise QueryError((
                    f"Context too large for model. Tokens used: {used}",
                    f"Response tokens: {MAX_ANSWER_TOKENS}",
                    f"Model token limit: {config.context_size}"))
            logger.info("turn: %d token(s) in, tools %s", used, "on" if tools else "off")
            return await client.chat.completions.create(
                model=config.name,
                messages=messages,
                stream=stream,
                max_completion_tokens=MAX_ANSWER_TOKENS,
                temperature=0,
                # `omit` drops the field entirely; `None` would send "tools": null,
                # which the vLLM servers reject.
                tools=tools if tools else omit,
                extra_body=config.extra_body)

        async def on_round(calls) -> None:
            await report_progress(progress_callback, "retrieving",
                                  ", ".join(c["name"] for c in calls))

        loop = ToolLoop(complete=complete, tools=tools, on_round=on_round)

        async def answer_generator():
            async for delta in loop.stream(messages):
                yield delta
            for label, payload in loop.result.transcript:
                query_context.add_system_message_parts(
                    [{"name": f"tool: {label}", "message": payload}], encoding)
            query_context.set_chunk_metadata(evidence.provenance)
            logger.info("answered in %d tool round(s), %d call(s); evidence: %s",
                        loop.result.rounds, loop.result.calls, evidence.summary())

        await report_progress(progress_callback, "preparing_answer")
        return answer_generator(), query_context
