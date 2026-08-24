"""The knowledge layer: mirrored sources, one Chroma collection each.

Startup mirrors every configured source to local disk and loads its vectors into its own
collection. After that nothing in the request path makes an HTTP request for content.

    store = knowledge.init(sources=resolve_sources(conf), cache_dir=conf.knowledge_cache_dir)
    hits = store.source("courses").search(embedding, k=10, where={"course_key": ck})
    text = hits[0].text
"""

from __future__ import annotations

import logging
from pathlib import Path

from .cache import mirror_root
from .config import (COURSES_KEY, DEFAULT_CACHE_DIR, SourceSpec, SourceType,
                     resolve_sources)
from .store import (BundleSource, CourseSource, Hit, KnowledgeSource, KnowledgeStore,
                    source_for)
from .sync import DEFAULT_WORKERS, sync, verify

logger = logging.getLogger(__name__)

__all__ = ["COURSES_KEY", "DEFAULT_CACHE_DIR", "SourceSpec", "SourceType", "Hit",
           "KnowledgeSource", "KnowledgeStore", "CourseSource", "BundleSource",
           "resolve_sources", "source_for", "sync", "verify",
           "build_store", "init", "get_store"]

_store: KnowledgeStore | None = None


def build_store(sources: list[SourceSpec], cache_dir: str | Path = DEFAULT_CACHE_DIR, *,
                do_sync: bool = True, workers: int = DEFAULT_WORKERS) -> KnowledgeStore:
    """Mirror each source, then load it into its own collection."""
    store = KnowledgeStore()
    for spec in sources:
        root = sync(spec, cache_dir, workers=workers) if do_sync \
            else mirror_root(spec, cache_dir)
        store.add(source_for(spec, root))
    return store


def init(*, sources: list[SourceSpec], cache_dir: str | Path = DEFAULT_CACHE_DIR,
         do_sync: bool = True) -> KnowledgeStore:
    global _store
    if _store is not None:
        raise ValueError(f"{__name__} already initialized")
    _store = build_store(sources, cache_dir, do_sync=do_sync)
    logger.info("knowledge sources loaded:\n%s", _store.describe())
    return _store


def get_store() -> KnowledgeStore:
    if _store is None:
        raise ValueError(f"{__name__} not initialized, call {__name__}.init first")
    return _store
