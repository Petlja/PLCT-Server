import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from ...knowledge.chunk_order import chunks_to_tokens
from ...knowledge.course_db import CourseDB
from . import questions as questions_arg

logger = logging.getLogger(__name__)

PLATFORM_COURSE_KEY = "petlja-docs"

_LANGUAGE_TAIL = questions_arg.SHARED_TAIL + " Ask in the language the material is written in."

COURSE_DESCRIPTION = (
    "Ask one or more questions about the subject matter this course teaches and receive the "
    "passages of course material that answer them best -- lesson text, worked examples, "
    "exercises and tests, in the words the students read. Ask for the subject itself, in "
    "the terms the material uses to teach it: \"how does binary search narrow the "
    "interval it looks in?\", never \"is there a lesson about binary search in this "
    "course?\". The second kind has no passage that answers it, and the nearest unrelated "
    "pages come back in its place. " + _LANGUAGE_TAIL
)

# Offered only when the page did not fit the prompt whole -- `engine._build_tools`. On the
# 95% of pages that did fit, a tool over the current page could answer nothing the model has
# not already read, and an unusable tool in the list is a routing mistake waiting to happen.
CURRENT_PAGE_DESCRIPTION = (
    "Ask one or more questions about the page the teacher is looking at and receive the "
    "sections of it that answer them best. This page was too long to reproduce whole in "
    "your context: what you were given is a sample of it, marked as such, and this is how "
    "you reach the rest. Use it when the teacher asks about something on this page that "
    "the sample does not cover -- a further exercise, a later section, whatever the "
    "`[...]` stands in for. " + _LANGUAGE_TAIL
)

# Three sections, as many as the prompt itself gave: ~9,200 tokens at 3,072 a chunk, which
# is as much of one page as the budget can spare with the rest of the course still to fund.
CURRENT_PAGE_K = 3

# Must not mention assessment or grading -- that pulls such questions off the literature.
PLATFORM_DESCRIPTION = (
    "Ask one or more questions about operating the petlja.org website and receive the "
    "passages of its user documentation that answer them best. It covers working the "
    "software: making an account and signing in, including through Microsoft, Google or "
    "an account for a child under 15, getting a teacher account; groups -- "
    "creating one, anonymous accounts, a new student, a student who changed class, a "
    "change of teacher; net.kabinet -- setting a kabinet up, its users, homework, "
    "following what students do there, writing to them; putting together a test of short "
    "questions and handing it out; setting up a small competition -- its problems, its "
    "points, its entrants; the kinds of material on Petlja (problem collections, "
    "handbooks, collections of short questions); and the competition environment as a "
    "contestant sees it -- getting in, reading a problem, sending a solution, input and "
    "output, testing the code, questions and announcements. Use it only for how to work "
    "the site. " + _LANGUAGE_TAIL
)


@dataclass(frozen=True)
class Limits:
    """How much one call may pull back. Calibrated over the corpus -- doc/ai_flow.md section 6."""

    k: int = 6                          # hits per question, course-wide
    max_activities: int = 5             # activities delivered per call, closest first
    max_distance: float = 0.45
    whole_page_max_tokens: int = chunks_to_tokens(8)


class CourseSearchTool:
    """`search_course` / `search_platform_docs` over one course of the course layer."""

    def __init__(self, *, name: str, description: str, course_key: str, source,
                 db: CourseDB, embed: Callable[[str], Awaitable[list[float]]],
                 evidence, exclude_activity: str = "", only_activity: str = "",
                 limits: "Limits | None" = None):
        self.name = name
        self.course_key = course_key
        self.source = source
        self.db = db
        self.embed = embed
        self.evidence = evidence
        self.limits = limits or Limits()
        self.definition = questions_arg.definition(name, description)
        # A tool searches the course minus one page, or that one page alone -- never both,
        # and the two are separate tools. `search_course` excludes the page the teacher is
        # on unconditionally: it is in the system message, booked chunk by chunk in the
        # ledger, so a hit on it comes back as already-provided after spending a hit of `k`
        # and a slot of `max_activities` a further lesson would have used. Since the
        # teacher's question is usually about the page they are standing on, its chunks
        # rank near the top by construction and can take several of the six. Filtered in
        # Chroma rather than after the fact, so `k` is `k` other lessons.
        self._where: dict = {"course_key": course_key}
        if only_activity:
            self._where = {"$and": [self._where, {"activity_key": only_activity}]}
        elif exclude_activity:
            self._where = {"$and": [self._where,
                                    {"activity_key": {"$ne": exclude_activity}}]}

        # `None` where distance may not refuse a hit. Searching one named page is a request
        # for that page: the model asked because the sample it was given fell short, and
        # material is relevant there by where the teacher is standing rather than by
        # distance. Every other search is held to the cutoff.
        self._max_distance: float | None = (
            None if only_activity else self.limits.max_distance)

    # ------------------------------------------------------------------ labels

    def _chunk_ids(self, activity_key: str) -> list[str]:
        """Every chunk of one activity, hit or not. One Chroma get, no text, no network."""
        return list(self.db.get_by_activity(self.course_key, activity_key))

    def _log(self, question: str, hits: list) -> None:
        """One question's course-wide hits, `far` marking the ones the cutoff drops.

        The refused distances stay in the log, because `max_distance` is calibrated off
        them: a threshold whose rejections are invisible cannot be moved with any evidence.
        The nearest is repeated as `best=` so that reading where a question landed over a
        run of them is a grep rather than a reading of every line.
        """
        far = self._max_distance
        logger.info("%s: %r -> best=%s %s", self.name, question,
                    f"{hits[0].distance:.3f}" if hits else "-",
                    ", ".join(
                        f"{hit.id[:8]}={hit.distance:.3f}"
                        f"{' far' if far is not None and hit.distance > far else ''}"
                        for hit in hits) or "none")

    # ------------------------------------------------------------------ running

    async def run(self, arguments: Any) -> dict[str, Any]:
        questions = questions_arg.parse(arguments)
        if isinstance(questions, dict):
            return questions

        hit_ids: dict[str, list[str]] = {}       # activity -> the chunk ids that matched
        best: dict[str, float] = {}              # activity -> its closest hit
        unanswered: list[str] = []               # questions whose every hit was too far

        for question in questions:
            embedding = await self.embed(question)
            hits = self.source.search(embedding, k=self.limits.k, where=self._where)
            self._log(question, hits)
            near = hits if self._max_distance is None else [
                h for h in hits if h.distance <= self._max_distance]

            if not near:
                unanswered.append(question)
                continue

            for hit in near:
                activity_key = hit.metadata.get("activity_key", "")
                best[activity_key] = min(best.get(activity_key, hit.distance), hit.distance)
                ids = hit_ids.setdefault(activity_key, [])
                if hit.id not in ids:
                    ids.append(hit.id)

        # Empty here means every question was too far, so they are all named.
        if not hit_ids:
            return {"passages": [],
                    "note": questions_arg.too_far("this material", unanswered)}


        found = sorted(hit_ids, key=lambda key: best[key])
        dropped = len(found) - self.limits.max_activities

        passages: list[dict[str, Any]] = []
        known = 0
        for activity_key in found[:self.limits.max_activities]:
            page = self._deliver_activity(activity_key, hit_ids[activity_key])
            # None and [] are different facts: material the model has, and material the
            # budget refused. Only the first belongs in the `known` count.
            if page is None:
                known += 1
            else:
                passages += page

        # What could not be sent is said once, in prose, rather than as passages with no
        # text in them: one shape reaches the model, and it is always material.
        notes: list[str] = []
        if unanswered:
            notes.append(questions_arg.too_far("this material", unanswered))
        if known:
            notes.append(f"{known} matching place(s) were already given to you earlier in "
                         "this answer, and are not repeated here.")
        if dropped > 0:
            notes.append(f"{dropped} further place(s) in the material also matched, less "
                         "closely, and were not included. Ask a narrower question if you "
                         "need them.")
        if self.evidence.exhausted:
            notes.append("The evidence budget for this answer is spent. Answer from what "
                         "you have rather than searching again.")

        result: dict[str, Any] = {"passages": passages}
        if notes:
            result["note"] = " ".join(notes)
        return result

    def _deliver_activity(self, activity_key: str,
                          hits: list[str]) -> "list[dict[str, Any]] | None":
        """One matched activity: the whole page where that is sensible, an excerpt where not.

        None when the model already has this material; empty when the budget refused it.
        `run` says which in its note.
        """
        all_ids = self._chunk_ids(activity_key)
        cost = chunks_to_tokens(len(all_ids))
        whole = 0 < cost <= min(self.limits.whole_page_max_tokens, self.evidence.remaining)
        if not whole and cost <= self.limits.whole_page_max_tokens:
            logger.info("%s: %s is short enough to widen but ~%d tok will not fit in the "
                        "%d left -- sending the %d matched chunk(s)", self.name,
                        activity_key, cost, self.evidence.remaining, len(hits))

        # Widening is all-or-nothing -- the de-overlapped page is one passage and one charge
        # -- so a page holding any chunk the model already has cannot be sent whole. It falls
        # back to the matched chunks it is missing rather than dropping out: a page the
        # prompt could only sample three sections of still holds material never seen, and
        # reporting all of it as already provided is both a lost answer and a false one.
        if whole and not any(self.evidence.holds(i) for i in all_ids):
            ids = all_ids
        else:
            whole = False
            ids = [i for i in hits if not self.evidence.holds(i)]
        if not ids:
            return None

        lesson_title, activity_title = self.db.titles(self.course_key, activity_key)
        labels = {"lesson": lesson_title, "activity": activity_title}
        return [p for p in self._passages(activity_key, ids, len(all_ids), labels,
                                          whole=whole) if self.evidence.sent(p)]

    def _passages(self, activity_key: str, ids: list[str], page_chunks: int,
                  labels: dict[str, str], *, whole: bool) -> list[dict[str, Any]]:
        """Turn chunks into passages: one for contiguous text, one each for scattered."""
        runs = self.db.runs(ids, whole=whole)
        if not runs:
            return []

        if whole and not runs[0].ordered:
            logger.info("%s: %s not reconstructable (%s)", self.name, activity_key,
                        "; ".join(runs[0].problems))
        ordered = runs[0].ordered if whole else len(runs) == 1

        return [
            self.evidence.deliver_run(
                ids_in_group, text,
                **labels,
                **({} if whole else {"excerpt": True}),
                record={"course_key": self.course_key, "activity_key": activity_key,
                        "lesson_title": labels["lesson"],
                        "activity_title": labels["activity"],
                        "chunks": f"{len(ids_in_group)}/{page_chunks}",
                        "whole": str(whole), "ordered": str(ordered)})
            for ids_in_group, text in ((run.order, run.text) for run in runs)]


def course_search_tool(**kwargs) -> CourseSearchTool:
    return CourseSearchTool(name="search_course", description=COURSE_DESCRIPTION, **kwargs)


def current_page_search_tool(**kwargs) -> CourseSearchTool:
    """`search_current_page`, over the one page the prompt could not carry whole."""
    kwargs.setdefault("limits", Limits(k=CURRENT_PAGE_K))
    return CourseSearchTool(name="search_current_page",
                            description=CURRENT_PAGE_DESCRIPTION, **kwargs)


def platform_search_tool(**kwargs) -> CourseSearchTool:
    return CourseSearchTool(name="search_platform_docs", description=PLATFORM_DESCRIPTION,
                            course_key=PLATFORM_COURSE_KEY, **kwargs)
