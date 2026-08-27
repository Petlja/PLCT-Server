"""What the teacher can require of an answer by writing it in the question.

A command is a word dropped into the sentence wherever it reads naturally, not a prefix and
not a mode: `/teaching` says the answer has to be grounded in what one tool reaches, and the
rest of the sentence is still the question. It is lifted back out before anything searches
with that question -- the embedder has no notion of a command, and a token that means
nothing to it only pulls the search away from the subject.
"""

import re
from dataclasses import dataclass

from .knowledge_tools import TEACHING_LITERATURE

@dataclass(frozen=True)
class Command:
    """What one word asks for: the tool, and the material as the prompt may name it.

    Two names for the same thing because they are read by different readers. `tool` is
    machinery and goes in the request's `tool_choice`, where the forcing actually happens.
    `source` is what the model is told, in the words the rules already use for that body of
    knowledge -- a tool name in the prompt turns a question about teaching into a question
    about which tool to call, and that is a turn the answer never recovers from.
    """

    tool: str
    source: str


# The word the teacher writes -> what it asks for. Bound to the tool object rather than to
# its name in text: renaming a tool cannot silently detach its command.
COMMANDS: dict[str, Command] = {
    "teaching": Command(tool=TEACHING_LITERATURE.name,
                        source="the professional literature on teaching"),
}

# The slash must open the text or follow whitespace and the word must not run on into
# another path segment, which together are what keep `https://petlja.org/teaching` and
# `docs/teaching` and `/teaching/nesto` from reading as commands. What trails the word goes
# with it -- one space, and the comma a teacher naturally writes after an aside -- so a
# command lifted out of the middle of a sentence leaves the one separator its neighbours
# need rather than two, or a comma with nothing before it.
_COMMAND = re.compile(r"(?:(?<=^)|(?<=\s))/(\w+)\b(?!/)[,;:]?[ \t]?", re.UNICODE)


@dataclass(frozen=True)
class Ask:
    """One question as the engine should treat it: the text, and what it demands."""

    query: str
    commands: tuple[str, ...] = ()          # as written, for the log
    requires: tuple[Command, ...] = ()


def read_commands(question: str) -> Ask:
    """The question with its commands lifted out, or unchanged when it carries none."""
    found: list[str] = []

    def lift(match: re.Match) -> str:
        name = match.group(1).lower()
        if name not in COMMANDS:
            return match.group(0)
        if name not in found:
            found.append(name)
        return ""

    query = _COMMAND.sub(lift, question).strip()
    if not found or not query:
        # A question that is nothing but its command gives the model nothing to search for;
        # let it go through as written and be asked what they meant.
        return Ask(query=question)
    return Ask(query=query, commands=tuple(found),
               requires=tuple(COMMANDS[word] for word in found))
