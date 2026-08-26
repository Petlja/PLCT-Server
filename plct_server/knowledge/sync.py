"""Mirror every configured source onto local disk, once, at startup."""

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path, PurePosixPath

import httpx
import zstandard as zstd

from ..ai.context_dataset import CourseSummary
from .cache import (MANIFEST, is_remote, mirror_root, read_manifest, write_atomic,
                    write_manifest)
from .config import DEFAULT_CACHE_DIR, SourceSpec

logger = logging.getLogger(__name__)

EMBEDDING_MODEL = "text-embedding-3-large"
EMBEDDING_SIZE = 1536
EMB_TYPE = f"{EMBEDDING_MODEL}-{EMBEDDING_SIZE}"

CHUNK_META = ".chunk-meta.json"   # chunk_hash -> metadata, lifted out of the payload
DEFAULT_WORKERS = 16

ENTRY_FILE = {"plct-ai-ctx": "index.json", "aikt-bundle": "manifest.json"}


@dataclass
class SyncStats:
    fetched: int = 0
    skipped: int = 0
    bytes: int = 0
    seconds: float = 0.0
    missing: list[str] = field(default_factory=list)   # 404 -- absent from the source
    failed: list[str] = field(default_factory=list)    # transport error after retries

    def summary(self) -> str:
        return (f"{self.fetched} fetched, {self.skipped} already local, "
                f"{self.bytes / 1e6:.1f} MB, {self.seconds:.1f}s"
                + (f", {len(self.missing)} missing" if self.missing else "")
                + (f", {len(self.failed)} FAILED" if self.failed else ""))


# --------------------------------------------------------------------------- fetching


def _get(client: httpx.Client, url: str, attempts: int = 3) -> bytes | None:
    """Bytes, or None for 404. Retries transport errors with backoff."""
    for attempt in range(attempts):
        try:
            response = client.get(url)
            if response.status_code == 404:
                return None
            response.raise_for_status()
            return response.content
        except httpx.HTTPError as exc:
            if attempt == attempts - 1:
                raise
            logger.debug("retry %d for %s (%s)", attempt + 1, url, exc)
            time.sleep(0.5 * 2 ** attempt)
    return None


def _fetch_many(client: httpx.Client, base_url: str, dest: Path, rel_paths: list[str],
                *, workers: int, force: bool, stats: SyncStats, label: str) -> None:
    """Download rel_paths into dest, in parallel, skipping what is already there."""
    todo = [r for r in rel_paths if force or not (dest / r).exists()]
    stats.skipped += len(rel_paths) - len(todo)
    if not todo:
        logger.info("%s: %d files already local", label, len(rel_paths))
        return

    logger.info("%s: fetching %d of %d files", label, len(todo), len(rel_paths))
    done = 0

    def one(rel: str) -> tuple[str, int | None]:
        try:
            data = _get(client, f"{base_url}/{rel}")
        except httpx.HTTPError as exc:
            logger.warning("failed: %s (%s)", rel, exc)
            return rel, -1
        if data is None:
            return rel, None
        write_atomic(dest / rel, data)
        return rel, len(data)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for rel, size in pool.map(one, todo):
            done += 1
            if size is None:
                stats.missing.append(rel)
            elif size < 0:
                stats.failed.append(rel)
            else:
                stats.fetched += 1
                stats.bytes += size
            if done % 250 == 0:
                logger.info("%s: %d/%d", label, done, len(todo))


def _safe_rel(value, label: str) -> str:
    """A relative path from the source that is not allowed to escape the mirror."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"invalid {label} in source metadata: {value!r}")
    rel = PurePosixPath(value.strip().replace("\\", "/"))
    if rel.is_absolute() or ".." in rel.parts:
        raise ValueError(f"{label} leaves the source directory: {value!r}")
    return str(rel)


# --------------------------------------------------------------------------- sync


def sync(spec: SourceSpec, cache_dir: str | Path = DEFAULT_CACHE_DIR, *,
         workers: int = DEFAULT_WORKERS, force: bool = False) -> Path:
    """Mirror one source and return its local root. A local source is used in place."""
    root = mirror_root(spec, cache_dir)
    entry_name = ENTRY_FILE[spec.type]

    if not is_remote(spec.url):
        if not (root / entry_name).exists():
            raise ValueError(f"source '{spec.key}': no {entry_name} in {root}")
        logger.info("source '%s': local, used in place (%s)", spec.key, root)
        return root

    base_url = spec.url.rstrip("/")
    root.mkdir(parents=True, exist_ok=True)

    with httpx.Client(timeout=60.0, follow_redirects=True) as client:
        entry_raw = _get(client, f"{base_url}/{entry_name}")
        if entry_raw is None:
            raise ValueError(f"source '{spec.key}': no {entry_name} at {base_url} "
                             "-- is the URL right?")
        digest = sha256(entry_raw).hexdigest()

        manifest = read_manifest(root)
        if not force and manifest and manifest.get("complete") \
                and manifest.get("entry_sha256") == digest:
            logger.info("source '%s': mirror up to date (%s)", spec.key, root)
            return root

        changed = bool(manifest) and manifest.get("entry_sha256") != digest
        if changed:
            logger.info("source '%s': %s changed, re-fetching mutable files",
                        spec.key, entry_name)

        stats = SyncStats()
        started = time.time()
        logger.info("source '%s': syncing %s -> %s", spec.key, base_url, root)
        write_atomic(root / entry_name, entry_raw)
        stats.fetched += 1
        stats.bytes += len(entry_raw)

        if spec.type == "plct-ai-ctx":
            counts = _sync_ai_ctx(client, base_url, root, entry_raw, workers=workers,
                                  force=force or changed, stats=stats)
        else:
            counts = _sync_bundle(client, base_url, root, entry_raw, workers=workers,
                                  force=force or changed, stats=stats)

        stats.seconds = time.time() - started
        write_manifest(root, {
            "key": spec.key,
            "type": spec.type,
            "url": base_url,
            "entry_sha256": digest,
            "synced_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            **counts,
            "missing": stats.missing,
            "complete": not stats.missing and not stats.failed,
        })
        logger.info("source '%s': %s", spec.key, stats.summary())
        if stats.failed:
            raise ValueError(f"source '{spec.key}': {len(stats.failed)} file(s) failed to "
                             f"download, first: {stats.failed[0]}")
    return root


def _payload_labels(path: Path) -> tuple[list[str], list[dict]]:
    """ids and metadatas out of emb-*.json.zst; the vectors are read and dropped."""
    with zstd.open(path, "rt", encoding="utf-8") as f:
        data = json.load(f)
    ids, metadatas = data["ids"], data["metadatas"]
    data.pop("embeddings", None)
    return ids, metadatas


def _sync_ai_ctx(client: httpx.Client, base_url: str, dest: Path, entry_raw: bytes, *,
                 workers: int, force: bool, stats: SyncStats) -> dict:
    """Mirror what the runtime reads: index, summaries, the payload, and chunk texts."""
    course_keys: list[str] = json.loads(entry_raw)["courses"]

    _fetch_many(client, base_url, dest, [f"{ck}/summary.json" for ck in course_keys],
                workers=workers, force=True, stats=stats, label="course summaries")

    # The summaries name their own text files, so the file list comes from the dataset
    # itself -- no container listing, which the blob URL does not offer anyway.
    text_paths: list[str] = []
    for course_key in course_keys:
        raw = (dest / course_key / "summary.json").read_text(encoding="utf-8")
        course = CourseSummary.model_validate_json(raw)
        text_paths.append(f"{course_key}/{course.summary_text_path}")
        text_paths.append(f"{course_key}/{course.toc_text_path}")
        text_paths += [f"{course_key}/{a.summary_text_path}"
                       for a in course.activities.values()]

    emb_rel = f"emb-{EMB_TYPE}.json.zst"
    emb_path = dest / emb_rel
    if force or not emb_path.exists():
        logger.info("payload: downloading %s", emb_rel)
        payload = _get(client, f"{base_url}/{emb_rel}")
        if payload is None:
            raise ValueError(f"no {emb_rel} at {base_url}")
        write_atomic(emb_path, payload)
        stats.fetched += 1
        stats.bytes += len(payload)
        del payload
    else:
        stats.skipped += 1
        logger.info("payload: %s already local", emb_rel)

    logger.info("payload: reading ids and metadata")
    ids, metadatas = _payload_labels(emb_path)
    write_atomic(dest / CHUNK_META,
                 json.dumps(dict(zip(ids, metadatas)), ensure_ascii=False).encode("utf-8"))
    logger.info("payload: %d chunks", len(ids))

    # Chunk ids are content hashes: an existing file can never be stale, so never force.
    _fetch_many(client, base_url, dest, sorted(set(text_paths)),
                workers=workers, force=force, stats=stats, label="summary texts")
    _fetch_many(client, base_url, dest, [f"chunks/{h[:2]}/{h}.txt" for h in ids],
                workers=workers, force=False, stats=stats, label="chunk texts")

    return {"emb_type": EMB_TYPE, "courses": len(course_keys), "chunks": len(ids),
            "summary_texts": len(set(text_paths))}


def _sync_bundle(client: httpx.Client, base_url: str, dest: Path, entry_raw: bytes, *,
                 workers: int, force: bool, stats: SyncStats) -> dict:
    """Mirror an AI-Knowledge-Tools index bundle: manifest, records, chunk payloads."""
    manifest = json.loads(entry_raw)
    if manifest.get("schema_version") != 1 or \
            manifest.get("artifact_type") != "vector_index_data":
        raise ValueError(f"not an index bundle at {base_url}: "
                         f"schema_version={manifest.get('schema_version')!r} "
                         f"artifact_type={manifest.get('artifact_type')!r}")

    records_rel = _safe_rel(manifest.get("records_file"), "records_file")
    raw = _get(client, f"{base_url}/{records_rel}")
    if raw is None:
        raise ValueError(f"no {records_rel} at {base_url}")
    write_atomic(dest / records_rel, raw)
    stats.fetched += 1
    stats.bytes += len(raw)

    rel_paths: list[str] = []
    chunks = concepts = 0
    for number, line in enumerate(raw.decode("utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid record at {records_rel}:{number}") from exc
        kind = record.get("kind")
        if kind == "chunk":
            chunks += 1
            metadata = record.get("metadata") or {}
            for name in ("text_file", "chunk_file"):
                if metadata.get(name):
                    rel_paths.append(_safe_rel(metadata[name], name))
        elif kind == "concept":
            concepts += 1
    del raw

    _fetch_many(client, base_url, dest, sorted(set(rel_paths)),
                workers=workers, force=force, stats=stats, label="chunk payloads")

    # The manifest states what the bundle should contain; disagreement means a partial
    # upload, which is worth failing on rather than serving.
    declared = manifest.get("counts") or {}
    for name, seen in (("chunks", chunks), ("concepts", concepts)):
        if declared.get(name) is not None and declared[name] != seen:
            raise ValueError(f"bundle at {base_url} declares {declared[name]} {name} "
                             f"but {records_rel} holds {seen}")

    return {"knowledge_unit": manifest.get("knowledge_unit"),
            "embedding_model": manifest.get("embedding_model"),
            "embedding_dimensions": manifest.get("embedding_dimensions"),
            "concepts": concepts, "chunks": chunks, "payload_files": len(set(rel_paths))}


# --------------------------------------------------------------------------- verify


def verify(spec: SourceSpec, cache_dir: str | Path = DEFAULT_CACHE_DIR) -> tuple[int, list[str]]:
    """Check a mirror against what the source says it should hold.

    Returns (items checked, problems). For a course dataset every chunk file is re-hashed
    against its id -- a chunk id is sha256("course_key\\ntext"). For a bundle every file a
    record names has to be present and non-empty.
    """
    root = mirror_root(spec, cache_dir)
    if spec.type == "plct-ai-ctx":
        return _verify_ai_ctx(root)
    return _verify_bundle(root)


def _verify_ai_ctx(root: Path) -> tuple[int, list[str]]:
    meta_path = root / CHUNK_META
    if not meta_path.exists():
        return 0, [f"{CHUNK_META} missing -- run sync"]
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    bad: list[str] = []
    for i, (chunk_hash, m) in enumerate(meta.items(), 1):
        path = root / "chunks" / chunk_hash[:2] / f"{chunk_hash}.txt"
        if not path.exists():
            bad.append(f"{chunk_hash} missing")
            continue
        text = path.read_text(encoding="utf-8")
        digest = sha256("\n".join([m["course_key"], text]).encode("utf-8")).hexdigest()
        if digest != chunk_hash:
            bad.append(f"{chunk_hash} hash mismatch")
        if i % 500 == 0:
            logger.info("verified %d/%d", i, len(meta))
    return len(meta), bad


def _verify_bundle(root: Path) -> tuple[int, list[str]]:
    manifest_path = root / "manifest.json"
    if not manifest_path.exists():
        return 0, ["manifest.json missing -- run sync"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    records_path = root / _safe_rel(manifest.get("records_file"), "records_file")
    if not records_path.exists():
        return 0, [f"{records_path.name} missing -- run sync"]

    bad: list[str] = []
    checked = 0
    with records_path.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            record = json.loads(line)
            if record.get("kind") != "chunk":
                continue
            checked += 1
            metadata = record.get("metadata") or {}
            for name in ("text_file", "chunk_file"):
                if not metadata.get(name):
                    continue
                path = root / _safe_rel(metadata[name], name)
                if not path.exists():
                    bad.append(f"{metadata[name]} missing")
                elif path.stat().st_size == 0:
                    bad.append(f"{metadata[name]} empty")

    declared = (manifest.get("counts") or {}).get("chunks")
    if declared is not None and declared != checked:
        bad.append(f"manifest declares {declared} chunks, records hold {checked}")
    return checked, bad
