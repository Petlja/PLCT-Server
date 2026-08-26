"""Document order: the one thing the AI-context dataset does not record.

Chunks are cut on a fixed stride, so consecutive ones share a long verbatim region.
That overlap is all there is to go on: it puts a page's chunks back in order, and it is
carried once instead of twice when they are joined. `course_db.py` owns the lookups,
`store.py` owns the mirror and the collection.
"""

from dataclasses import dataclass, field

# The chunker's settings, which is what makes chunks_to_tokens possible without reading text.
CHUNK_SIZE = 3072
CHUNK_STRIDE = 1548


def chunks_to_tokens(chunk_count: int) -> int:
    """Size without reading a byte: chunks are CHUNK_SIZE tokens on a CHUNK_STRIDE stride."""
    return 0 if not chunk_count else CHUNK_STRIDE * (chunk_count - 1) + CHUNK_SIZE


PROBE_SKIP = 50
PROBE_LEN = 200
MIN_OVERLAP = 800      # real overlaps run 2400-4700 chars; anything less is coincidence
MAX_MISMATCH = 4       # tolerated U+FFFD substitutions across a verified overlap
REPLACEMENT = "�"


@dataclass
class Reconstruction:
    order: list[str]                      # chunk hashes, document order (best effort)
    text: str                             # de-overlapped, concatenated
    ordered: bool                         # did the chain resolve cleanly?
    problems: list[str] = field(default_factory=list)


def verified_overlap(a: str, b: str) -> tuple[int, int]:
    """Longest L where a's last L characters are b's first L. Returns (L, mismatches)."""
    if len(a) < PROBE_SKIP + PROBE_LEN:
        return 0, 0
    probe = a[len(a) - PROBE_SKIP - PROBE_LEN:len(a) - PROBE_SKIP]
    best, best_mismatch, at = 0, 0, 0
    while (at := b.find(probe, at)) != -1:
        length = PROBE_SKIP + PROBE_LEN + at
        at += 1
        if not MIN_OVERLAP <= length <= min(len(a), len(b)) or length <= best:
            continue
        mismatch = sum(1 for x, y in zip(a[-length:], b[:length]) if x != y)
        if mismatch <= MAX_MISMATCH:
            best, best_mismatch = length, mismatch
    return best, best_mismatch


def bridge(tail: str, head: str) -> str:
    """One copy of an overlap region, preferring whichever side is not U+FFFD."""
    if len(tail) != len(head):
        return head
    return "".join(h if t == REPLACEMENT else t for t, h in zip(tail, head))


def _chain(chunks: dict[str, str]) -> tuple[dict[str, str], dict[str, str], dict[str, int]]:
    """Link the chunks by verified overlap: (successor, predecessor, overlap length).

    Longest wins, and each chunk gets at most one of each, so contested joins are decided.
    """
    hashes = list(chunks)
    links: list[tuple[int, int, str, str]] = []     # (overlap, -mismatch, a, b)
    for a in hashes:
        for b in hashes:
            if a != b:
                length, mismatch = verified_overlap(chunks[a], chunks[b])
                if length:
                    links.append((length, -mismatch, a, b))

    succ: dict[str, str] = {}
    pred: dict[str, str] = {}
    lengths: dict[str, int] = {}
    end_of = {h: h for h in hashes}                 # path head -> its current tail
    start_of = {h: h for h in hashes}               # path tail -> its current head
    for length, _, a, b in sorted(links, reverse=True):
        if a in succ or b in pred or start_of.get(a) == b:
            continue                                # taken, or would close a cycle
        succ[a], pred[b], lengths[b] = b, a, length
        head, tail = start_of[a], end_of[b]
        end_of[head], start_of[tail] = tail, head
    return succ, pred, lengths


def _walk(start: str, succ: dict[str, str]) -> list[str]:
    """Follow the successor links from one chunk. Stops rather than circling."""
    order: list[str] = []
    seen: set[str] = set()
    cur: str | None = start
    while cur is not None and cur not in seen:
        order.append(cur)
        seen.add(cur)
        cur = succ.get(cur)
    return order


def _join(order: list[str], chunks: dict[str, str], lengths: dict[str, int]) -> str:
    """Concatenate chunks already in order, carrying each shared overlap exactly once."""
    parts: list[str] = []
    carry = chunks[order[0]]
    for cur in order[1:]:
        text, length = chunks[cur], lengths[cur]
        parts.append(carry[:-length])
        carry = bridge(carry[-length:], text[:length]) + text[length:]
    parts.append(carry)
    return "".join(parts)


def _unordered(chunks: dict[str, str], problems: list[str]) -> Reconstruction:
    return Reconstruction(list(chunks), "\n\n".join(chunks.values()), False, problems)


def reconstruct(chunks: dict[str, str]) -> Reconstruction:
    """Order the chunks of one activity by their build-time overlap and strip it.

    All-or-nothing: a set it cannot fully order comes back concatenated in arbitrary order
    with `ordered=False`, rather than in a guessed one.
    """
    hashes = list(chunks)
    if len(hashes) <= 1:
        return Reconstruction(hashes, chunks[hashes[0]] if hashes else "", True)

    succ, pred, lengths = _chain(chunks)
    problems: list[str] = []

    unlinked = [h[:8] for h in hashes if h not in pred and h not in succ]
    if unlinked:
        problems.append(f"{len(unlinked)} chunk(s) share no overlap with any other: "
                        f"{', '.join(unlinked)}")

    heads = [h for h in hashes if h not in pred]
    if len(heads) != 1 or len(succ) != len(hashes) - 1:
        problems.append(f"chain unresolved: {len(heads)} head(s), "
                        f"{len(succ)} link(s) for {len(hashes)} chunks")
        return _unordered(chunks, problems)

    order = _walk(heads[0], succ)
    if len(order) != len(hashes):
        problems.append(f"walk visited {len(order)} of {len(hashes)} chunks (cycle?)")
        return _unordered(chunks, problems)

    return Reconstruction(order, _join(order, chunks, lengths), True, problems)


def fuse(chunks: dict[str, str]) -> list[Reconstruction]:
    """Group chunks into the runs that actually chain, and reconstruct each run.

    For an arbitrary handful pulled out of a big page, where `reconstruct`'s all-or-nothing
    rule is wrong: neighbours share ~1,524 tokens and would otherwise be sent twice.
    """
    if len(chunks) <= 1:
        return [reconstruct(chunks)]
    succ, pred, _ = _chain(chunks)
    runs = [_walk(start, succ) for start in chunks if start not in pred]
    return [reconstruct({i: chunks[i] for i in run}) for run in runs]
