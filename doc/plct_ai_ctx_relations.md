# PLCT-AI-Ctx → PLCT-Server

What the course knowledge source hands this repo, and what this repo has to do with it.

PLCT-AI-Ctx (`../net-kabinet/PLCT-AI-Ctx`) is **build-time only**. It produces one artifact —
the `ai-context/` dataset — and PLCT-Server consumes it at startup. Nothing at runtime calls
back into it.

For the runtime that consumes this, see [ai_flow.md](ai_flow.md).

---

## 1. The offer: the `ai-context/` dataset

`plct-ai-ctx-build` walks PLCT course projects and writes the dataset that `ContextDataset`
reads. Layout:

```text
ai-context/
  index.json                          # { courses: [...], emb_types: [...] }
  <course_key>/
    summary.json                      # CourseSummary: title, summary path, toc path, activities{}
    summaries/course-summary.txt
    summaries/course-toc.txt
    summaries/<activity>.txt
  chunks/<hh>/<sha256>.txt            # chunk text
  chunks/<hh>/<sha256>.json           # ChunkMetadata
  chunks/<hh>/<sha256>-<model>-<size>.json
  emb-<model>-<size>.json.zst         # { ids, embeddings, metadatas } — the startup payload
```

`ChunkMetadata` is `course_key`, `activity_key`, `course_title`, `lesson_title`,
`activity_title` — these are exactly the fields available as Chroma filters, and therefore
exactly the scoping the retrieval tools can express.

Chunking is **fixed-size with overlap** (`chunk_size: 3072`, `chunk_overlap: 1524` in the sample
config) via `langchain-experimental`. Chunk identity is `sha256(course_key + "\n" + text)`, which
makes rebuilds incremental: unchanged text keeps its hash and its cached embedding.

## 2. The dependency direction

The writer half, `ContextDatasetBuilder`, lives in **this** repo
([context_dataset.py:36](../plct_server/ai/context_dataset.py#L36)) — PLCT-AI-Ctx depends on
PLCT-Server, not the other way around. A change to the dataset format is therefore a change
in this repo first, and the build repo picks it up on its next release.

## 3. How the server takes delivery

| | |
| --- | --- |
| Configured by | `ai_ctx_url` — a local path **or an HTTP base URL** (Azure Blob in production), plus a `knowledge_sources` entry of `type: plct-ai-ctx` |
| Read through | [`FileSet`](../plct_server/content/fileset.py#L20), which is what makes the HTTP case work at all |
| Loaded into | its own Chroma collection, `text-embedding-3-large` @ 1536, **inner product** over normalised vectors |
| Mirrored to | `<knowledge_cache_dir>/<source-key>-<url-hash>/`, from which chunk text is read per hit |
| Reached by | the `search_course` and `search_platform_docs` tools (the latter is the same class scoped to `course_key = "petlja-docs"`) |
| Cutoff | `max_distance` **0.45** — calibrated on this embedding model and this corpus; it does not transfer to a bundle |

The mirror is also why chunk text matches the dataset's own hashes: the files were written on
Windows with CRLF, and a local read translates them back to LF, while an HTTP read does not.

## 4. What the server has to reconstruct

The dataset records neither **document order** nor **lessons**, and both are needed to hand the
model a page rather than a scatter of chunks. [`course_db`](../plct_server/knowledge/course_db.py)
sits on top of the *same* loaded collection and recovers them. It is a library module with no
CLI and no mirror of its own.

- **Document order** — chunk ids are content hashes and the payload is written in hash order, so
  order is recovered by locating and verifying the build-time chunk overlap
  ([chunk_order.py](../plct_server/knowledge/chunk_order.py)). This is only possible *because*
  chunking is fixed-size with a known overlap; a change to `chunk_overlap` upstream lands here.
- **Lessons** — a lesson exists only as a `lesson_title` repeated across the chunk metadata of
  consecutive activities, so it is inferred as a run.

Measured corpus-wide: 2215 activities, 360 reconstructed, 1854 single-chunk, 1 genuinely
unorderable; 487 lesson runs, and no course where a title appears in two separate runs.

The overlap that order recovery keys on is also stripped when a hit is widened to its whole
page — see [ai_flow.md §6.4](ai_flow.md).

## 5. What flows from the shape of this corpus

Two runtime constants are calibrated against this dataset specifically, and are not portable
to another source:

- The median activity is a **single chunk**, which is why the page-in-prompt cap
  (`CONTEXT_MAX_CHUNKS` = 3) bounds only the tail and costs ~3,000 tokens at the median.
- 26 pages (1.2%) are too large to deliver whole — runs of unrelated algorithmic exercise
  tasks, up to 53 chunks, concentrated in seven specialist courses. They are the reason the
  excerpt path exists.

Both calibrations are tabulated in [ai_flow.md §6.4](ai_flow.md).

## 6. If the dataset changes

| Change upstream | Consequence here |
| --- | --- |
| `chunk_overlap` or chunker | `course_db` order recovery has to be re-verified against the corpus |
| A `ChunkMetadata` field | The set of expressible Chroma filters changes — that is the scoping vocabulary of `search_course` |
| Embedding model or dimensions | A new collection: `max_distance` must be recalibrated, since the scale does not carry across models |
| Layout under `ai-context/` | `ContextDatasetBuilder` in this repo is the format's definition; change it here first |
