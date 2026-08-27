"""How the answering pipeline says what it did.

`debug_stream` tees these records into the browser as well as the console, so they are
written for someone watching one question being answered. INFO carries the shape of an
outcome; `distances()` keeps the per-hit numbers a cutoff is calibrated from at DEBUG.
"""

import json
from typing import Any, Callable, Iterable, Sequence, Union

INDENT = "    "

RULE = "---"                # a `table()` row that draws a rule instead of a value

# A label and a value, optionally with a note to trail them -- or `RULE`.
Row = Union[tuple[str, str], tuple[str, str, str], str]


def tok(value: int) -> str:
    return f"{value:,} tok"


def count(value: int) -> str:
    return f"{value:,}"


def share(part: int, whole: int) -> str:
    return "--" if whole <= 0 else f"{round(100 * part / whole)}%"


def plural(value: int, singular: str, plural_form: str | None = None) -> str:
    """`1 call` / `2 calls` -- written out, because `call(s)` reads like a placeholder."""
    return f"{count(value)} {singular if value == 1 else plural_form or singular + 's'}"


def table(rows: Sequence[Row]) -> str:
    """Label/value pairs in aligned columns, with an optional note trailing each row.

    Values are right-aligned so two sizes can be compared by column, not by counting digits.
    """
    body = [row for row in rows if row != RULE]
    labels = max((len(row[0]) for row in body), default=0)
    values = max((len(row[1]) for row in body), default=0)

    lines = []
    for row in rows:
        if row == RULE:
            lines.append(INDENT + "-" * (labels + 2 + values))
            continue
        line = f"{INDENT}{row[0].ljust(labels)}  {row[1].rjust(values)}"
        if len(row) > 2 and row[2]:
            line += f"   {row[2]}"
        lines.append(line.rstrip())
    return "\n".join(lines)


def block(*lines: str) -> str:
    """Several lines as one log record: a record is the unit both consumers keep whole,
    so anything meant to be read together has to be written together."""
    return "\n".join(line for line in lines if line)


def listing(items: Iterable[str]) -> str:
    """A numbered list, one item per line, indented under whatever introduced it."""
    return "\n".join(f"{INDENT}{i}. {item}" for i, item in enumerate(items, start=1))


def call_block(name: str, arguments: Any) -> str:
    """One tool call as the reader should see it: what was called, and what was asked.

    `questions` is the model's own words for what it went looking for, and as JSON it
    arrives as one unbroken line. Laid out here; any other shape falls back to JSON.
    """
    if isinstance(arguments, dict):
        questions = arguments.get("questions")
        if (isinstance(questions, list) and questions
                and all(isinstance(q, str) for q in questions)):
            rest = {k: v for k, v in arguments.items() if k != "questions"}
            head = f"{name} asks {plural(len(questions), 'question')}:"
            if rest:
                head += f" (also {json.dumps(rest, ensure_ascii=False)})"
            return head + "\n" + listing(questions)
    return f"{name}({json.dumps(arguments, ensure_ascii=False)})"


def evidence_line(evidence: Any) -> str:
    """Where the request's evidence budget stands. Logged per call, not only at the end:
    a run that gathers too much does it one call at a time."""
    return (f"evidence so far {tok(evidence.tokens)} of {tok(evidence.max_tokens)} "
            f"({share(evidence.tokens, evidence.max_tokens)}), "
            f"{tok(evidence.remaining)} left"
            + (" -- spent, no more searching" if evidence.exhausted else ""))


def _span(values: Sequence[float]) -> str:
    if not values:
        return "none"
    low, high = min(values), max(values)
    return f"{low:.3f}" if low == high else f"{low:.3f}-{high:.3f}"


def _named(hit: Any, name: "Callable[[Any], Any] | None") -> str:
    if name is None:
        return ""
    label = name(hit)
    return f" ({label})" if label else ""


def search_outcome(kind: str, hits: Sequence[Any], cutoff: "float | None",
                   name: "Callable[[Any], Any] | None" = None) -> str:
    """One search's result in a sentence: fetched, kept, and how far away."""
    if not hits:
        return f"no {kind} came back"

    all_distances = [hit.distance for hit in hits]
    if cutoff is None:
        return (f"fetched {plural(len(hits), kind)}, keeping every one "
                f"({_span(all_distances)}, no distance cutoff here)")

    kept = [d for d in all_distances if d <= cutoff]
    dropped = [d for d in all_distances if d > cutoff]
    if not kept:
        nearest = min(all_distances)
        closest = next(h for h in hits if h.distance == nearest)
        return (f"fetched {plural(len(hits), kind)}, keeping none -- the nearest was "
                f"{nearest:.3f}{_named(closest, name)}, past the {cutoff:.3f} cutoff")

    line = (f"fetched {plural(len(hits), kind)}, keeping "
            f"{'every one' if not dropped else count(len(kept))} "
            f"within {cutoff:.3f} ({_span(kept)})")
    if dropped:
        line += f"; {count(len(dropped))} too far ({_span(dropped)})"
    return line


def distances(hits: Sequence[Any], cutoff: "float | None",
              name: "Callable[[Any], Any] | None" = None) -> str:
    """Every hit with its distance, `far` marking the ones the cutoff drops. For DEBUG."""
    def label(hit: Any) -> str:
        return str(name(hit)) if name else str(hit.id)[:8]

    return ", ".join(
        f"{label(hit)}={hit.distance:.3f}"
        f"{'' if cutoff is None or hit.distance <= cutoff else ' far'}"
        for hit in hits) or "none"
