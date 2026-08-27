"""The tool over one AI-Knowledge-Tools bundle.

AIKT prepares knowledge; it does not describe it. A tool description is prompt engineering
-- calibrated against this model, and against the sibling tools it competes with for the
model's attention -- so it is authored here, beside those siblings, and bound to a bundle by
the `knowledge_unit` its manifest declares. That name travels with the artifact, so renaming
a source key in the server config cannot silently detach a tool from its knowledge.

One bundle, one tool: a tool stands on its own and says what it knows, so the authored
prose is closed by the bundle's own concept names, read off the loaded records. A tool over
several bundles could say what it holds only as a stack of those lists. When a second bundle
arrives it gets its own entry below.
"""

import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from . import questions as questions_arg
from .. import narration

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Limits:
    """How much one call may pull back. Calibrated over the bundle -- doc/ai_flow.md section 6."""

    chunk_k: int = 5                    # chunk hits per question
    concept_k: int = 3                  # ...and concepts, each expanding to its own chunks
    chunks_per_concept: int = 3
    max_chunk_distance: float = 0.50    # deliberately loose; the cap bounds the cost
    max_concept_distance: float = 0.50  # nearer everything by construction -- held
    chunks_per_question: int = 3        # the cap scales with what was asked...
    max_chunks: int = 18                # ...up to here


@dataclass(frozen=True)
class BundleTool:
    """How one known bundle is offered: what it is called, what it says, how it is cited."""

    name: str
    description: str
    label: str          # names the source on every passage, so the model can cite it


TEACHING_LITERATURE = BundleTool(
    name="consult_teaching_literature",
    label="CO-CREATE handbook for teachers",
    # What it is for, how to use it, and -- appended by `inventory()` -- what it knows.
    # The subjects are not summarised here: the concept list below says them by name.
    description=(
        "Ask one or more questions about teaching practice and receive the passages of the "
        "professional literature that answer them best: a handbook for secondary-school "
        "teachers. Each call returns the passages closest to your questions plus the "
        "passages covering the concepts they touch. "
        + questions_arg.SHARED_TAIL +
        " This literature is written in English: ask in English whatever language the "
        "teacher writes in."
    ),
)


def inventory(names: list[str]) -> str:
    """The bundle naming itself, for the end of its tool's description.

    Last, after everything the model has to act on: a description is read past, and no
    instruction should sit behind a hundred nouns. Semicolons because a concept name may
    carry a comma of its own.
    """
    if not names:
        return ""
    return ("\n\nThe concepts this literature names, in the order it treats them: "
            + "; ".join(names) + ".")


# knowledge_unit, as the bundle's manifest declares it -> what this server offers it as.
BUNDLE_TOOLS: dict[str, BundleTool] = {
    "Handbook-for-Teachers": TEACHING_LITERATURE,
}


def offering(source) -> BundleTool:
    """What `source` is offered as. Raises when nothing offers it.

    A bundle that is mirrored, indexed and held in RAM but reachable by no tool is dead
    weight the model can never consult, and nothing at runtime would say so. Better to
    refuse to start.
    """
    unit = source.knowledge_unit
    try:
        return BUNDLE_TOOLS[unit]
    except KeyError:
        known = ", ".join(sorted(BUNDLE_TOOLS)) or "none"
        raise ValueError(
            f"knowledge source '{source.key}' is a bundle of knowledge unit {unit!r}, which "
            f"no tool offers -- the model could never consult it. Add a BundleTool for it "
            f"in {__name__} (units offered: {known})") from None


class BundleSearchTool:
    """Concept-and-chunk search over one AIKT bundle."""

    def __init__(self, *, source, offering: BundleTool,
                 embed: Callable[[str], Awaitable[list[float]]], evidence,
                 limits: "Limits | None" = None):
        self.source = source
        self.name = offering.name
        self.label = offering.label
        self.embed = embed
        self.evidence = evidence
        self.limits = limits or Limits()
        self.definition = questions_arg.definition(
            self.name, offering.description + inventory(source.concept_names))

    def _log_question(self, position: int, total: int, question: str,
                      chunk_hits: list, concept_hits: list) -> None:
        """One question and what both of its searches found, as one block -- they answer
        the same question and are read together. Refused distances are not dropped, only
        moved to DEBUG: the cutoffs are calibrated off them.
        """
        def ordinal(hit):
            return hit.metadata.get("ordinal")

        def named(hit):
            return hit.metadata.get("name")

        logger.info("%s", narration.block(
            f'{self.name}, question {position} of {total}: "{question}"',
            narration.INDENT + "passages: " + narration.search_outcome(
                "passage", chunk_hits, self.limits.max_chunk_distance, ordinal),
            narration.INDENT + "concepts: " + narration.search_outcome(
                "concept", concept_hits, self.limits.max_concept_distance, named)
            if self.limits.concept_k else ""))
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("%s: passages %s | concepts %s", self.name,
                         narration.distances(chunk_hits, self.limits.max_chunk_distance,
                                             ordinal),
                         narration.distances(concept_hits,
                                             self.limits.max_concept_distance, named))

    def _log_call(self, questions: list, passages: list, known: int, matched: list,
                  *, left_behind: int, spent: int) -> None:
        """What the model actually received, which the per-question lines above cannot say:
        passages are merged, dropped by the cap, and skipped when it already has them."""
        asked = f"{self.name} answered {narration.plural(len(questions), 'question')} -- "
        if not passages and not known:
            logger.info("%s", asked + "nothing in this literature was near enough")
            return
        outcome = [f"{narration.plural(len(passages), 'passage')} sent, "
                   f"{narration.tok(spent)}"]
        if known:
            outcome.append(f"{narration.count(known)} it already had")
        if left_behind:
            outcome.append(f"{narration.count(left_behind)} left behind by the cap")
        if matched:
            outcome.append(f"concepts: {', '.join(matched)}")
        logger.info("%s", narration.block(
            asked + "; ".join(outcome),
            narration.INDENT + narration.evidence_line(self.evidence)))

    # ------------------------------------------------------------------ running

    async def run(self, arguments: Any) -> dict[str, Any]:
        questions = questions_arg.parse(arguments)
        if isinstance(questions, dict):
            return questions

        direct: dict[str, float] = {}       # chunk id -> the best question hit it took
        by_concept: dict[str, float] = {}   # ...and, for a chunk a concept led to, its own
        nearest: list[str] = []             # each question's closest chunk, in ask order
        matched: list[str] = []
        unanswered: list[str] = []          # questions nothing was near enough to answer

        def keep(into: dict[str, float], key: str, distance: float) -> None:
            into[key] = min(into.get(key, distance), distance)

        for position, question in enumerate(questions, start=1):
            # One vector per question: both kinds live in the same collection, indexed by
            # the same embedder, and are told apart by a metadata filter.
            embedding = await self.embed(question)

            chunk_hits = self.source.search(embedding, k=self.limits.chunk_k,
                                            where={"kind": "chunk"})
            near = [h for h in chunk_hits if h.distance <= self.limits.max_chunk_distance]
            for hit in near:
                keep(direct, hit.id, hit.distance)

            concept_hits = []
            concepts = []
            if self.limits.concept_k:
                concept_hits = self.source.search(embedding, k=self.limits.concept_k,
                                                  where={"kind": "concept"})
                concepts = [h for h in concept_hits
                            if h.distance <= self.limits.max_concept_distance]
            self._log_question(position, len(questions), question, chunk_hits,
                               concept_hits)
            for hit in concepts:
                name = hit.metadata.get("name")
                if name and name not in matched:
                    matched.append(name)
                for chunk_id in self.source.concept_chunks.get(
                        hit.id, [])[:self.limits.chunks_per_concept]:
                    keep(by_concept, chunk_id, hit.distance)

            # Closest by distance, not first back: ranking is this tool's job, not the
            # index's, and a chunk hit outranks a concept-led one whatever their numbers.
            if near:
                nearest.append(min(near, key=lambda hit: hit.distance).id)
            elif concepts:
                closest = min(concepts, key=lambda hit: hit.distance)
                led = self.source.concept_chunks.get(closest.id, [])
                if led:
                    nearest.append(led[0])
            else:
                unanswered.append(question)

        # Two tiers, each ranked within itself, and the cap taken off the top. Not one
        # merged ranking: the two distances are different populations, and a chunk the
        # question hit outright is better evidence than one a matched concept led to.
        ranked = sorted(direct, key=direct.__getitem__)
        ranked += [i for i in sorted(by_concept, key=by_concept.__getitem__)
                   if i not in direct]

        cap = min(self.limits.chunks_per_question * len(questions),
                  self.limits.max_chunks)
        before = self.evidence.tokens
        passages, known = self._deliver(self._fill(cap, nearest, ranked))
        self._log_call(questions, passages, known, matched,
                       left_behind=max(0, len(ranked) - cap),
                       spent=self.evidence.tokens - before)
        result: dict[str, Any] = {"passages": passages}
        if matched:
            result["matched_concepts"] = matched

        notes: list[str] = []
        if unanswered:
            notes.append(questions_arg.too_far("this literature", unanswered))
        if known:
            notes.append(f"{known} matching passage(s) were already given to you earlier in "
                         "this answer, and are not repeated here.")
        if len(ranked) > cap:
            notes.append(f"{len(ranked) - cap} further passage(s) also "
                         "matched, less closely, and were not included. Ask a narrower "
                         "question if you need them.")
        if self.evidence.exhausted:
            notes.append("The evidence budget for this answer is spent. Answer from what "
                         "you have rather than searching again.")
        if notes:
            result["note"] = " ".join(notes)
        return result

    @staticmethod
    def _fill(cap: int, nearest: list[str], ranked: list[str]) -> list[str]:
        """The cap filled: one slot per question first, the rest by distance.

        The floor is one rather than a share. Its job is that no question the model asked
        is erased without trace -- a facet whose material was found and then dropped leaves
        a hole nothing reports, and one passage is enough for the model to know the facet
        has material. Past that the questions are not equally answerable by this bundle, so
        distance decides rather than fairness.
        """
        taken = list(dict.fromkeys(nearest))[:cap]
        return taken + [i for i in ranked if i not in taken][:cap - len(taken)]

    def _deliver(self, wanted: list[str]) -> "tuple[list[dict[str, Any]], int]":
        """Merge runs of consecutive ordinals, then hand them to the ledger.

        Merged before delivery, so an adjacent pair is charged and deduplicated as the one
        passage the model actually receives. Returns the passages that carry text and a
        count of the ones the model already has -- a passage with a status and no text is
        not material, and `run` says that in prose instead.
        """
        records = self.source.records

        def labels(chunk_id: str) -> dict[str, str]:
            metadata = records[chunk_id]
            return {"source": self.label,
                    "section": " > ".join(metadata.get("heading_path") or [])
                               or metadata.get("title") or ""}

        known = sum(1 for i in wanted if self.evidence.holds(i))

        ordered = sorted((i for i in wanted if not self.evidence.holds(i)),
                         key=lambda i: int(records[i].get("ordinal", 0)))

        runs: list[list[str]] = []
        for chunk_id in ordered:
            ordinal = int(records[chunk_id].get("ordinal", 0))
            previous = int(records[runs[-1][-1]].get("ordinal", 0)) if runs else None
            if runs and ordinal == previous + 1:
                runs[-1].append(chunk_id)
            else:
                runs.append([chunk_id])

        passages = []
        for run in runs:
            tokens = sum(int(records[i].get("token_count") or 0) for i in run)
            text = "\n\n".join(self.source.text(i) for i in run)
            passages.append(self.evidence.deliver_run(
                run, text, token_count=tokens or None, **labels(run[0])))
        return [p for p in passages if self.evidence.sent(p)], known


def bundle_search_tool(*, source, **kwargs) -> BundleSearchTool:
    """The tool this bundle is offered as. Raises when no tool offers it."""
    return BundleSearchTool(source=source, offering=offering(source), **kwargs)
