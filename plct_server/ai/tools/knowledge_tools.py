"""The tool over one AI-Knowledge-Tools bundle.

AIKT prepares knowledge; it does not describe it. A tool description is prompt engineering
-- calibrated against this model, and against the sibling tools it competes with for the
model's attention -- so it is authored here, beside those siblings, and bound to a bundle by
the `knowledge_unit` its manifest declares. That name travels with the artifact, so renaming
a source key in the server config cannot silently detach a tool from its knowledge.

One bundle, one tool: a merged tool over several bundles would have to describe itself by
listing what it holds, and a generated inventory is not a description a model routes on.
When a second bundle arrives it gets its own entry below.
"""

import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from . import questions as questions_arg

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Limits:
    """How much one call may pull back. Calibrated over the bundle -- doc/ai_flow.md section 6."""

    chunk_k: int = 5                    # chunk hits per question
    concept_k: int = 3                  # ...and concepts, each expanding to its own chunks
    chunks_per_concept: int = 3
    # Two cutoffs rather than one: a concept vector is a short name, so it sits nearer any
    # question by construction and its distances are a different population from a chunk's.
    # Cosine over the bundle's own embedder -- text-embedding-3-small here, where the course
    # layer is -3-large, so neither layer's scale transfers to the other. Over this handbook
    # answers land under ~0.46. The log marks what each cutoff refused, to recalibrate on.
    max_chunk_distance: float = 0.46
    max_concept_distance: float = 0.46
    # The handbook is 122 chunks, 62k tokens. Five questions at chunk_k=5, each with three
    # concepts of three chunks, reach for 70 of those chunks: that is not retrieval, it is
    # paging in the book, and it spends an evidence budget the course layer also needs.
    # The cap is what keeps a call worth a few passages instead of a third of the corpus.
    max_chunks: int = 12


@dataclass(frozen=True)
class BundleTool:
    """How one known bundle is offered: what it is called, what it says, how it is cited."""

    name: str
    description: str
    label: str          # names the source on every passage, so the model can cite it


TEACHING_LITERATURE = BundleTool(
    name="consult_teaching_literature",
    label="CO-CREATE handbook for teachers",
    description=(
        "Ask one or more questions about teaching practice and receive the passages of the "
        "professional literature that answer them best. The literature here is a handbook "
        "for secondary-school teachers, and it covers how students learn and differ "
        "(multiple intelligences, learning styles, motivation, mindset, self-regulated "
        "learning); how a lesson is planned, taught and evaluated (teaching methods, forms "
        "of work, learning outcomes, formative and summative assessment, rubrics, "
        "portfolios); how a class is run (classroom management, group and pair work, "
        "collaborative problem solving); how to teach a mixed class (inclusive education, "
        "gifted students, students with special educational needs); and the ethics of "
        "using AI in education. Each call returns the passages closest to your questions "
        "plus the passages covering the concepts they touch. "
        + questions_arg.SHARED_TAIL +
        " This literature is written in English: ask in English whatever language the "
        "teacher writes in."
    ),
)

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
        self.definition = questions_arg.definition(self.name, offering.description)

    def _far(self, hits: list, cutoff: float, name: Callable[[Any], Any]) -> str:
        """Every hit with its distance, `far` marking the ones the cutoff drops.

        The refused distances stay in the log, because the cutoffs are calibrated off them:
        a threshold whose rejections are invisible cannot be moved with any evidence.
        """
        return ", ".join(
            f"{name(hit)}={hit.distance:.3f}{'' if hit.distance <= cutoff else ' far'}"
            for hit in hits) or "none"

    # ------------------------------------------------------------------ running

    async def run(self, arguments: Any) -> dict[str, Any]:
        questions = questions_arg.parse(arguments)
        if isinstance(questions, dict):
            return questions

        direct: dict[str, float] = {}       # chunk id -> the best question hit it took
        by_concept: dict[str, float] = {}   # ...and, for a chunk a concept led to, its own
        matched: list[str] = []
        unanswered: list[str] = []          # questions nothing was near enough to answer

        def keep(into: dict[str, float], key: str, distance: float) -> None:
            into[key] = min(into.get(key, distance), distance)

        for question in questions:
            # One vector per question: both kinds live in the same collection, indexed by
            # the same embedder, and are told apart by a metadata filter.
            embedding = await self.embed(question)

            chunk_hits = self.source.search(embedding, k=self.limits.chunk_k,
                                            where={"kind": "chunk"})
            logger.info("%s: %r -> %s", self.name, question,
                        self._far(chunk_hits, self.limits.max_chunk_distance,
                                  lambda hit: hit.metadata.get("ordinal")))
            near = [h for h in chunk_hits if h.distance <= self.limits.max_chunk_distance]
            for hit in near:
                keep(direct, hit.id, hit.distance)

            concepts = []
            if self.limits.concept_k:
                concept_hits = self.source.search(embedding, k=self.limits.concept_k,
                                                  where={"kind": "concept"})
                logger.info("%s: %r -> concepts %s", self.name, question,
                            self._far(concept_hits, self.limits.max_concept_distance,
                                      lambda hit: hit.metadata.get("name")))
                concepts = [h for h in concept_hits
                            if h.distance <= self.limits.max_concept_distance]
            for hit in concepts:
                name = hit.metadata.get("name")
                if name and name not in matched:
                    matched.append(name)
                for chunk_id in self.source.concept_chunks.get(
                        hit.id, [])[:self.limits.chunks_per_concept]:
                    keep(by_concept, chunk_id, hit.distance)

            if not near and not concepts:
                unanswered.append(question)

        # Two tiers, each ranked within itself, and the cap taken off the top. Not one
        # merged ranking: the two distances are different populations, and a chunk the
        # question hit outright is better evidence than one a matched concept led to.
        ranked = sorted(direct, key=direct.__getitem__)
        ranked += [i for i in sorted(by_concept, key=by_concept.__getitem__)
                   if i not in direct]

        passages, known = self._deliver(ranked[:self.limits.max_chunks])
        result: dict[str, Any] = {"passages": passages}
        if matched:
            result["matched_concepts"] = matched

        notes: list[str] = []
        if unanswered:
            notes.append(questions_arg.too_far("this literature", unanswered))
        if known:
            notes.append(f"{known} matching passage(s) were already given to you earlier in "
                         "this answer, and are not repeated here.")
        if len(ranked) > self.limits.max_chunks:
            notes.append(f"{len(ranked) - self.limits.max_chunks} further passage(s) also "
                         "matched, less closely, and were not included. Ask a narrower "
                         "question if you need them.")
        if self.evidence.exhausted:
            notes.append("The evidence budget for this answer is spent. Answer from what "
                         "you have rather than searching again.")
        if notes:
            result["note"] = " ".join(notes)
        return result

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
