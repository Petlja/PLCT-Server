import json
import logging
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Awaitable, Callable

from .. import narration

logger = logging.getLogger(__name__)

DEFAULT_MAX_ROUNDS = 4
MAX_CALLS_PER_ROUND = 8


class _Calls:
    """Tool calls reassembled from streaming deltas, keyed by their index."""

    def __init__(self) -> None:
        self._by_index: dict[int, dict[str, Any]] = {}

    def add(self, delta_calls) -> None:
        for part in delta_calls or []:
            call = self._by_index.setdefault(
                part.index, {"id": "", "name": "", "arguments": ""})
            if getattr(part, "id", None):
                call["id"] = part.id
            function = getattr(part, "function", None)
            if function is not None:
                if getattr(function, "name", None):
                    call["name"] = function.name
                if getattr(function, "arguments", None):
                    call["arguments"] += function.arguments

    def collected(self) -> list[dict[str, Any]]:
        return [self._by_index[index] for index in sorted(self._by_index)]


@dataclass
class ToolLoopResult:
    rounds: int = 0
    calls: int = 0
    transcript: list[tuple[str, str]] = field(default_factory=list)   # (label, payload)


class ToolLoop:
    """Runs one question to a streamed answer, offering `tools` along the way."""

    def __init__(self, *, complete: Callable[..., Awaitable[Any]], tools: list,
                 max_rounds: int = DEFAULT_MAX_ROUNDS, require: str | None = None,
                 on_round: Callable[[list[dict[str, Any]]], Awaitable[None]] | None = None,
                 on_results: Callable[[list[dict[str, Any]]], Awaitable[None]] | None = None,
                 on_answer: Callable[[], Awaitable[None]] | None = None):
        self.complete = complete
        self.tools = {tool.name: tool for tool in tools}
        self.definitions = [tool.definition for tool in tools]
        self.max_rounds = max_rounds
        # Material the teacher asked for by name, as the tool that reaches it.
        self.require = require if require in self.tools else None
        # Asked for material, read it, started writing -- three moments, because one
        # "working..." cannot say which is happening.
        self.on_round = on_round
        self.on_results = on_results
        self.on_answer = on_answer
        self.result = ToolLoopResult()

    def _choice(self, satisfied: bool) -> Any:
        """What this turn is obliged to do, when the teacher asked for one source by name.

        `required` rather than the tool's name, because naming it permits that one call and
        nothing beside it -- and a question about teaching *this lesson* needs the lesson
        too, in the same round. So the first turn is only made to gather, and the source the
        teacher asked for is carried by the prompt. The name is the backstop: one turn, on
        the round after one that gathered without it, and then never again -- a choice that
        keeps re-forcing is a loop that searches every round and never writes.
        """
        if not self.require or satisfied:
            return None
        if self.result.rounds == 0:
            return "required"
        if self.result.rounds == 1:
            logger.info("the model gathered without %s, which the teacher asked for -- this "
                        "turn has to call it", self.require)
            return {"type": "function", "function": {"name": self.require}}
        return None

    async def stream(self, messages: list[dict[str, Any]]) -> AsyncIterator[str]:
        """Yield the answer's text as it arrives, running tool rounds in between."""
        messages = list(messages)
        satisfied = False

        for _ in range(self.max_rounds + 1):
            offer_tools = bool(self.definitions) and self.result.rounds < self.max_rounds
            calls = _Calls()
            answered = False

            completion = await self.complete(
                messages=messages,
                tools=self.definitions if offer_tools else None,
                tool_choice=self._choice(satisfied) if offer_tools else None,
                stream=True)
            async for chunk in completion:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if getattr(delta, "tool_calls", None):
                    calls.add(delta.tool_calls)
                if getattr(delta, "content", None):
                    if not answered and self.on_answer:
                        await self.on_answer()
                    answered = True
                    yield delta.content

            collected = calls.collected()
            if not collected:
                if not answered:
                    logger.warning("answering turn produced neither content nor tool calls")
                return

            satisfied = satisfied or any(call["name"] == self.require
                                         for call in collected)
            self.result.rounds += 1
            logger.info("round %d of at most %d: the model asks for %s",
                        self.result.rounds, self.max_rounds,
                        narration.plural(len(collected), "tool call"))
            if self.on_round:
                await self.on_round(collected)

            messages.append({
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {"id": call["id"], "type": "function",
                     "function": {"name": call["name"], "arguments": call["arguments"]}}
                    for call in collected],
            })
            for position, call in enumerate(collected, start=1):
                messages.append({
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": json.dumps(await self._run(position, call),
                                          ensure_ascii=False),
                })
            if self.on_results:
                await self.on_results(collected)

        logger.warning("the model used all %d rounds without ever writing an answer",
                       self.max_rounds)

    async def _run(self, position: int, call: dict[str, Any]) -> dict[str, Any]:
        """One call's output. Every call needs one, or the next request is malformed."""
        if position > MAX_CALLS_PER_ROUND:
            return {"error": f"Only {MAX_CALLS_PER_ROUND} calls run in one round and this "
                             "one did not. Request it again in your next turn."}
        tool = self.tools.get(call["name"])
        if tool is None:
            return {"error": f"Unknown tool: {call['name']}"}
        try:
            arguments = json.loads(call["arguments"] or "{}")
        except json.JSONDecodeError:
            return {"error": "Arguments were not valid JSON. Send them again."}

        self.result.calls += 1
        logger.info("%s", narration.call_block(call["name"], arguments))
        output = await tool.run(arguments)
        self.result.transcript.append(
            (f"{call['name']} {json.dumps(arguments, ensure_ascii=False)}",
             json.dumps(output, ensure_ascii=False, indent=2)))
        return output
