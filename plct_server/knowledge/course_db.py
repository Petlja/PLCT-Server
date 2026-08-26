"""Lesson structure: the other thing the AI-context dataset does not record.

A course's activities are grouped into lessons out of the chunk metadata and the TOC
text, and chunk text is fetched and de-overlapped for the tools. `store.py` owns the
mirror and the collection, `chunk_order.py` owns document order.
"""

import logging
import re
from dataclasses import dataclass

from .chunk_order import Reconstruction, fuse, reconstruct

logger = logging.getLogger("course-db")


class CourseDB:
    """The course source, read as a course rather than as a vector index.

    Everything here is a disk read or a metadata-only Chroma get; text lives in the
    mirror, keyed by content hash, so the source's cache can never be stale.
    """

    def __init__(self, source):
        self.source = source
        self._lessons: dict[str, list["Lesson"]] = {}
        self._titles: dict[str, dict[str, tuple[str, str]]] = {}

    def get_by_activity(self, course_key: str, activity_key: str) -> dict[str, dict]:
        """chunk_hash -> metadata for one activity. No vectors, no text, no network.

        `course_key` is not optional: 121 activity keys are shared between courses, and
        dropping it would mix two courses' copies of the same page.
        """
        return self.source.get({"$and": [{"course_key": course_key},
                                         {"activity_key": activity_key}]})

    def runs(self, chunk_ids: list[str], *, whole: bool = False) -> list[Reconstruction]:
        """The named chunks as text, in document order, each overlap carried once.

        `whole` is for a full page, which reconstructs all-or-nothing; without it the
        chunks are an arbitrary handful and only the runs that chain are joined. Chunks
        the mirror does not have are dropped, so this can come back empty.
        """
        chunks: dict[str, str] = {}
        for chunk_id in chunk_ids:
            text = self.source.text(chunk_id)
            if text is None:
                logger.warning("chunk text missing from the mirror: %s", chunk_id)
            else:
                chunks[chunk_id] = text
        if not chunks:
            return []
        return [reconstruct(chunks)] if whole else fuse(chunks)

    # ------------------------------------------------------------------- structure

    def course_title(self, course_key: str) -> str:
        summary = self.source.course_dict.get(course_key)
        return summary.title if summary else course_key

    def lessons(self, course_key: str) -> "list[Lesson]":
        """Every lesson of a course, in document order, each with its activities in order.

        Cached: one Chroma get and one TOC read per course.
        """
        if course_key not in self._lessons:
            self._lessons[course_key] = _build_lessons(self, course_key)
        return self._lessons[course_key]

    def locate(self, course_key: str,
               activity_key: str) -> "tuple[Lesson | None, LessonActivity | None]":
        """The lesson and the activity one activity_key names, or (None, None)."""
        for lesson in self.lessons(course_key):
            for activity in lesson.activities:
                if activity.activity_key == activity_key:
                    return lesson, activity
        return None, None

    def titles(self, course_key: str, activity_key: str) -> tuple[str, str]:
        """(lesson title, activity title). Not from the chunk metadata, which has both wrong."""
        if course_key not in self._titles:
            self._titles[course_key] = {
                activity.activity_key: (lesson.title, activity.title)
                for lesson in self.lessons(course_key)
                for activity in lesson.activities}
        return self._titles[course_key].get(activity_key, ("", ""))


# --------------------------------------------------------------------------- lessons


@dataclass(frozen=True)
class LessonActivity:
    activity_key: str
    title: str                    # from summary.json, which is the reliable source


@dataclass(frozen=True)
class Lesson:
    title: str                    # the TOC spelling where there is one
    activities: list[LessonActivity]


def _norm(title: str | None) -> str:
    return re.sub(r"\s+", "", title or "")


def _toc_sections(db: CourseDB, course_key: str,
                  run_titles: list[str | None]) -> dict[str, str]:
    """norm(title) -> the TOC's spelling, for sections that actually hold activities.

    Four courses carry a landing-page section holding nothing fetchable; it is dropped.
    """
    wanted = {_norm(title) for title in run_titles}
    sections: dict[str, str] = {}
    for line in (db.source.toc_text(course_key) or "").splitlines():
        if line.startswith("Section:"):
            title = line.split("Section:", 1)[1].strip()
            if _norm(title) in wanted:
                sections[_norm(title)] = title
    return sections


def _build_lessons(db: CourseDB, course_key: str) -> list[Lesson]:
    """Group the course's activities into lesson runs. Cached by `CourseDB.lessons`.

    Order comes from `CourseSummary.activities`, grouping from the chunk metadata's
    `lesson_title`.
    """
    summary = db.source.course_dict.get(course_key)
    if summary is None:
        return []

    lesson_of: dict[str, str] = {}
    for meta in db.source.get({"course_key": course_key}).values():
        lesson_of.setdefault(meta["activity_key"], meta["lesson_title"])

    runs: list[tuple[str | None, list[str]]] = []
    for activity_key in summary.activities:
        title = lesson_of.get(activity_key)
        if not runs or runs[-1][0] != title:
            runs.append((title, []))
        runs[-1][1].append(activity_key)

    display = _toc_sections(db, course_key, [title for title, _ in runs])
    lessons: list[Lesson] = []
    for title, activity_keys in runs:
        activities = []
        for activity_key in activity_keys:
            entry = summary.activities.get(activity_key)
            activities.append(LessonActivity(
                activity_key=activity_key,
                title=(entry.title if entry else None) or activity_key))
        lessons.append(Lesson(
            title=display.get(_norm(title), title or "(no lesson title)"),
            activities=activities))

    return lessons
