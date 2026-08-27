"""One request's delivered passages: deduplicated once, budgeted once."""

import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)

DEFAULT_MAX_EVIDENCE_TOKENS = 35_000

# Below this the budget is spent in the only sense the model can act on: a course chunk is
# 3,072 tokens on a fixed stride and a whole page is larger still, so nothing the course
# layer holds can arrive any more. The handbook could still squeeze one ~500-token passage
# in, which is not worth another round against the risk of searching instead of answering.
EXHAUSTED_BELOW = 3_072


def estimate_tokens(text: str) -> int:
    """A cheap standing estimate. Callers with a real tokenizer should pass one in."""
    return max(1, len(text) // 4)


class Evidence:
    """The ledger for one request."""

    def __init__(self, *, max_tokens: int = DEFAULT_MAX_EVIDENCE_TOKENS,
                 count_tokens: Callable[[str], int] | None = None):
        self.max_tokens = max_tokens
        self._count = count_tokens or estimate_tokens
        self.delivered: dict[str, int] = {}     # passage id -> tokens it cost
        self.tokens = 0
        self.provenance: list[dict[str, str]] = []   # for the offline report, not the model

    def holds(self, passage_id: str) -> bool:
        return passage_id in self.delivered

    @property
    def remaining(self) -> int:
        """Budget still unspent. What a tool asks before choosing how much to send."""
        return max(0, self.max_tokens - self.tokens)

    @property
    def exhausted(self) -> bool:
        """Is there room left for anything worth fetching?

        Read off what is unspent, never latched by a refusal. One page too large to fit is
        not a spent budget: latching there told the model to stop searching while most of
        the budget was still free, and the largest pages are exactly the ones that trip it.
        Being true before anything is refused is the point rather than a side effect -- the
        warning is worth more ahead of a wasted round than after one.
        """
        return self.remaining < EXHAUSTED_BELOW

    def deliver(self, passage_id: str, text: str, *, token_count: int | None = None,
                record: dict[str, str] | None = None, **labels: Any) -> dict[str, Any]:
        """Account for one passage and return what the model should see of it.

        Three outcomes, all of them data: the text, "already provided", or "budget spent".
        The labels ride along in every case, so the model can tell passages apart with no id.
        """
        if passage_id in self.delivered:
            return {**labels, "status": "already_provided"}

        tokens = token_count if isinstance(token_count, int) and token_count > 0 \
            else self._count(text)

        if self.delivered and self.tokens + tokens > self.max_tokens:
            logger.info("evidence: budget exhausted, %d tok would exceed %d",
                        tokens, self.max_tokens)
            return {**labels, "status": "budget_exhausted"}

        self.delivered[passage_id] = tokens
        self.tokens += tokens
        if record:
            self.provenance.append(record)
        return {**labels, "text": text}

    @staticmethod
    def sent(passage: dict[str, Any]) -> bool:
        """Did this passage's text actually go out, or is it one of the two notes?"""
        return "text" in passage

    def deliver_run(self, ids: list[str], text: str, *, token_count: int | None = None,
                    record: dict[str, str] | None = None,
                    **labels: Any) -> dict[str, Any]:
        """One passage made of several chunks: charge the head, mark the rest spent.

        Only if the text went out -- a passage the budget refused stays available to a
        later, smaller call instead of reporting as already sent.
        """
        head, *rest = ids
        passage = self.deliver(head, text, token_count=token_count, record=record,
                               **labels)
        if self.sent(passage):
            for spent in rest:
                self.deliver(spent, "", token_count=1, **labels)
        return passage

    def summary(self) -> str:
        return (f"{len(self.delivered)} passage(s), {self.tokens} token(s)"
                + (", budget exhausted" if self.exhausted else ""))
