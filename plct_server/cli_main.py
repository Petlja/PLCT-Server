import uvicorn
import click
from logging import getLogger
from fastapi import FastAPI
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
        course_dirs = folders, verbose = verbose, 
        ai_context_dir = ai_context)
    app = FastAPI()
    app.include_router(get_ui_router())

    uvicorn.run(app, host=host, port=port) 

# This is the entry point for the server (see pyproject.toml)
def cli() -> None:
    serve()

