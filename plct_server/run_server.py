import uvicorn
import click
from logging import getLogger
import logging
from .main import app
from . import content

logger = getLogger(__name__)

@click.command()
@click.argument("folders", nargs=-1, type=click.Path(exists=True, file_okay=False, dir_okay=True))
@click.option("-h", "--host", default="127.0.0.1", help="Host to bind to")
@click.option("-p", "--port", default=8000, help="Port to bind to")
@click.option("-v", "--verbose", is_flag=True, help="Enable verbose logging")
def serve(folders: tuple[str], host: str, port: int, verbose:bool) -> None:
    """Start the HTTP server for PLCT course(s).
    
    FOLDERS: The folders of PLCT projects to serve. If not provided, the current directory is used."""

    logger.info(f"folders: {folders}, host: {host}, port: {port}")
    
    content.configure(course_dirs = folders, verbose = verbose)

    uvicorn.run(app, host=host, port=port) 

# This is the entry point for the server (see pyproject.toml)
def main() -> None:
    serve()

