import uvicorn
import click

from .main import app
from .content import set_cli_folders

@click.command()
@click.argument("folders", nargs=-1, type=click.Path(exists=True, file_okay=False, dir_okay=True))
@click.option("-h", "--host", default="127.0.0.1", help="Host to bind to")
@click.option("-p", "--port", default=8000, help="Port to bind to")
def serve(folders: tuple[str], host: str, port: int) -> None:
    """Start the HTTP server for PLCT course(s).
    
    FOLDERS: The folders of PLCT projects to serve. If not provided, the current directory is used."""

    print(f"folders: {folders}, host: {host}, port: {port}")
    
    set_cli_folders(folders)

    uvicorn.run(app, host=host, port=port) 

# This is the entry point for the server (see pyproject.toml)
def main() -> None:
    serve()

