from abc import ABC, abstractmethod
import json
import os
import posixpath
import re
from urllib.parse import urljoin, urlparse

import aiofiles
from fastapi import Request, Response
from fastapi.responses import FileResponse
import httpx
import yaml

class FileSet(ABC):
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
            if ':' in p: # Windows path
                p = p[1:]
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
        
    async def read_str_async(self, path: str) -> str | None:
        lpath = self.local_path(path)
        if not os.path.isfile(lpath):
            return None
        async with aiofiles.open(lpath, mode='r', encoding="utf8") as f:
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

    _client: httpx.Client

    def __init__(self, base_url: str):
        if base_url.endswith('/'):
            self.base_url = base_url[:-1]
        else:
            self.base_url = base_url
        self._client = httpx.Client()


    def full_url(self, path: str) -> str:
        if path is None or path == "":
            return self.base_url
        return f"{self.base_url}/{clean_path(path)}"

    def read_str(self, path: str) -> str:
        url = self.full_url(path)
        response = self._client.get(url)
        if response.status_code == 404:
            return None
        return response.text

    async def read_str_async(self, path: str) -> str:
        url = self.full_url(path)
        async with httpx.AsyncClient() as client:
            response = await client.get(url)
            if response.status_code == 404:
                return None
            response.raise_for_status()
            return response.text

    async def fastapi_response(self, path: str, request: Request = None) -> Response:
        forward_url = self.full_url(path)

        # List of headers to forward
        headers_whitelist = {"accept", "accept-language", "accept-encoding", "cache-control",
                                "if-modified-since", "if-none-match", "range"}

        # Create a dictionary of headers to forward based on the whitelist
        fw_headers = {key: value for key, value in request.headers.items() 
                      if key.lower() in headers_whitelist}

        async with httpx.AsyncClient() as client:
            # Forward the request and stream the response
            response = await client.request(
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
        
