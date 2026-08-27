"""The knowledge layer over tiny on-disk fixtures: no network, no API key.

Both source types are built from a handful of records, so these tests exercise loading,
collection isolation, metadata filtering and text reads without touching blob storage.
"""

import json
import tempfile
import unittest
from pathlib import Path

import zstandard as zstd

from plct_server.knowledge import build_store, resolve_sources, sync, verify
from plct_server.knowledge.config import SourceSpec
from plct_server.knowledge.store import KnowledgeStore, source_for
from plct_server.knowledge.chunk_order import fuse, reconstruct
from plct_server.knowledge.sync import _safe_rel


def make_course_dataset(root: Path) -> None:
    """A minimal PLCT-AI-Ctx dataset: one course, two chunks."""
    course_key = "test-course"
    chunks = {
        "aa" + "0" * 62: ("Rekurzija je kada funkcija poziva samu sebe.", [1.0, 0.0, 0.0, 0.0]),
        "bb" + "1" * 62: ("Petlja se ponavlja dok je uslov tacan.", [0.0, 1.0, 0.0, 0.0]),
    }
    (root / course_key / "summaries").mkdir(parents=True)
    (root / course_key / "summaries" / "course-summary.txt").write_text(
        "Kurs o programiranju", encoding="utf-8")
    (root / course_key / "summaries" / "course-toc.txt").write_text(
        "Section: Uvod\n  Rekurzija", encoding="utf-8")
    (root / course_key / "summaries" / "a1.txt").write_text("Sazetak", encoding="utf-8")
    (root / course_key / "summary.json").write_text(json.dumps({
        "course_key": course_key, "title": "Test kurs",
        "summary_text_path": "summaries/course-summary.txt",
        "toc_text_path": "summaries/course-toc.txt",
        "activities": {"act-1": {"title": "Rekurzija",
                                 "summary_text_path": "summaries/a1.txt"}},
    }), encoding="utf-8")
    (root / "index.json").write_text(json.dumps({
        "courses": [course_key], "emb_types": ["text-embedding-3-large-1536"]}),
        encoding="utf-8")

    metadatas = []
    for chunk_hash, (text, _) in chunks.items():
        path = root / "chunks" / chunk_hash[:2] / f"{chunk_hash}.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        metadatas.append({"course_key": course_key, "activity_key": "act-1",
                          "course_title": "Test kurs", "lesson_title": "Uvod",
                          "activity_title": "Rekurzija"})
    payload = {"ids": list(chunks),
               "embeddings": [v for _, v in chunks.values()],
               "metadatas": metadatas}
    with zstd.open(root / "emb-text-embedding-3-large-1536.json.zst", "wt",
                   encoding="utf-8") as f:
        f.write(json.dumps(payload))


def make_bundle(root: Path) -> None:
    """A minimal AI-Knowledge-Tools bundle: one concept, two chunks, 4-dim vectors."""
    (root / "chunks").mkdir(parents=True)
    (root / "chunks" / "0001.md").write_text("Formative assessment guides teaching.",
                                             encoding="utf-8")
    (root / "chunks" / "0002.md").write_text("Group work builds collaboration.",
                                             encoding="utf-8")
    (root / "chunks" / "0001.json").write_text("{}", encoding="utf-8")
    (root / "chunks" / "0002.json").write_text("{}", encoding="utf-8")
    (root / "manifest.json").write_text(json.dumps({
        "schema_version": 1, "artifact_type": "vector_index_data",
        "knowledge_unit": "Test-Unit", "embedding_model": "text-embedding-3-small",
        "embedding_dimensions": 4, "records_file": "records.jsonl",
        "chunks_directory": "chunks",
        "counts": {"concepts": 1, "chunks": 2, "records": 3},
    }), encoding="utf-8")
    records = [
        {"id": "concept:1", "kind": "concept", "embedding": [1.0, 0.0, 0.0, 0.0],
         "metadata": {"name": "Formative assessment", "description": "Assessment for learning.",
                      "aliases": []}},
        {"id": "Test-Unit:0001", "kind": "chunk", "embedding": [0.9, 0.1, 0.0, 0.0],
         "metadata": {"title": "Assessment", "ordinal": 1, "heading_path": ["Assessment"],
                      "token_count": 6, "text_file": "chunks/0001.md",
                      "chunk_file": "chunks/0001.json",
                      "concepts": [{"id": "concept:1", "name": "Formative assessment",
                                    "confidence": 0.9}]}},
        {"id": "Test-Unit:0002", "kind": "chunk", "embedding": [0.0, 0.0, 1.0, 0.0],
         "metadata": {"title": "Group work", "ordinal": 2, "heading_path": ["Methods"],
                      "token_count": 5, "text_file": "chunks/0002.md",
                      "chunk_file": "chunks/0002.json",
                      "concepts": [{"id": "concept:1", "name": "Formative assessment",
                                    "confidence": 0.4}]}},
    ]
    (root / "records.jsonl").write_text(
        "\n".join(json.dumps(r) for r in records), encoding="utf-8")


class KnowledgeFixture(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.course_root = base / "courses"
        self.bundle_root = base / "handbook"
        self.course_root.mkdir()
        self.bundle_root.mkdir()
        make_course_dataset(self.course_root)
        make_bundle(self.bundle_root)
        self.course_spec = SourceSpec(key="courses", type="plct-ai-ctx",
                                      url=str(self.course_root))
        self.bundle_spec = SourceSpec(key="handbook", type="aikt-bundle",
                                      url=str(self.bundle_root))
        self.store = None

    def tearDown(self):
        # The in-memory Chroma client is shared across the process; drop what we made.
        if self.store is not None:
            for key in self.store.keys():
                self.store.client.delete_collection(self.store.source(key).collection_name)
        self._tmp.cleanup()

    def build(self) -> KnowledgeStore:
        self.store = build_store([self.course_spec, self.bundle_spec], "unused",
                                 do_sync=True)
        return self.store


class StoreTests(KnowledgeFixture):
    def test_each_source_gets_its_own_collection(self):
        store = self.build()
        courses, handbook = store.source("courses"), store.source("handbook")
        self.assertEqual(courses.collection_name, "courses-text-embedding-3-large-1536")
        self.assertEqual(handbook.collection_name, "handbook-text-embedding-3-small-4")
        self.assertEqual((courses.distance, handbook.distance), ("ip", "cosine"))
        self.assertEqual(courses.collection.count(), 2)
        self.assertEqual(handbook.collection.count(), 3)

    def test_sources_never_leak_into_each_other(self):
        store = self.build()
        course_ids = {h.id for h in store.source("courses").search([1.0, 0, 0, 0], k=5)}
        handbook_ids = {h.id for h in store.source("handbook").search([1.0, 0, 0, 0], k=5)}
        self.assertTrue(course_ids)
        self.assertTrue(handbook_ids)
        self.assertFalse(course_ids & handbook_ids)

    def test_hit_text_comes_off_disk(self):
        store = self.build()
        hit = store.source("courses").search([1.0, 0, 0, 0], k=1)[0]
        self.assertIn("Rekurzija", hit.text)
        self.assertEqual(hit.metadata["course_key"], "test-course")

        chunk = [h for h in store.source("handbook").search([0.9, 0.1, 0, 0], k=3)
                 if h.metadata.get("ordinal") == 1][0]
        self.assertIn("Formative assessment", chunk.text)
        concept = [h for h in store.source("handbook").search([1.0, 0, 0, 0], k=3)
                   if h.id.startswith("concept:")][0]
        self.assertEqual(concept.text, "Assessment for learning.")

    def test_metadata_filter_and_empty_k(self):
        store = self.build()
        courses = store.source("courses")
        self.assertEqual(len(courses.search([1.0, 0, 0, 0], k=5,
                                            where={"course_key": "test-course"})), 2)
        self.assertEqual(courses.search([1.0, 0, 0, 0], k=5,
                                        where={"course_key": "absent"}), [])
        self.assertEqual(courses.search([1.0, 0, 0, 0], k=0), [])

    def test_bundle_keeps_concept_assignments_ranked(self):
        store = self.build()
        handbook = store.source("handbook")
        self.assertEqual(handbook.concept_chunks["concept:1"],
                         ["Test-Unit:0001", "Test-Unit:0002"])
        self.assertEqual(handbook.concept_names, ["Formative assessment"])

    def test_unknown_source_names_what_is_loaded(self):
        store = self.build()
        with self.assertRaises(ValueError) as caught:
            store.source("nope")
        self.assertIn("courses", str(caught.exception))

    def test_duplicate_source_is_refused(self):
        store = self.build()
        with self.assertRaises(ValueError):
            store.add(source_for(self.course_spec, self.course_root))


class SyncTests(KnowledgeFixture):
    def test_local_source_is_used_in_place(self):
        for spec, root in ((self.course_spec, self.course_root),
                           (self.bundle_spec, self.bundle_root)):
            self.assertEqual(sync(spec, "unused"), root)

    def test_local_source_without_entry_file_fails(self):
        (self.bundle_root / "manifest.json").unlink()
        with self.assertRaises(ValueError):
            sync(self.bundle_spec, "unused")

    def test_verify_accepts_a_complete_bundle(self):
        checked, problems = verify(self.bundle_spec, "unused")
        self.assertEqual((checked, problems), (2, []))

    def test_verify_reports_a_missing_payload(self):
        (self.bundle_root / "chunks" / "0002.md").unlink()
        _, problems = verify(self.bundle_spec, "unused")
        self.assertEqual(problems, ["chunks/0002.md missing"])

    def test_source_paths_cannot_escape_the_mirror(self):
        for value in ("../secret.md", "/etc/passwd", "a/../../b.md"):
            with self.assertRaises(ValueError):
                _safe_rel(value, "text_file")


class ConfigTests(unittest.TestCase):
    class Conf:
        def __init__(self, **kwargs):
            self.knowledge_sources = []
            self.__dict__.update(kwargs)

    def test_configured_sources_are_returned_in_order(self):
        conf = self.Conf(knowledge_sources=[
            SourceSpec(key="courses", type="plct-ai-ctx", url="https://example.com/ctx/"),
            SourceSpec(key="handbook", type="aikt-bundle", url="https://example.com/b/")])
        self.assertEqual([s.key for s in resolve_sources(conf)], ["courses", "handbook"])

    def test_no_sources_is_not_an_error(self):
        self.assertEqual(resolve_sources(self.Conf()), [])

    def test_disabled_sources_are_skipped(self):
        conf = self.Conf(knowledge_sources=[
            SourceSpec(key="a", type="aikt-bundle", url="u", enabled=False),
            SourceSpec(key="b", type="aikt-bundle", url="u")])
        self.assertEqual([s.key for s in resolve_sources(conf)], ["b"])

    def test_duplicate_keys_are_refused(self):
        conf = self.Conf(knowledge_sources=[
            SourceSpec(key="a", type="aikt-bundle", url="u"),
            SourceSpec(key="a", type="plct-ai-ctx", url="u")])
        with self.assertRaises(ValueError):
            resolve_sources(conf)

    def test_keys_have_to_be_collection_safe(self):
        for key in ("has space", "-leading", "trailing-", "", "a" * 41):
            with self.assertRaises(ValueError):
                SourceSpec(key=key, type="aikt-bundle", url="u")


if __name__ == "__main__":
    unittest.main()


class FuseTests(unittest.TestCase):
    """`fuse` groups chunks into the runs that actually chain.

    `reconstruct` is all-or-nothing on purpose -- it rebuilds one whole activity and should
    not guess an order it cannot verify. That is the wrong answer for a handful of chunks
    pulled out of a big page by a query, where neighbours share ~1,524 tokens and would
    otherwise be handed over twice.
    """

    OVERLAP = "Rekurzija je kada funkcija poziva samu sebe. " * 40

    def test_a_fully_chaining_set_is_one_run_identical_to_reconstruct(self):
        chunks = {"a": "POCETAK. " + self.OVERLAP, "b": self.OVERLAP + "KRAJ."}
        runs = fuse(chunks)

        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0].text, reconstruct(chunks).text)
        self.assertTrue(runs[0].ordered)

    def test_an_adjacent_pair_beside_an_unrelated_chunk_fuses_only_the_pair(self):
        chunks = {"a": "POCETAK. " + self.OVERLAP,
                  "b": self.OVERLAP + "KRAJ.",
                  "z": "Sasvim drugi zadatak, bez ikakvog preklapanja. " * 30}
        runs = fuse(chunks)

        texts = sorted((r.text for r in runs), key=len)
        self.assertEqual(len(runs), 2)
        self.assertTrue(texts[1].startswith("POCETAK."))
        self.assertTrue(texts[1].endswith("KRAJ."))
        # The shared overlap is carried once across the fused pair.
        self.assertEqual(len(texts[1]),
                         len(chunks["a"]) + len(chunks["b"]) - len(self.OVERLAP))
        self.assertEqual(texts[0], chunks["z"])

    def test_chunks_that_share_nothing_stay_separate(self):
        chunks = {f"id{i}": f"Zadatak broj {i}. " * 30 for i in range(3)}
        runs = fuse(chunks)

        self.assertEqual(len(runs), 3)
        self.assertEqual(sorted(r.text for r in runs), sorted(chunks.values()))

    def test_a_single_chunk_and_an_empty_set(self):
        self.assertEqual(fuse({"a": "tekst"})[0].text, "tekst")
        self.assertEqual(fuse({})[0].text, "")
