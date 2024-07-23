import logging
import os
import json
import jinja2
from typing import Optional
from markdown_it import MarkdownIt
from pydantic import BaseModel
from ..ai.engine import AiEngine, get_ai_engine

CONVERSATION_DIR = "plct_server/eval/conversations"
RESULT_DIR = "plct_server/eval/results"
COMPARATION_TEMPLATE = "plct_server/eval/templates/comparison_template.html"

logger = logging.getLogger(__name__)

class Conversation(BaseModel):
    history: list[tuple[str, str]]
    query: str
    response: str
    benchmark_response: str
    course_key: str
    activity_key: str
    feedback: Optional[int] = None
    ai_assessment: Optional[int] = None

    def transform_markdown(self):
        md = MarkdownIt()

        def convert_to_html(text):
            return md.render(text)

        self.history = [(convert_to_html(item[0]), convert_to_html(item[1])) for item in self.history]
        self.query = convert_to_html(self.query)
        self.response = convert_to_html(self.response)
        self.benchmark_response = convert_to_html(self.benchmark_response)

async def run_test_case(ai_engine: AiEngine, test_case: Conversation):
    answer_generator = await ai_engine.generate_answer(
        history=test_case.history,
        query=test_case.query,
        course_key=test_case.course_key,
        activity_key=test_case.activity_key
    )

    answer = ""
    async for chunk in answer_generator:
        answer += chunk

    return answer

def load_conversations(directory: str) -> dict[str, list[Conversation]]:
    conversations_dict = {}
    for test_case_file in os.listdir(directory):
        if not test_case_file.endswith(".json"):
            continue
        with open(os.path.join(directory, test_case_file), encoding="utf-8") as f:
            test_case_file_name, _ = os.path.splitext(test_case_file)
            conversations_json = json.load(f)
            conversations = [Conversation.model_validate(conversation) for conversation in conversations_json]
            conversations_dict[test_case_file_name] = conversations
    return conversations_dict

async def process_conversations(ai_engine: AiEngine, output_dir: str, set_benchmark: bool) -> None:
    conversations_dict = load_conversations(CONVERSATION_DIR)
    for test_case_file_name, conversations in conversations_dict.items():
        logger.info(f"Getting answers for {os.path.basename(output_dir)} {test_case_file_name}")
        for conversation in conversations:
            response = await run_test_case(ai_engine, conversation)
            if set_benchmark:
                conversation.benchmark_response = response
            else:
                conversation.response = response

        result_file = os.path.join(output_dir, f"results_{test_case_file_name}.json")
        with open(result_file, "w") as f:
            json.dump([conversation.model_dump() for conversation in conversations], f, indent=4)

async def batch_prompt_conversations(batch_name: str, set_benchmark: bool) -> None:
    ai_engine = get_ai_engine()
    output_dir = os.path.join(RESULT_DIR, batch_name)
    os.makedirs(output_dir, exist_ok=True)
    await process_conversations(ai_engine, output_dir, set_benchmark)

async def generate_html_report(batch_name: str, use_ai_to_compare: bool) -> None:
    conversation_path = os.path.join(RESULT_DIR, batch_name)

    conversations_dict = load_conversations(conversation_path)
    conversations = [conversation for conv_list in conversations_dict.values() for conversation in conv_list]

    for conversation in conversations:
        conversation.transform_markdown()
        if use_ai_to_compare:
            logger.info(f"Getting AI assessment of similarity")
            conversation.ai_assessment = await get_ai_assessment(conversation.response, conversation.benchmark_response)

    with open(COMPARATION_TEMPLATE, 'r', encoding='utf-8') as file:
        template_content = file.read()
    
    template = jinja2.Template(template_content)
    
    html_content = template.render(conversations=conversations)

    report_path = os.path.join(RESULT_DIR, batch_name, 'report.html')
    with open(report_path, 'w', encoding='utf-8') as file:
        file.write(html_content)


async def get_ai_assessment(response: str, benchmark_response: str) -> int:
    ai_engine = get_ai_engine()
    return await ai_engine.compare_strings(response, benchmark_response)