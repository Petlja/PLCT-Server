"""The page the teacher is on, as the system message carries it."""

import logging
from dataclasses import dataclass
from typing import Awaitable, Callable

from ...knowledge.course_db import CourseDB

logger = logging.getLogger(__name__)


CONTEXT_MAX_CHUNKS = 3


@dataclass
class PageContext:
    """The current page as the system message should carry it."""

    text: str
    whole: bool
    used: int          # chunks included
    total: int         # chunks the page has


async def current_page(*, course_key: str, activity_key: str, query: str, source,
                       db: CourseDB, embed: Callable[[str], Awaitable[list[float]]],
                       evidence, max_chunks: int = CONTEXT_MAX_CHUNKS
                       ) -> PageContext | None:
    """The page the teacher is on, as text: whole if it is short, searched if it is not."""
    all_ids = list(db.get_by_activity(course_key, activity_key))
    if not all_ids:
        return None

    whole = len(all_ids) <= max_chunks
    if whole:
        ids = all_ids
    else:
        embedding = await embed(query)
        ids = [hit.id for hit in source.search(embedding, k=max_chunks, where={"$and": [
            {"course_key": course_key}, {"activity_key": activity_key}]})]
        logger.info("current page has %d chunks -- searching it with the teacher's "
                    "question, %d back", len(all_ids), len(ids))

    runs = db.runs(ids)
    if not runs:
        return None

    used = sum(len(run.order) for run in runs)
    text = "\n\n[...]\n\n".join(run.text for run in runs) if len(runs) > 1 \
        else runs[0].text
    lesson_title, activity_title = db.titles(course_key, activity_key)
    labels = {"lesson": lesson_title, "activity": activity_title}
    record = {"course_key": course_key, "activity_key": activity_key,
              "lesson_title": lesson_title, "activity_title": activity_title,
              "chunks": f"{used}/{len(all_ids)}",
              "whole": str(whole), "via": "context"}
    for n, run in enumerate(runs):
        # The provenance record describes the page, so it is written once, not per run.
        evidence.deliver_run(run.order, run.text, record=record if n == 0 else None,
                             **labels)
    return PageContext(text=text, whole=whole, used=used, total=len(all_ids))
