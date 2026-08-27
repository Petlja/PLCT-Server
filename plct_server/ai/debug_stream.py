"""Streaming what the AI pipeline logs, alongside the answer it produces.

The pipeline already narrates itself: the engine reports the tokens each turn costs, the
tool loop reports its rounds, and every tool logs the call it ran. `debug_mode` in the
configuration tees those log records into the answer stream, so the UI can show the same
story the server console shows -- without a second narration channel threaded through
every layer of the pipeline.

The tee is per request. `capture()` binds a sink to the current context, and because
asyncio copies the context into each task, records logged anywhere under the task that
answers one question reach that question's sink and never another's. Outside a
`capture()` the handler is inert, so every other logging consumer sees what it always saw.

Turning the tee on raises the traced loggers to INFO, because the narration this exists
to show is logged at INFO and a logger below that level never reaches a handler at all.
That is the one side effect: those modules also get louder in the server's own log, which
is what asking for a debug mode is asking for. `verbose: true` adds the DEBUG detail.
"""

import logging
import time

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Callable, Iterator

# The pipeline's own loggers. Records from anything below these names are teed and the
# rest is left out: a trace full of httpx connection notes helps nobody.
TRACED_LOGGERS = ("plct_server.ai", "plct_server.knowledge")

PACKAGE_PREFIX = "plct_server."

TraceSink = Callable[[dict[str, Any]], None]


@dataclass
class _Trace:
    sink: TraceSink
    started: float


_trace: ContextVar[_Trace | None] = ContextVar("plct_debug_trace", default=None)


def _event(trace: "_Trace", *, level: str, source: str, message: str) -> dict[str, Any]:
    """One line of the trace, stamped with how far into the request it happened."""
    return {
        "type": "debug",
        "level": level,
        "source": source,
        "message": message,
        "elapsed": round(time.monotonic() - trace.started, 3),
    }


def as_event(record: logging.LogRecord, trace: "_Trace") -> dict[str, Any]:
    """One log record as the wire event the UI renders."""
    message = record.getMessage()
    if record.exc_info:
        message += "\n" + logging.Formatter().formatException(record.exc_info)
    source = record.name
    if source.startswith(PACKAGE_PREFIX):
        source = source[len(PACKAGE_PREFIX):]
    return _event(trace, level=record.levelname, source=source, message=message)


def note(message: str, *, source: str = "ui", level: str = "INFO") -> None:
    """Put a line into the current trace that no logger produced.

    For what the reader was shown rather than what the pipeline did -- the two are worth
    reading side by side, and the progress message is the only part of a run that reaches
    them while it is still running. A no-op outside a `capture()`, like the tee itself,
    so the caller needs no test for whether debug mode is on.
    """
    trace = _trace.get()
    if trace is None:
        return
    trace.sink(_event(trace, level=level, source=source, message=message))


class _TeeHandler(logging.Handler):
    """Hands each record to the sink bound to the context it was logged in, if any."""

    def emit(self, record: logging.LogRecord) -> None:
        trace = _trace.get()
        if trace is None:
            return
        try:
            trace.sink(as_event(record, trace))
        except Exception:               # a broken sink must not break the answer
            self.handleError(record)    # whose pipeline it is watching


_handler: _TeeHandler | None = None


def install() -> None:
    """Attach the tee to the traced loggers. Only the first call does anything.

    Called from `capture()`, so a server that never turns debug mode on never grows the
    handler at all.
    """
    global _handler
    if _handler is not None:
        return
    _handler = _TeeHandler(level=logging.DEBUG)
    for name in TRACED_LOGGERS:
        traced = logging.getLogger(name)
        traced.addHandler(_handler)
        # A record below the logger's level never reaches any handler, so a server left
        # at the default WARNING would tee an empty trace. Lift it just far enough.
        if traced.getEffectiveLevel() > logging.INFO:
            traced.setLevel(logging.INFO)


@contextmanager
def capture(sink: TraceSink | None) -> Iterator[None]:
    """Tee the pipeline's log records to `sink` for the duration of the block.

    A `None` sink makes this a no-op, which is how the caller expresses "debug mode is
    off" without wrapping the block in a conditional.

    Enter it inside the task that runs the pipeline: the binding follows that task's
    context, so two questions answered at once never see each other's records.
    """
    if sink is None:
        yield
        return
    install()
    token = _trace.set(_Trace(sink=sink, started=time.monotonic()))
    try:
        yield
    finally:
        _trace.reset(token)
