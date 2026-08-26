"""Token counting and per-source embedders.

No network and no API key. What is exercised here is the bookkeeping around a request
rather than the request: which tiktoken encoding a model is counted with, and whether a
query vector is built for the index it will be searched against. Both used to be single
module constants from when the server had one knowledge source and one embedder.
"""

import unittest

import tiktoken

from plct_server.ai import engine
from plct_server.ai.engine import AiEngine
from plct_server.ai.model_conf import ModelConfig, ModelProvider
from plct_server.ai.query_context import QueryError
from plct_server.knowledge.store import KnowledgeSource


SERBIAN = ("Ученици треба да разумеју појам променљиве пре него што пређу на петље. "
           "Наставник најпре показује пример, затим ученици самостално решавају задатак. ")


# --------------------------------------------------------------------------- fakes


class FakeSource:
    def __init__(self, key, model, dimensions):
        self.key = key
        self.embedding_model = model
        self.embedding_dimensions = dimensions

    query_embedder = KnowledgeSource.query_embedder


class FakeEmbeddings:
    def __init__(self):
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        raise AssertionError("the guard should have fired before the API call")


class FakeClient:
    def __init__(self):
        self.embeddings = FakeEmbeddings()


def bare_engine():
    """An AiEngine with only the token bookkeeping wired up.

    `__init__` mirrors and indexes a corpus; none of that is what these tests are about.
    """
    ai = object.__new__(AiEngine)
    ai._encodings = {}
    ai.fallback_encoding = tiktoken.get_encoding(engine.FALLBACK_ENCODING)
    ai.client_factory = None
    return ai


# --------------------------------------------------------------------------- tests


class EncodingTests(unittest.TestCase):
    """The premise: the two encodings are not interchangeable on this corpus."""

    def test_cyrillic_costs_far_more_in_cl100k_than_in_o200k(self):
        text = SERBIAN * 100
        cl100k = len(tiktoken.get_encoding("cl100k_base").encode(text))
        o200k = len(tiktoken.get_encoding("o200k_base").encode(text))

        self.assertGreater(cl100k, o200k * 1.4)
        self.assertLess(o200k, 8191)
        self.assertGreater(cl100k, 8191)

    def test_a_model_is_counted_with_its_own_encoding(self):
        ai = bare_engine()
        embedding = ModelConfig(name="text-embedding-3-large", type="embedding",
                                context_size=8_191, encoding="cl100k_base")
        chat = ModelConfig(name="gpt-4o-mini", type="chat", context_size=128_000,
                           encoding="o200k_base")

        self.assertEqual(ai._encoding_for(embedding).name, "cl100k_base")
        self.assertEqual(ai._encoding_for(chat).name, "o200k_base")
        self.assertGreater(ai.count_tokens(SERBIAN, ai._encoding_for(embedding)),
                           ai.count_tokens(SERBIAN, ai._encoding_for(chat)))

    def test_a_model_tiktoken_does_not_know_falls_back(self):
        ai = bare_engine()
        vllm = ModelConfig(name="Qwen/Qwen3-8B", provider=ModelProvider.VLLM, type="chat",
                           context_size=32_768)

        self.assertIsNone(vllm.encoding)
        self.assertEqual(ai._encoding_for(vllm).name, engine.FALLBACK_ENCODING)

    def test_the_encoding_is_loaded_once_per_name(self):
        ai = bare_engine()
        config = ModelConfig(name="m", type="chat", context_size=1, encoding="cl100k_base")

        self.assertIs(ai._encoding_for(config), ai._encoding_for(config))


class EmbeddingGuardTests(unittest.IsolatedAsyncioTestCase):
    async def test_oversized_cyrillic_is_refused_before_the_api_call(self):
        """The regression test: 5k tokens by the chat encoding, 8.4k by the real one.

        Counted with o200k_base this input reads as comfortably inside the 8191-token
        limit, so the guard waves it through and OpenAI answers with a 400.
        """
        ai = bare_engine()
        config = ModelConfig(name="text-embedding-3-large", type="embedding",
                             context_size=8_191, encoding="cl100k_base")
        ai._model_config_dict = {config.name: config}
        client = FakeClient()
        ai._get_async_openai_client = lambda requested_model: client

        with self.assertRaises(QueryError):
            await ai._create_embedding(SERBIAN * 100, model=config.name, dimensions=1536)

        self.assertEqual(client.embeddings.calls, [])

    async def test_the_model_and_dimensions_are_required(self):
        """No defaults to fall back on -- the caller states which index it is searching."""
        ai = bare_engine()
        with self.assertRaises(TypeError):
            await ai._create_embedding("pitanje")


class SourceEmbedderTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_source_binds_its_own_model_and_dimensions(self):
        calls = []

        async def embed(text, *, model, dimensions):
            calls.append((text, model, dimensions))
            return [0.0] * dimensions

        courses = FakeSource("courses", "text-embedding-3-large", 1536)
        handbook = FakeSource("handbook", "text-embedding-3-small", 1536)

        await courses.query_embedder(embed)("pitanje")
        await handbook.query_embedder(embed)("pitanje")

        self.assertEqual(calls, [("pitanje", "text-embedding-3-large", 1536),
                                 ("pitanje", "text-embedding-3-small", 1536)])


if __name__ == "__main__":
    unittest.main()
