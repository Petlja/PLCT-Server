import json
import logging

from pydantic import BaseModel
from enum import Enum


logger = logging.getLogger(__name__)


TOOLS_CHOICE_DEF : dict[str, object] = {
    "type": "function",
    "function": {
        "name": "text_classification",
    }
}

TOOLS_DEF : list[dict[str, object]] = [
        {
            "type": "function",
            "strict": True,
            "function": {
                "name": "text_classification",
                "description": "Restates the question and classifies it.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "restated_question": {
                            "type": "string",
                            "description": "The restated question, elaborated by the model."},
                        "refers_to_course": {
                            "type": "string", 
                            "enum": ["yes", "no", "unsure"],
                            "description": "Does the question refer to the course?"},
                        "refers_to_lecture": {
                            "type": "string", 
                            "enum": ["yes", "no", "unsure"],
                            "description": "Does the question refer to the lecture? If the question refers to a task or a question it is most likely a lecture question."}
                    },
                    "required": ["restated_question", "refers_to_course", "refers_to_lecture"], 
                    "additionalProperties" : False
                },
            },
        }
    ]

class Answer(Enum):
    YES = "yes"
    NO = "no"
    UNSURE = "unsure"

class QueryClassification(BaseModel):
    refers_to_course: Answer
    refers_to_lecture: Answer
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
                refers_to_course=arguments_dict.get("refers_to_course", Answer.UNSURE),
                refers_to_lecture=arguments_dict.get("refers_to_lecture", Answer.UNSURE),
                restated_question=arguments_dict.get("restated_question", None)
            )

        raise QueryClassificationError(f"Unexpected finish reason: {finish_reason}")

    except Exception as e:
        logger.error(f"Error parsing query classification: {e}")
        return QueryClassification(
            refers_to_course=Answer.UNSURE,
            refers_to_lecture=Answer.UNSURE,
            restated_question=None
        )

    


