import uvicorn
import click
import asyncio
from logging import getLogger
from fastapi import FastAPI
from uuid import uuid4
from .eval.batch_review import batch_prompt_conversations, generate_html_report
from .endpoints import get_ui_router
from .content import server

logger = getLogger(__name__)

@click.command()
@click.argument("folders", nargs=-1, type=click.Path(exists=True, file_okay=False, dir_okay=True))
@click.option("-h", "--host", default="127.0.0.1", help="Host to bind to")
@click.option("-p", "--port", default=8000, help="Port to bind to")
@click.option("-v", "--verbose", is_flag=True, help="Enable verbose logging")
@click.option("-a", "--ai-context", help="Folder with AI context")
def serve(folders: tuple[str], host: str, port: int, verbose:bool, ai_context:str) -> None:
    """Start the HTTP server for PLCT course(s).
    
    FOLDERS: The folders of PLCT projects to serve. If not provided, the current directory is used."""

    logger.info(f"folders: {folders}, host: {host}, port: {port}")
    
    server.configure(
        course_urls = folders, verbose = verbose, 
        ai_ctx_url = ai_context)
    app = FastAPI()
    app.include_router(get_ui_router())

    uvicorn.run(app, host=host, port=port) 

@click.command()
@click.option("-a", "--ai-context", help="Folder with AI context")
@click.option("-n", "--batch-name", default=uuid4(), help="Batch name")
@click.option("-b", "--set-benchmark", is_flag=True, help="Set responses as the benchmark responses")
@click.option("-v", "--verbose", is_flag=True, help="Enable verbose logging")
@click.option("-c", "--compare-with-ai", is_flag=True, help="Compare responses with AI")
def batch_review(ai_context:str, batch_name:str, set_benchmark: bool, verbose, compare_with_ai: bool) -> None:
    
    server.configure(
        ai_ctx_url = ai_context,
        verbose=  verbose)
    
    import platform
    if platform.system()=='Windows':
       asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


    logger.info("Starting batch review of conversations")
    asyncio.run(batch_prompt_conversations(batch_name=batch_name, set_benchmark=set_benchmark))

    logger.info("Generating HTML report")
    if compare_with_ai:
        asyncio.run(generate_html_report(batch_name, compare_with_ai))
    else:
        generate_html_report(batch_name, compare_with_ai)



# This is the entry point for the server (see pyproject.toml)
def cli() -> None:
    serve()

def batch_review_cli() -> None:
    batch_review()
