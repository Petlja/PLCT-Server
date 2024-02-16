
import logging
from rich.logging import RichHandler

logger = logging.getLogger(__name__)

# If the logger has no handlers, add a default logger configuration
if not logger.hasHandlers():
    handler = RichHandler()
    formatter = logging.Formatter('%(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)