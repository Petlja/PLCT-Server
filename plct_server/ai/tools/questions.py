"""The one shape every tool here has: `questions: string[]` in, passages out."""

from typing import Any

# Every tool here takes the same argument, so every tool makes the same promise about it.
SHARED_TAIL = (
    "Send several related questions in one call to gather everything at once: passages are "
    "deduplicated across the questions and across every previous call, so you receive each "
    "one only once."
)


def too_far(corpus: str, questions: "list[str] | None" = None) -> str:
    """What a search that found nothing near enough says back.

    Named questions rather than "nothing matched": one call may carry several, and the
    model has to know which of them to rethink. The steer is the same for every corpus
    here, because so is the usual cause -- a question about the material rather than about
    its subject, and an index can only rank, never report an absence.
    """
    which = (", ".join(f'"{question}"' for question in questions) if questions
             else "these questions")
    return (f"Nothing in {corpus} was close enough to {which}. Reword: ask for the subject "
            "matter itself, in the words the material would use, rather than about the "
            "material -- or take it that it does not cover what was asked.")


def definition(name: str, description: str) -> dict[str, Any]:
    """The OpenAI tool definition. No ids, no refs, no `k`, no scope flags."""
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            # strict belongs inside `function`; on the wrapper it is silently ignored.
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "questions": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "description": (
                                "One focused question in natural language, and nothing "
                                "else: no titles, no quoted names, no instruction about "
                                "what to do with the answer. Ask about the subject matter, "
                                "in the words the material itself would use -- passages "
                                "are found by meaning, so a question phrased the way its "
                                "answer is written finds that answer, and every word that "
                                "is not subject matter pulls the search away from it. "

                                "Do not ask about the material -- whether it contains "
                                "something, whether a topic is covered, how much of it "
                                "there is. No passage answers a question of that kind, and "
                                "the closest unrelated text comes back in its place. "

                                "This holds when you want material from a particular place "
                                "you can name: ask what that place teaches, never for the "
                                "place. Naming it does not fetch it -- the name is matched "
                                "as text like any other, so two questions differing only "
                                "in the name search for nearly the same thing and come "
                                "back with nearly the same passages. Instead of \"list two "
                                "exercises from the activity 'Sorting algorithms'\", ask "
                                "\"how is insertion sort carried out, step by step?\". "
                                "Ask for the thing itself and see what arrives."
                            ),
                        },
                        "description": "A list of focused questions.",
                    }
                },
                "required": ["questions"],
                "additionalProperties": False,
            },
        },
    }


def parse(arguments: Any) -> list[str] | dict[str, Any]:
    """The questions, stripped -- or the error dict to hand back to the model."""
    if not isinstance(arguments, dict):
        return {"error": "Arguments must be a JSON object."}
    questions = arguments.get("questions")
    if not isinstance(questions, list):
        return {"error": "questions must be an array of strings."}
    if not questions:
        return {"error": "questions array must not be empty."}
    if any(not isinstance(q, str) or not q.strip() for q in questions):
        return {"error": "Each question must be a non-empty string."}
    return [q.strip() for q in questions]
