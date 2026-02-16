from abc import ABC, abstractmethod
import json
import logging
import os
import posixpath
import re
from urllib.parse import urljoin, urlparse

import aiofiles
from fastapi import Request, Response
from fastapi.responses import FileResponse
import httpx
import yaml

logger = logging.getLogger(__name__)


class FileSet(ABC):
    """Common abstraction for reading files from different sources (local filesystem, HTTP, etc.).

    Provides a unified interface so that application code can access files regardless of their
    origin without coupling to a specific storage mechanism. Core operations (read as string or bytes)
    are abstract; convenience methods for JSON, YAML, and FastAPI responses are built on top.
    Both synchronous and asynchronous variants are supported.

    Concrete implementations:
        - LocalFileSet: Reads from the local filesystem.
        - HttpFileSet: Reads from a remote HTTP server, proxying requests and responses.
    """
    @abstractmethod
    def read_str(self, path: str) -> str | None:
        pass

    def read_json(self, path: str) -> dict | None:
        str_value = self.read_str(path)
        if str_value is None:
            return None
        return json.loads(str_value)
    
    def read_yaml(self, path: str) -> dict | None:
        str_value = self.read_str(path)
        if str_value is None:
            return None
        return yaml.safe_load(str_value)
    
    @abstractmethod
    def read_bytes(self, path: str) -> bytes | None:
        pass

    @abstractmethod
    async def read_str_async(self, path: str) -> str | None:
        pass

    async def read_json_async(self, path: str) -> dict | None:
        str_value = await self.read_str_async(path)
        if str_value is None:
            return None
        return json.loads(str_value)
    
    async def read_yaml_async(self, path: str) -> dict | None:
        str_value = await self.read_str_async(path)
        if str_value is None:
            return None
        return yaml.safe_load(str_value)
    
    @abstractmethod
    async def read_bytes_async(self, path: str) -> bytes | None:
        pass

    @abstractmethod
    def subdir(self, path: str) -> 'FileSet':
        pass

    @abstractmethod
    def fastapi_response(self, path: str, request: Request) -> Response:
        pass

    @staticmethod
    def from_base_url(base_url: str) -> 'FileSet':
        parsed_url = urlparse(base_url)
        if parsed_url.scheme in ("http", "https"):
            return HttpFileSet(base_url)
        elif parsed_url.scheme == "file":
            p = parsed_url.path
            return LocalFileSet(p)
        elif parsed_url.scheme == "":
            return LocalFileSet(base_url)
        else:
            raise ValueError(f"Unsupported URL scheme: {parsed_url.scheme}")

path_cleaner_regex = re.compile(r'^/|(\.\./?)')

def clean_path(path: str) -> str:
    return path_cleaner_regex.sub('', posixpath.normpath(path))

class LocalFileSet(FileSet):

    base_dir: str

    def __init__(self, base_dir: str):
        logger.debug(f"Creating LocalFileSet from base directory: {base_dir}")
        if base_dir.endswith('/'):
            self.base_dir = base_dir[:-1]
        else:
            self.base_dir = base_dir

    def local_path(self, path: str) -> str:
        return f"{self.base_dir}/{clean_path(path)}"
    
    def read_str(self, path: str) -> str | None:
        lpath = self.local_path(path)
        if not os.path.isfile(lpath):
            return None
        with open(lpath, encoding="utf8") as f:
            return f.read()
        
    def read_bytes(self, path: str) -> bytes | None:
        lpath = self.local_path(path)
        if not os.path.isfile(lpath):
            return None
        with open(lpath, 'rb') as f:
            return f.read()
        
    async def read_str_async(self, path: str) -> str | None:
        lpath = self.local_path(path)
        if not os.path.isfile(lpath):
            return None
        async with aiofiles.open(lpath, mode='r', encoding="utf8") as f:
            return await f.read()
        
    async def read_bytes_async(self, path: str) -> bytes | None:
        lpath = self.local_path(path)
        if not os.path.isfile(lpath):
            return None
        async with aiofiles.open(lpath, mode='rb') as f:
            return await f.read()

    def fastapi_response(self, request: Request, path: str) -> Response:
        lpath = self.local_path(path)
        return FileResponse(lpath)
    
    def subdir(self, path: str) -> 'LocalFileSet':
        return LocalFileSet(self.local_path(path))
    
    def __str__(self) -> str:
        return f"LocalFileSet({self.base_dir})"
    
class HttpFileSet(FileSet):

    base_url: str

    # make single static client/async_client to handle shared connection pools
    client = httpx.Client()
    async_client = httpx.AsyncClient()


    def __init__(self, base_url: str):
        if base_url.endswith('/'):
            self.base_url = base_url[:-1]
        else:
            self.base_url = base_url


    def full_url(self, path: str) -> str:
        if path is None or path == "":
            return self.base_url
        return f"{self.base_url}/{clean_path(path)}"

    def read_str(self, path: str) -> str | None:
        url = self.full_url(path)
        response = HttpFileSet.client.get(url)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.text
    
    def read_bytes(self, path: str) -> bytes | None:
        url = self.full_url(path)
        response = HttpFileSet.client.get(url)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.content

    async def read_str_async(self, path: str) -> str | None:
        url = self.full_url(path)
        response = await HttpFileSet.async_client.get(url)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.text
    
    async def read_bytes_async(self, path: str) -> bytes | None:
        url = self.full_url(path)
        response = await HttpFileSet.async_client.get(url)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.content

    async def fastapi_response(self, path: str, request: Request = None) -> Response:
        forward_url = self.full_url(path)

        # List of headers to forward
        headers_whitelist = {"accept", "accept-language", "accept-encoding", "cache-control",
                                "if-modified-since", "if-none-match", "range"}

        # Create a dictionary of headers to forward based on the whitelist
        fw_headers = {key: value for key, value in request.headers.items() 
                      if key.lower() in headers_whitelist}
        
        fw_headers["connection"] = "keep-alive"

        # Forward the request and stream the response
        response = await HttpFileSet.async_client.request(
            method=request.method,
            url=forward_url,
            headers=fw_headers,
            data=await request.body(),
            stream=True,
        )

        response_headers = dict(response.headers)
        response_headers.pop("connetion", None)

        # TODO: Consider handling the case where the response is a redirect

        # Stream the response back to the client
        return Response(
            content=response.aiter_raw(),
            status_code=response.status_code,
            headers=dict(response_headers),
        )
        
    def subdir(self, path: str) -> 'HttpFileSet':
        return HttpFileSet(self.full_url(path))
    
    def __str__(self) -> str:
        return f"HttpFileSet({self.base_url})"
        
