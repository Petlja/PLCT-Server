from pydantic import BaseModel
from tiktoken import Encoding


class QueryError(Exception):
    pass

class QueryContext(BaseModel):
    model : str = ""  # what answered, after the request's model name or the fallback
    chunk_metadata : list[dict[str,str]] = []
    system_message : str = ""
    token_size : dict[str,int] = {}

    def set_chunk_metadata(self, chunk_metadata: list[dict[str,str]]):
        self.chunk_metadata = chunk_metadata

    def add_encoding_length(self, name: str, message: str, encoding: Encoding) -> None:
        if name not in self.token_size:
            self.token_size[name] = 0
        self.token_size[name] += len(encoding.encode(message))
    
    def add_system_message_parts(self,parts: list[dict[str, str]], encoding: Encoding) -> None:
        for part in parts:
            self.add_encoding_length(part["name"], part["message"], encoding)
            self.system_message += part["message"]