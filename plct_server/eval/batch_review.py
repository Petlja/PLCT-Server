import logging
import os
import jinja2

from typing import Optional, Tuple
from markdown_it import MarkdownIt
from pydantic import BaseModel

from ..ai.engine import AiEngine, QueryContext, get_ai_engine
from ..ioutils import read_json, write_json, read_str, write_str

CONVERSATION_DIR = "plct_server/eval/conversations/default"
RESULT_DIR = "plct_server/eval/results"
COMPARISON_TEMPLATE = "plct_server/eval/templates/comparison_template.html"

logger = logging.getLogger(__name__)

class Conversation(BaseModel):
    history: list[tuple[str, str]]
    condensed_history : Optional[str] = ""
    query: str
    response: str
    benchmark_response: str
    course_key: str
    activity_key: str
    feedback: Optional[int] = None
    ai_assessment: Optional[int] = None
    query_context: Optional[QueryContext]= None
    model : Optional[str] = None

    def transform_markdown(self):
        md = MarkdownIt()

        def convert_to_html(text):
            return md.render(text)

        self.history = [(convert_to_html(item[0]), convert_to_html(item[1])) for item in self.history]
        self.query = convert_to_html(self.query)
        self.response = convert_to_html(self.response)
        self.benchmark_response = convert_to_html(self.benchmark_response)
        self.query_context.system_message = convert_to_html(self.query_context.system_message)

async def run_test_case(ai_engine: AiEngine, test_case: Conversation, model : str) -> Tuple[str, QueryContext]:
    answer_generator, context = await ai_engine.generate_answer(
        history=test_case.history,
        query=test_case.query,
        course_key=test_case.course_key,
        activity_key=test_case.activity_key,
        condensed_history = test_case.condensed_history,
        model_name= test_case.model if test_case.model else model
    )
    
    answer = ""
    async for chunk in answer_generator:
        answer += chunk

    return answer, context

def load_conversations(directory: str) -> dict[str, list[Conversation]]:
    conversations_dict = {}
    for file in os.listdir(directory):
        if not file.endswith(".json"):
            continue

        file_path = os.path.join(directory, file)
        file_name, _ = os.path.splitext(file)
        conversations_json = read_json(file_path)
        conversations = [Conversation.model_validate(conversation) for conversation in conversations_json]
        conversations_dict[file_name] = conversations
          
    return conversations_dict

async def process_conversations(conversation_dir: str, output_dir: str, set_benchmark: bool, model : str) -> None:
    ai_engine = get_ai_engine()
    conversations_dict = load_conversations(conversation_dir)

    logger.info(f"Processing {len(conversations_dict)} conversation files")
    for file_name, conversations in conversations_dict.items():
        for conversation in conversations:
            response, context = await run_test_case(ai_engine, conversation, model)
            if set_benchmark:
                conversation.benchmark_response = response
            else:
                conversation.response = response
                conversation.query_context = context

        result_file_suffix = "" if set_benchmark else "results_"
        result_file = os.path.join(output_dir, f"{result_file_suffix}{file_name}.json")
        write_json(result_file, [conv.model_dump(exclude = {"encoding"}) for conv in conversations])
        logger.info(f"Results written to {result_file}")    

async def batch_prompt_conversations(conversation_dir: str, batch_name: str, set_benchmark: bool, model : str) -> None:
    output_dir = CONVERSATION_DIR if set_benchmark else os.path.join(RESULT_DIR, batch_name)
    os.makedirs(output_dir, exist_ok=True)

    await process_conversations(conversation_dir, output_dir, set_benchmark, model)

async def generate_html_report(batch_name: str, use_ai_to_compare: bool) -> None:
    conversation_path = os.path.join(RESULT_DIR, batch_name)

    conversations_dict = load_conversations(conversation_path)
    conversations = [conversation for conv_list in conversations_dict.values() for conversation in conv_list]

    for conversation in conversations:
        conversation.transform_markdown()
        if use_ai_to_compare:
            conversation.ai_assessment = await get_ai_assessment(
                conversation.response, 
                conversation.benchmark_response
                )

    template_content = read_str(COMPARISON_TEMPLATE)
    template = jinja2.Template(template_content)
    html_content = template.render(conversations=conversations)

    report_path = os.path.join(RESULT_DIR, batch_name, 'report.html')
    write_str(report_path, html_content)
    logger.info(f"Report generated at {report_path}")


async def get_ai_assessment(response: str, benchmark_response: str) -> int:
    ai_engine = get_ai_engine()
    return await ai_engine.compare_strings(response, benchmark_response)