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
                        

CONVERSATION_CONTINUATION_DESCRIPTION = """
Two follow-up suggestions that the teacher can click to have the assistant perform the action on their behalf.

The follow-up suggestions should be in the same language as the teacher's question.

Take into account history and avoid repeating the suggestions that have been used by the teacher, they will show in the history of the conversation.

These suggestions should be **concise and actionable**—representing things the assistant can do for the teacher.

Focus on providing clear, **action-oriented commands** the assistant can execute directly when clicked. 

Never ask the teacher to do something themselves, such as "Can you please...?" or "Would you mind...?" or "Do you want to...?" or "Could you...?".

Examples of follow-up suggestions:
    - Create a test for the "{current lecture}".
    - Create a homework assignment for the "{current lecture}".
    - Show an example of "{current topic}".
    - Break down the "{current concept}" into simpler terms.
    - Create a quiz on "{current concept}".
    - Demonstrate how to apply "{current topic}" in practice.

**Avoid verbose descriptions or questions.** The suggestions should be brief and phrased as direct actions.
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
                            "description": "The restated question, elaborated by the model. In the same language as the original question."
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
                    "required": ["restated_question", "classify_query", "possible_conversation_continuation"], 
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

class StructuredOutputResponse(BaseModel):
    classification: Classification
    restated_question: str
    followup_questions: list[str]

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
                followup_questions=followup_questions
            )

        raise QueryClassificationError(f"Unexpected finish reason: {finish_reason}")

    except Exception as e:
        logger.error(f"Error parsing query classification: {e}")
        return StructuredOutputResponse(
            restated_question=query,
            classification=Classification.UNSURE,
            followup_questions=[]
        )

    


