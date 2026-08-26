import json
import logging
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Awaitable, Callable

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
                 max_rounds: int = DEFAULT_MAX_ROUNDS,
                 on_round: Callable[[list[dict[str, Any]]], Awaitable[None]] | None = None):
        self.complete = complete
        self.tools = {tool.name: tool for tool in tools}
        self.definitions = [tool.definition for tool in tools]
        self.max_rounds = max_rounds
        self.on_round = on_round
        self.result = ToolLoopResult()

    async def stream(self, messages: list[dict[str, Any]]) -> AsyncIterator[str]:
        """Yield the answer's text as it arrives, running tool rounds in between."""
        messages = list(messages)

        for _ in range(self.max_rounds + 1):
            offer_tools = bool(self.definitions) and self.result.rounds < self.max_rounds
            calls = _Calls()
            answered = False

            completion = await self.complete(
                messages=messages,
                tools=self.definitions if offer_tools else None,
                stream=True)
            async for chunk in completion:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if getattr(delta, "tool_calls", None):
                    calls.add(delta.tool_calls)
                if getattr(delta, "content", None):
                    answered = True
                    yield delta.content

            collected = calls.collected()
            if not collected:
                if not answered:
                    logger.warning("answering turn produced neither content nor tool calls")
                return

            self.result.rounds += 1
            logger.info("tool round %d/%d: %d call(s)",
                        self.result.rounds, self.max_rounds, len(collected))
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

        logger.warning("tool loop exhausted %d rounds without an answer", self.max_rounds)

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
        logger.info("  %s(%s)", call["name"],
                    json.dumps(arguments, ensure_ascii=False)[:300])
        output = await tool.run(arguments)
        self.result.transcript.append(
            (f"{call['name']} {json.dumps(arguments, ensure_ascii=False)}",
             json.dumps(output, ensure_ascii=False, indent=2)))
        return output
