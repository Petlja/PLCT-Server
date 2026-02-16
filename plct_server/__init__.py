
import logging
from rich.logging import RichHandler

logger = logging.getLogger(__name__)

# If the logger has no handlers, add a default logger configuration
if not logger.hasHandlers():
    handler = RichHandler(show_time=False)
    formatter = logging.Formatter(' %(message)s')
    handler.setFormatter(formatter)
    logging.basicConfig(level=logging.INFO, handlers=[handler])
    
# When the PLCT Server package is used as an extension to the plct CLI, 
# this function will be called to register the extension's commands
def register_extension_command(cli_group):
    from .cli_main import serve, batch_review
    cli_group.add_command(serve)
    cli_group.add_command(batch_review)
