import json
import logging

from pydantic import BaseModel
from enum import Enum


logger = logging.getLogger(__name__)


CLASSIFY_QUERY_DESCRIPTION = """
Classify the user's question as referring to a course, the current lecture, the platform, or unsure.

- **course** Used when the question is about the course in general, including overall topics or materials.

- **current_lecture** classification is used when the question is about the current lecture, including the current topic, concept and activities such as questions, code examples, and exercises. 

- **platform** classification is used when the question is about the petlja.org LMS platform where the course is hosted.

- **unsure** classification is used when you aren't sure how to classify the query.
"""

CLASSIFY_LANGUAGE_DESCRIPTION = """
Classify the language of the user's question as Serbian Cyrillic, Serbian Latin, English, or other.
"""
                        

CONVERSATION_CONTINUATION_DESCRIPTION = """
You are helping a teacher by suggesting follow-up questions they might ask an AI teaching assistant.
The teacher relies on the assistant to generate examples, tests, homework, and explanations.
Your job is to think about what the teacher might ask next, phrased as a question the teacher would say, not as something the assistant would do.
Keep the questions on the short side up to 100 characters.
Ensure that these follow-up questions:
- Are in the same language and script as the teacher's original question.
- Are concise, actionable, and related to the topic the teacher is asking about.
- Do not repeat any questions the teacher already asked or suggestions already made in this conversation.
"""



TOOLS_CHOICE_DEF : dict[str, object] = {
    "type": "function",
    "function": {
        "name": "question_classification",
    }
}

TOOLS_DEF : list[dict[str, object]] = [
        {
            "type": "function",
            "strict": True,
            "function": {
                "name": "question_classification",
                "description": "Restates the question and classifies it.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "restated_question": {
                            "type": "string",
                            "description": "Put your self in the teacher's shoes and rephrase the question in a way that is clear and concise."
                        },
                        "classify_language": {
                            "type": "string", 
                            "enum": ["sr-Cyrl", "sr-Latn", "en", "other"],
                            "description": CLASSIFY_LANGUAGE_DESCRIPTION
                        },
                        "classify_query": {
                            "type": "string", 
                            "enum": ["course", "current_lecture", "platform", "unsure"],
                            "description": CLASSIFY_QUERY_DESCRIPTION
                        },
                        "possible_conversation_continuation": {
                            "type": "object",
                            "properties": {
                                "continuation_1": {
                                    "type": "string",
                                    "description": "The first follow-up ask or question."
                                },
                                "continuation_2": {
                                    "type": "string",
                                    "description": "The second follow-up ask or question."
                                }
                            },
                            "required": ["continuation_1", "continuation_2"],
                            "description": CONVERSATION_CONTINUATION_DESCRIPTION
                        }

                   },
                    "required": ["restated_question", "classify_language", "classify_query", "possible_conversation_continuation"], 
                    "additionalProperties" : False
                },
            },
        }
    ]

class Classification(Enum):
    COURSE = "course"
    CURRENT_LECTURE = "current_lecture"
    PLATFORM = "platform"
    UNSURE = "unsure"

class QueryLanguage(Enum):
    SR_CYRL = "sr-Cyrl"
    SR_LATN = "sr-Latn"
    EN = "en"
    DEFAULT = "default"

LANGUAGE_RESPONSES : dict[QueryLanguage, str] = {
    QueryLanguage.SR_CYRL: "Answer in Serbian Cyrillic script.",
    QueryLanguage.SR_LATN: "Answer in Serbian Latin script.",
    QueryLanguage.EN: "Answer in English.",
    QueryLanguage.DEFAULT: "Answer in the same language as the question."
}

class StructuredOutputResponse(BaseModel):
    classification: Classification
    restated_question: str
    followup_questions: list[str]
    query_language: QueryLanguage

def get_answer_language(structured_output : StructuredOutputResponse) -> str:
    return LANGUAGE_RESPONSES.get(
        structured_output.query_language,
        QueryLanguage.DEFAULT
    )




class QueryClassificationError(Exception):
    pass

def parse_query_classification(response : object, query :str) -> StructuredOutputResponse:
    try:
        finish_reason = response.choices[0].finish_reason

        if finish_reason in ["length", "content_filter"]:
            raise QueryClassificationError(f"Response filtered out. Reason: {finish_reason}")

        if finish_reason in ["tool_calls", "stop"]:
            tool_call = response.choices[0].message.tool_calls[0]
            arguments_json = tool_call.function.arguments
            arguments_dict = json.loads(arguments_json)

            followup_questions = [
                arguments_dict.get("possible_conversation_continuation", {}).get("continuation_1", ""),
                arguments_dict.get("possible_conversation_continuation", {}).get("continuation_2", "")
            ]

            return StructuredOutputResponse(
                restated_question=arguments_dict.get("restated_question", query),
                classification=Classification(arguments_dict.get("classify_query", "unsure")),
                followup_questions=followup_questions,
                query_language=QueryLanguage(arguments_dict.get("classify_language", "default"))

            )

        raise QueryClassificationError(f"Unexpected finish reason: {finish_reason}")

    except Exception as e:
        logger.error(f"Error parsing query classification: {e}")
        return StructuredOutputResponse(
            restated_question=query,
            classification=Classification.UNSURE,
            followup_questions=[],
            query_language=QueryLanguage.DEFAULT
        )

    


