"""Which knowledge sources this server serves, and where they come from.

A source is a named body of indexed knowledge with its own vectors: the PLCT-AI-Ctx course
dataset is one, an AI-Knowledge-Tools bundle is another. They stay separate payloads -- two
tables in one database -- so each declares its own embedding model and distance space and
is queried on its own.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, field_validator

COURSES_KEY = "courses"
DEFAULT_CACHE_DIR = ".cache/knowledge"

SourceType = Literal["plct-ai-ctx", "aikt-bundle"]

# The key becomes part of a Chroma collection name, which allows [a-zA-Z0-9._-] and has to
# start and end alphanumeric.
_KEY_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$")


class SourceSpec(BaseModel):
    """One configured source. `url` is an http(s) base or a local path."""

    key: str
    type: SourceType
    url: str
    enabled: bool = True

    @field_validator("key")
    @classmethod
    def _valid_key(cls, value: str) -> str:
        if not _KEY_RE.match(value) or not value[-1].isalnum() or len(value) > 40:
            raise ValueError(
                f"invalid source key {value!r}: use letters, digits, '.', '_' or '-', "
                "start and end with a letter or digit, 40 characters at most")
        return value

    @field_validator("url")
    @classmethod
    def _valid_url(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("source url must not be empty")
        return value.strip()


def resolve_sources(conf) -> list[SourceSpec]:
    """The enabled sources for a ConfigOptions."""
    specs = [s for s in (conf.knowledge_sources or []) if s.enabled]
    seen: set[str] = set()
    for spec in specs:
        if spec.key in seen:
            raise ValueError(f"duplicate knowledge source key: {spec.key}")
        seen.add(spec.key)
    return specs
