import json
import logging

from pydantic import BaseModel
from enum import Enum


logger = logging.getLogger(__name__)


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
                            "description": "The restated question, elaborated by the model."
                        },
                        "classify_query": {
                            "type": "string", 
                            "enum": ["course", "current_lecture", "platform", "unsure"],
                            "description": 
                            """
                            Classify the user question as referring to a course, the current lecture, the platform, or unsure.
                            The `course` classification is used when the question is about the course in general.

                            The `current_lecture` classification is used when the question is about the current lecture.

                            The `platform` classification is used when the question is about the petlja.org platform where the course is hosted.

                            The `unsure` classification is used when the model is unsure about the classification.
                            """
                        },
                   },
                    "required": ["restated_question", "classify_query"], 
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

class QueryClassification(BaseModel):
    classification: Classification
    restated_question: str

class QueryClassificationError(Exception):
    pass

def parse_query_classification(response):
    try:
        finish_reason = response.choices[0].finish_reason

        if finish_reason in ["length", "content_filter"]:
            raise QueryClassificationError(f"Response filtered out. Reason: {finish_reason}")

        if finish_reason in ["tool_calls", "stop"]:
            tool_call = response.choices[0].message.tool_calls[0]
            arguments_json = tool_call.function.arguments
            arguments_dict = json.loads(arguments_json)

            return QueryClassification(
                restated_question=arguments_dict.get("restated_question", None),
                classification=Classification(arguments_dict.get("classify_query", "unsure"))
            )

        raise QueryClassificationError(f"Unexpected finish reason: {finish_reason}")

    except Exception as e:
        logger.error(f"Error parsing query classification: {e}")
        return QueryClassification(
            restated_question=None,
            classification=Classification.UNSURE
        )

    


