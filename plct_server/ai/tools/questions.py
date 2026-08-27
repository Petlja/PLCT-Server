"""The one shape every tool here has: `questions: string[]` in, passages out."""

from typing import Any

# Every tool here takes the same argument, so every tool makes the same promise about it.
SHARED_TAIL = (
    "Send several related questions in one call to gather everything at once: passages are "
    "deduplicated across the questions and across every previous call, so you receive each "
    "one only once."
)


def too_far(corpus: str, questions: "list[str] | None" = None) -> str:
    """What a search that found nothing near enough says back."""
    which = (", ".join(f'"{question}"' for question in questions) if questions
             else "these questions")
    return (f"Nothing in {corpus} was close enough to {which}. Reword: ask for the subject "
            "matter itself, in the words the material would use, rather than about the "
            f"material. If it was already asked that way, take it that {corpus} does not "
            "cover it and go on under your instructions. This note is not for the teacher: "
            "what a search did or did not reach is never part of an answer.")


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
                                "else -- no titles, no quoted names, no instruction about "
                                "what to do with the answer. Passages are found by "
                                "meaning, so a question phrased the way its answer is "
                                "written finds that answer, and every word that is not "
                                "subject matter pulls the search away from it.\n\n"

                                "Ask about the subject matter, never about the material "
                                "-- whether it contains something, whether a topic is "
                                "covered, how much of it there is. Nothing answers a "
                                "question of that kind, and the closest unrelated text "
                                "comes back in its place.\n\n"

                                "Naming a place does not fetch it: the name is matched "
                                "as text like any other, so two questions differing only "
                                "in the name come back with nearly the same passages. Ask "
                                "what that place teaches instead. Not \"list two "
                                "exercises from the activity 'Sorting algorithms'\", but "
                                "\"how is insertion sort carried out, step by step?\"."
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
