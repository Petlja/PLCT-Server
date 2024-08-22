import logging
from pydantic import BaseModel
from tiktoken import Encoding


logger = logging.getLogger(__name__)

class QueryError(Exception):
    pass

class QueryContext(BaseModel):
    chunk_metadata : list[dict[str,str]] = []
    system_message : str = ""
    token_size : dict[str,int] = {}

    def set_chunk_metadata(self, chunk_metadata: dict[str,str]):
        self.chunk_metadata = chunk_metadata

    def get_all_chunk_activity_keys(self) -> str:
        return [item["activity_key"] for item in self.chunk_metadata]
            
    def add_encoding_length(self, name: str, message: str, encoding: Encoding) -> None:
        if name not in self.token_size:
            self.token_size[name] = 0
        self.token_size[name] += len(encoding.encode(message))
    
    def get_encoding_length(self) -> int:
        return sum(self.token_size.values())
    
    def log_encoding_length(self) -> None:
        for name, size in self.token_size.items():
            logger.debug(f"Encoding length for {name}: {size}")

    def add_system_message_parts(self,parts: list[dict[str, str]], encoding: Encoding) -> None:
        for part in parts:
            self.add_encoding_length(part["name"], part["message"], encoding)
            self.system_message += part["message"]