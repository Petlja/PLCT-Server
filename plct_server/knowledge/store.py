"""One Chroma client, one collection per source.

Collections are independent by construction: each owns its index, its dimensionality, its
distance space and its metadata schema, and Chroma validates none of that across
collections. So the course dataset (`text-embedding-3-large`@1536, inner product) and an
AI-Knowledge-Tools bundle (`text-embedding-3-small`@1536, cosine) coexist in one client
with no coupling at all -- two tables in one database.

The store is a registry and a lifecycle owner, not a query planner. `store.source(key)`
hands back one source and the caller searches that one; there is deliberately no
`search_all()`. A question is routed to a source, and that source embeds it with the model
that built its vectors.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import chromadb
from chromadb.config import Settings

from ..ai.context_dataset import ContextDataset
from .config import SourceSpec
from .sync import EMBEDDING_MODEL, EMBEDDING_SIZE

logger = logging.getLogger(__name__)


@dataclass
class Hit:
    """One retrieved record. `text` is read from the mirror, not held in RAM."""

    source_key: str
    id: str
    distance: float
    metadata: dict[str, Any]
    _source: "KnowledgeSource" = field(repr=False)

    @property
    def text(self) -> str:
        return self._source.text(self.id)


class KnowledgeSource:
    """A body of indexed knowledge with its own vectors, mirrored to `root`."""

    embedding_model: str
    embedding_dimensions: int
    distance: str          # Chroma hnsw:space

    def __init__(self, spec: SourceSpec, root: Path):
        self.spec = spec
        self.root = Path(root)
        self.collection = None

    @property
    def key(self) -> str:
        return self.spec.key

    @property
    def collection_name(self) -> str:
        return f"{self.key}-{self.embedding_model}-{self.embedding_dimensions}"

    def load(self, client) -> None:
        """Create this source's collection and fill it. Called once, at startup."""
        raise NotImplementedError

    def text(self, record_id: str) -> str:
        raise NotImplementedError

    def describe(self) -> str:
        count = self.collection.count() if self.collection is not None else 0
        return (f"{self.key} [{self.spec.type}] {count} records, "
                f"{self.embedding_model}@{self.embedding_dimensions}, {self.distance}")

    # -- shared machinery ---------------------------------------------------

    def _create_collection(self, client):
        self.collection = client.create_collection(
            name=self.collection_name, metadata={"hnsw:space": self.distance})
        return self.collection

    def _add_batched(self, client, ids: list[str], embeddings: list, metadatas: list[dict]) -> None:
        batch = client.get_max_batch_size()
        for start in range(0, len(ids), batch):
            end = min(start + batch, len(ids))
            self.collection.add(ids=ids[start:end], embeddings=embeddings[start:end],
                                metadatas=metadatas[start:end])
            logger.debug("%s: indexed %d-%d", self.key, start, end)

    def _metadata_for(self, record_id: str, chroma_metadata: dict) -> dict:
        return dict(chroma_metadata or {})

    def search(self, embedding: list[float], *, k: int = 5,
               where: dict | None = None) -> list[Hit]:
        """The k nearest records, optionally filtered by metadata."""
        if self.collection is None:
            raise ValueError(f"source '{self.key}' is not loaded")
        if k <= 0:
            return []
        result = self.collection.query(query_embeddings=[embedding], n_results=k,
                                       where=where or None)
        hits: list[Hit] = []
        for record_id, distance, metadata in zip(result["ids"][0], result["distances"][0],
                                                 result["metadatas"][0]):
            hits.append(Hit(source_key=self.key, id=record_id, distance=float(distance),
                            metadata=self._metadata_for(record_id, metadata), _source=self))
        return hits


class CourseSource(KnowledgeSource):
    """The PLCT-AI-Ctx dataset: courses, lessons, activity summaries and chunk vectors.

    Wraps `ContextDataset` pointed at the mirror, so summaries, the TOC and chunk text are
    disk reads. That also makes the served text match the dataset's own hashes: the files
    were written on Windows with CRLF, and a local read translates them back to LF --
    exactly the text that was chunked and hashed -- while an HTTP read does not.
    """

    embedding_model = EMBEDDING_MODEL
    embedding_dimensions = EMBEDDING_SIZE
    distance = "ip"

    def __init__(self, spec: SourceSpec, root: Path):
        super().__init__(spec, root)
        # As a file:// URL: FileSet.from_base_url parses what it is given, and on Windows
        # an absolute path like C:\cache\courses reads as the URL scheme "c".
        self.ctx = ContextDataset(self.root.resolve().as_uri())

    @property
    def course_dict(self):
        return self.ctx.course_dict

    def load(self, client) -> None:
        self._create_collection(client)
        logger.info("source '%s': loading %s payload", self.key, self.collection_name)
        embeddings, ids, metadatas = self.ctx.get_embeddings_data(
            self.embedding_model, self.embedding_dimensions)
        self._add_batched(client, ids, embeddings, metadatas)
        logger.info("source '%s': %d chunk vectors indexed", self.key, len(ids))

    def text(self, record_id: str) -> str:
        return self.ctx.get_chunk_text(record_id)


class BundleSource(KnowledgeSource):
    """An AI-Knowledge-Tools index bundle: concept and chunk vectors over one unit.

    Records are streamed into Chroma and only their metadata is kept in RAM. AIKT's own
    `build_index_session` retains every embedding in `records_by_id` on top of the copy
    Chroma holds -- 7.8 MB for this unit, and linear in the corpus. Same validation, no
    second copy.
    """

    distance = "cosine"

    def __init__(self, spec: SourceSpec, root: Path):
        super().__init__(spec, root)
        manifest_path = self.root / "manifest.json"
        try:
            self.manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise ValueError(f"source '{spec.key}': no manifest at {manifest_path}") from exc
        if self.manifest.get("schema_version") != 1 or \
                self.manifest.get("artifact_type") != "vector_index_data":
            raise ValueError(f"source '{spec.key}': {manifest_path} is not an index bundle")
        self.embedding_model = self.manifest["embedding_model"]
        self.embedding_dimensions = int(self.manifest["embedding_dimensions"])
        self.knowledge_unit = self.manifest.get("knowledge_unit") or spec.key
        self.records: dict[str, dict] = {}          # record_id -> full metadata
        self.concept_chunks: dict[str, list[str]] = {}

    def _records_file(self) -> Path:
        return self.root / str(self.manifest.get("records_file") or "records.jsonl")

    def _stream_records(self) -> Iterable[dict]:
        path = self._records_file()
        with path.open(encoding="utf-8") as f:
            for number, line in enumerate(f, start=1):
                if not line.strip():
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"invalid record at {path}:{number}") from exc

    def load(self, client) -> None:
        self._create_collection(client)
        logger.info("source '%s': loading %s", self.key, self._records_file().name)

        ids: list[str] = []
        embeddings: list[list[float]] = []
        metadatas: list[dict] = []
        assignments: dict[str, list[tuple[float, int, str]]] = {}
        batch = client.get_max_batch_size()

        def flush() -> None:
            if ids:
                self.collection.add(ids=ids, embeddings=embeddings, metadatas=metadatas)
                ids.clear()
                embeddings.clear()
                metadatas.clear()

        for record in self._stream_records():
            record_id = record.get("id")
            kind = record.get("kind")
            embedding = record.get("embedding")
            metadata = record.get("metadata")
            if not isinstance(record_id, str) or kind not in ("concept", "chunk") \
                    or not isinstance(metadata, dict) or not isinstance(embedding, list) \
                    or len(embedding) != self.embedding_dimensions:
                raise ValueError(f"source '{self.key}': invalid {kind} record {record_id!r}")

            # Chroma metadata holds scalars only; the full record metadata stays here.
            self.records[record_id] = metadata
            flat = {"kind": kind,
                    "title": metadata.get("title") or metadata.get("name") or ""}
            if kind == "chunk":
                flat["ordinal"] = int(metadata.get("ordinal", 0))
                for assignment in metadata.get("concepts") or []:
                    if not isinstance(assignment, dict):
                        continue
                    concept_id = assignment.get("id")
                    if not isinstance(concept_id, str) or not concept_id:
                        continue
                    confidence = assignment.get("confidence")
                    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
                        confidence = 0.0
                    assignments.setdefault(concept_id, []).append(
                        (float(confidence), flat["ordinal"], record_id))

            ids.append(record_id)
            embeddings.append(embedding)
            metadatas.append(flat)
            if len(ids) >= batch:
                flush()
        flush()

        # Ranked by confidence, then document order -- what the next chunk's tool needs.
        self.concept_chunks = {
            concept_id: [rid for _, _, rid in sorted(entries, key=lambda e: (-e[0], e[1]))]
            for concept_id, entries in assignments.items()}

        kinds: dict[str, int] = {}
        for metadata in self.records.values():
            kinds["chunk" if "ordinal" in metadata else "concept"] = \
                kinds.get("chunk" if "ordinal" in metadata else "concept", 0) + 1
        logger.info("source '%s': %d records indexed (%s)", self.key, len(self.records),
                    ", ".join(f"{n} {k}" for k, n in sorted(kinds.items())))

    def _metadata_for(self, record_id: str, chroma_metadata: dict) -> dict:
        return dict(self.records.get(record_id) or chroma_metadata or {})

    def text(self, record_id: str) -> str:
        """A chunk's Markdown payload, or a concept's description."""
        metadata = self.records.get(record_id)
        if metadata is None:
            raise ValueError(f"source '{self.key}': unknown record {record_id!r}")
        text_file = metadata.get("text_file")
        if not text_file:
            return metadata.get("description") or ""
        path = (self.root / text_file).resolve()
        if not path.is_relative_to(self.root.resolve()):
            raise ValueError(f"source '{self.key}': {text_file} leaves the bundle")
        return path.read_text(encoding="utf-8")


SOURCE_TYPES = {"plct-ai-ctx": CourseSource, "aikt-bundle": BundleSource}


def source_for(spec: SourceSpec, root: Path) -> KnowledgeSource:
    return SOURCE_TYPES[spec.type](spec, root)


class KnowledgeStore:
    """Every loaded source, over one in-memory Chroma client."""

    def __init__(self, client=None):
        self.client = client or chromadb.Client(Settings(anonymized_telemetry=False))
        self._sources: dict[str, KnowledgeSource] = {}

    def add(self, source: KnowledgeSource) -> KnowledgeSource:
        if source.key in self._sources:
            raise ValueError(f"source '{source.key}' is already loaded")
        source.load(self.client)
        self._sources[source.key] = source
        return source

    def source(self, key: str) -> KnowledgeSource:
        try:
            return self._sources[key]
        except KeyError:
            raise ValueError(
                f"no knowledge source '{key}' (loaded: {', '.join(self.keys()) or 'none'})"
            ) from None

    def keys(self) -> list[str]:
        return list(self._sources)

    def describe(self) -> str:
        return "\n".join(s.describe() for s in self._sources.values())
