import logging
import uvicorn
import click
import asyncio
from logging import getLogger
from fastapi import FastAPI
from uuid import uuid4
from .eval.batch_review import batch_prompt_conversations, generate_html_report, CONVERSATION_DIR
from .endpoints import get_ui_router
from .content import server
from .knowledge.config import COURSES_KEY, SourceSpec

logger = getLogger(__name__)


def course_sources(ai_context: str | None) -> list[SourceSpec] | None:
    """The --ai-context option: serve exactly that folder as the course source.

    It predates `knowledge_sources` and stays as the one-dataset shorthand, so the
    translation lives here rather than in the configuration layer.
    """
    if not ai_context:
        return None
    return [SourceSpec(key=COURSES_KEY, type="plct-ai-ctx", url=ai_context)]

@click.command()
@click.argument("folders", nargs=-1, type=click.Path(exists=True, file_okay=False, dir_okay=True))
@click.option("-c", "--config", help="Configuration file")
@click.option("-h", "--host", default="127.0.0.1", help="Host to bind to")
@click.option("-p", "--port", default=9000, help="Port to bind to")
@click.option("-v", "--verbose", is_flag=True, help="Enable verbose logging")
@click.option("-a", "--ai-context", help="Folder with AI context; serves it as the sole 'courses' source")
@click.option("-e", "--azure-ai-endpoint", help="Azure AI endpoint. For model specific values use modelname=endpoint syntax")
def serve(folders: tuple[str], config : str, host: str, port: int, verbose:bool, ai_context:str, azure_ai_endpoint: str) -> None:
    """Start the HTTP server for PLCT course(s).
    
    FOLDERS: The folders of PLCT projects to serve. If not provided, the current directory is used."""
    if(verbose):
        logging.getLogger().setLevel(logging.DEBUG)

    logger.debug(f"CLI optoins: folders: {folders}, host: {host}, port: {port}, verbose: {verbose}, ai_context: {ai_context}, azure_ai_endpoint: {azure_ai_endpoint}")


    server.configure(
        course_urls=folders, config_file=config, verbose=verbose,
        knowledge_sources=course_sources(ai_context),
        azure_default_ai_endpoint=azure_ai_endpoint)
    
    app = FastAPI()
    app.include_router(get_ui_router())

    uvicorn.run(app, host=host, port=port) 

@click.command()
@click.option("-a", "--ai-context", help="Folder with AI context; serves it as the sole 'courses' source")
@click.option("-n", "--batch-name", default=uuid4(), help="Batch name")
@click.option("-b", "--set-benchmark", is_flag=True, help="Set responses as the benchmark responses")
@click.option("-v", "--verbose", is_flag=True, help="Enable verbose logging")
@click.option("-d", "--conversation-dir", type = click.Path(exists=True, file_okay=False, dir_okay=True),default=CONVERSATION_DIR, help="Directory holding pre-arranged conversations")
@click.option("-m", "--model", default ="gpt-4o" ,help="default model to use")
@click.option("-nr", "--no-report", is_flag=True, help="Do not generate HTML report", default=False)
def batch_review(ai_context:str, batch_name:str, set_benchmark: bool, verbose, conversation_dir: str, model : str, no_report: bool) -> None:
    import platform
    if platform.system()=='Windows':
       asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    asyncio.run(batch_review_async(ai_context, batch_name, set_benchmark, verbose, conversation_dir, model, no_report))
    
async def batch_review_async(ai_context:str, batch_name:str, set_benchmark: bool, verbose, conversation_dir: str, model : str, no_report: bool) -> None:
    server.configure(
        knowledge_sources=course_sources(ai_context),
        verbose=verbose)
      
    logger.info("Starting batch review of conversations")
    await batch_prompt_conversations(conversation_dir = conversation_dir, batch_name=batch_name, set_benchmark=set_benchmark, model = model)

    if not (set_benchmark or no_report):
        logger.info("Generating HTML report")
        await generate_html_report(batch_name)

# This is the entry point for the server (see pyproject.toml)
def cli() -> None:
    serve()

def batch_review_cli() -> None:
    batch_review()
