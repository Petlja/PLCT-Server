
import logging
from rich.logging import RichHandler

logger = logging.getLogger(__name__)

# If the logger has no handlers, add a default logger configuration
if not logger.hasHandlers():
    handler = RichHandler(show_time=False)
    formatter = logging.Formatter(' %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)

def register_extension_command(cli_group):
    from .cli_main import serve
    cli_group.add_command(serve)