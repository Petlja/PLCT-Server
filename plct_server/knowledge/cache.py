"""The local mirror: one directory per source, keyed by the URL it came from.

Everything the request path reads comes from here, not from the network. A source whose
url is already a local path is used in place -- it is its own mirror.
"""

from __future__ import annotations

import json
from hashlib import sha1
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import url2pathname

from .config import SourceSpec

MANIFEST = ".mirror.json"


def is_remote(url: str) -> bool:
    return urlparse(url).scheme in ("http", "https")


def local_path(url: str) -> Path:
    """A non-remote url as a filesystem path. Accepts plain paths and file:// URLs."""
    parsed = urlparse(url)
    if parsed.scheme == "file":
        return Path(url2pathname(parsed.path))
    return Path(url)


def mirror_root(spec: SourceSpec, cache_dir: str | Path) -> Path:
    """Where this source lives on disk.

    The url hash keeps two sources -- or two builds of one source -- from sharing a
    directory, and the key prefix keeps the directory readable.
    """
    if not is_remote(spec.url):
        return local_path(spec.url)
    digest = sha1(spec.url.rstrip("/").encode()).hexdigest()[:12]
    return Path(cache_dir) / f"{spec.key}-{digest}"


def write_atomic(path: Path, data: bytes) -> None:
    """Write via a .part file, so an interrupted sync never leaves a half file behind."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".part")
    tmp.write_bytes(data)
    tmp.replace(path)


def read_manifest(root: Path) -> dict | None:
    """What the last sync of this mirror produced, or None if it was never synced."""
    path = Path(root) / MANIFEST
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def write_manifest(root: Path, data: dict) -> None:
    write_atomic(Path(root) / MANIFEST,
                 json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8"))
