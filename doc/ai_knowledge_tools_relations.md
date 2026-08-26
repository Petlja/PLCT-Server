# AI-Knowledge-Tools → PLCT-Server

What the AIKT repo offers this one, what this repo takes, and what it deliberately leaves.

AI-Knowledge-Tools (`../AI-Knowledge-Tools`) is a separate, product-neutral pipeline **plus** a
reusable retrieval/answering library. It offers two things, and PLCT-Server accepts them on
different terms: the **bundle** is loaded as data, and the **library** is read as a design and
re-implemented rather than imported.

For the runtime that consumes this, see [ai_flow.md](ai_flow.md).

---

## 1. The pipeline and its artifact

```text
aikt ingest          DOCX → data/ingested/<unit>.md  (+ _media/, _interim/)
aikt cnpt-extract    <unit>.md → <unit>_concepts.json     # canonical concept inventory, UUIDv5 ids
aikt semantic-chunk  <unit>.md + concepts → <unit>_chunks.json
aikt index           concepts + chunks → data/index/<unit>/
aikt retrieve        inspect the bundle
aikt ask             answer a question through the tool loop
```

The prepared bundle — the only part PLCT-Server consumes:

```text
data/index/<unit>/
  manifest.json       # embedding_model, embedding_dimensions, counts, source paths
  records.jsonl       # one line per vector record: {id, kind: concept|chunk, embedding, metadata}
  chunks/0001.json    # chunk metadata, neighbour links, no text
  chunks/0001.md      # verbatim chunk text
```

Real reference bundle (`Handbook-for-Teachers`): 146 concepts, 122 chunks, 268 records,
`text-embedding-3-small` @ 1536 dims, **8.1 MB `records.jsonl`**.

Two properties of the bundle are what make it worth consuming:

- **Source-preserving chunking.** Concatenating chunk texts in ordinal order reproduces the source
  byte for byte. Chunks carry `heading_path`, `content_type`, `token_count`, source line range,
  and `previous/next_chunk_id` — so a neighbour is `ordinal ± 1`. Unlike the course dataset,
  nothing has to be reconstructed: order is recorded.
- **A concept layer.** Concepts are vectors too. A concept hit can be *inverted* to the chunks
  assigned to it, which is a second retrieval path that fixed-size chunking has no equivalent of.

## 2. How the server takes delivery

| | |
| --- | --- |
| Configured by | a `knowledge_sources` entry of `type: aikt-bundle` |
| Loaded into | its own Chroma collection at whatever the manifest records — `text-embedding-3-small` @ 1536, **cosine**, for the reference bundle |
| Mirrored to | `<knowledge_cache_dir>/<source-key>-<url-hash>/`; chunk `.md` read per hit |
| Reached by | one tool per bundle — `consult_teaching_literature` for `Handbook-for-Teachers` |
| Cutoffs | `max_chunk_distance` and `max_concept_distance`, both **0.46**; two populations, because a concept vector is a short name and sits nearer any question by construction |

**A bundle is bound to its tool by `knowledge_unit`, the name its manifest declares.** AIKT
prepares knowledge and does not describe it, so the tool name, description and citation label
are authored in this repo, in `BUNDLE_TOOLS`
([knowledge_tools.py](../plct_server/ai/tools/knowledge_tools.py)), beside the sibling tools the
description competes with for the model's routing decision. A loaded bundle that no tool offers
**raises at startup** — see [ai_flow.md §6.2](ai_flow.md) for why, and for the one-bundle-one-tool
rule.

## 3. The library on offer

| Function / class | Role | Notes |
| --- | --- | --- |
| `build_index_session` | loads a bundle into an ephemeral Chroma collection | **accepts an injected `chroma_client`**; issues no embedding request, so it works without an API key |
| `IndexSession` | the loaded bundle: manifest, `records_by_id`, collection, lazy `_lookups` | collection name is `aikt-retrieval-<uuid4>` — several sessions can share one client |
| `query_index_session` | embeds one query, searches, returns ranked hits | **accepts an injected `embeddings_create`**; cosine distance; `where={"kind": ...}` |
| `session_catalog`, `session_chunk`, `session_concept_chunk_ids`, `read_chunk_text` | deterministic lookups over loaded records | no requests |
| `KnowledgeBaseTool` | the `query_knowledge_base` tool | self-describing: its `description` embeds the full concept list and tells the model which language to query in |
| `answer_question` | the local tool loop that exercises it | seeds evidence, bounded rounds, strict JSON answer schema |

`KnowledgeBaseTool` owns an **evidence ledger**: chunk text is deduplicated across every call and
bounded by `max_evidence_tokens` using the `token_count` metadata. Already-delivered chunks come
back as `{"status": "already_provided"}` instead of repeated text. Adjacent ordinals are merged
into one passage before returning. Recoverable problems (empty retrieval, budget exhausted) are
returned to the model **as tool data, not raised**.

The tool takes `questions: string[]` — a batch — so one round can gather evidence for several
subtopics with cross-question deduplication.

**This is the design PLCT-Server's whole tool layer follows.** The `questions: string[]`-only
parameter shape, the per-request ledger, the recoverable-problems-as-data rule and the
adjacent-passage merge are all AIKT's, applied to the course tools as well as to the bundle tool.

## 4. Why the tool is ported, not imported

The retrieval strategy — kNN over chunks *and* concepts, concept→chunk expansion,
adjacent-ordinal merge — lives in
[ai/tools/knowledge_tools.py](../plct_server/ai/tools/knowledge_tools.py) over `BundleSource`,
which already holds the records, the confidence-ranked concept index and the chunk text.
Importing the class would have meant loading each bundle a second time into its own
`IndexSession` and calling a blocking embedding path from the event loop.

| | PLCT-Server | AI-Knowledge-Tools |
| --- | --- | --- |
| Concurrency | async throughout (`AsyncOpenAI`, FastAPI streaming) | synchronous (`OpenAI().embeddings.create`, `.responses.create`) |
| Model API | Chat Completions, streamed | Responses API, non-streamed |
| Tool definition shape | `{"type":"function","function":{...}}` | `{"type":"function","name":...}` (Responses flat form) |
| Provider | OpenAI / Azure / vLLM via `AiClientFactory` | OpenAI only, unless a callable is injected |
| Vector distance | inner product (`ip`) | cosine |
| Embedding model | per source: the course dataset at `text-embedding-3-large` @ 1536, each bundle at whatever its manifest records | whatever the manifest records (`text-embedding-3-small` @ 1536 in the reference bundle) |
| Storage access | `FileSet` — local **or HTTP** | `pathlib.Path` — **local filesystem only** |
| Text residency | chunk text fetched per hit, over HTTP | chunk `.md` read from disk per hit |
| Retrieval control | model asks natural-language questions and iterates | model asks natural-language questions and iterates |

### The `dimensions` gap

`query_index_session` validates the returned embedding length against the manifest but never
sends `dimensions` — so a `-large` bundle would be 3072-dim unless the injected callable supplies
`dimensions` itself. PLCT-Server's `_create_embedding` always sends both, and takes them from the
source being searched rather than from a default: `KnowledgeSource.query_embedder` binds a
source's model and width once, at tool construction, so a query vector cannot be built for an
index it does not match. The two sources loaded today share a width but not an embedder, so a
length check alone would not catch a mix-up between them.

Both `aikt index` and `query_index_session` accept an injected `embeddings_create`, so this is
controllable from the host without forking.

## 5. Open edges

- **The bundle assumes a local path.** `FileSet` is this repo's deployment contract and production
  reads over HTTPS from blob storage; AIKT's own loader does not. The mirror step is what bridges
  it today.
- **The description is authored here, the knowledge upstream.** Re-measuring tool routing after a
  bundle changes is a PLCT-Server job — `plct-batch-review` is the net.
- **Adding a second bundle means adding a `BUNDLE_TOOLS` entry**, not widening an existing tool.
