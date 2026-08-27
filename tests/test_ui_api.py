import json
import logging
import unittest
from unittest.mock import patch

from plct_server.ai import debug_stream
from plct_server.endpoints.ui_api import PROGRESS_MESSAGES, ChatInput, stream_response

PIPELINE_LOGGER = logging.getLogger("plct_server.ai.engine")


class FakeAiEngine:
    async def generate_answer(self, **kwargs):
        progress_callback = kwargs["progress_callback"]
        await progress_callback("preparing_answer")
        PIPELINE_LOGGER.info("tool round %d/%d: %d call(s)", 1, 4, 2)
        await progress_callback("retrieving", "search_course")

        async def answer():
            PIPELINE_LOGGER.info("answered in 1 tool round(s)")
            yield "Prvi\nred"

        return answer(), None


class StreamResponseTests(unittest.IsolatedAsyncioTestCase):

    async def events(self, *, debug=False):
        """Every event one question streams, with the engine and the config stood in for.

        The patches have to stay up while the stream is consumed: `stream_response` is a
        generator, so nothing at all runs until it is iterated.
        """
        chat_input = ChatInput(
            question="Pitanje",
            model="model",
            contextAttributes={"course_key": "course", "activity_key": "activity"},
        )
        with patch("plct_server.endpoints.ui_api.get_ai_engine",
                   return_value=FakeAiEngine()), \
             patch("plct_server.endpoints.ui_api.debug_mode_enabled",
                   return_value=debug):
            chunks = [chunk async for chunk in stream_response(chat_input)]
        self.assertTrue(all(chunk.endswith(b"\n") for chunk in chunks))
        return [json.loads(chunk) for chunk in chunks]

    async def test_streams_typed_ndjson_events_in_order(self):
        events = await self.events()

        self.assertEqual(
            [event["type"] for event in events],
            ["progress", "progress", "content", "done"],
        )
        self.assertEqual(events[1]["detail"], "search_course")
        self.assertNotIn("detail", events[0])
        self.assertEqual(events[2]["text"], "Prvi\nred")

    async def test_debug_mode_lifts_the_pipeline_loggers_to_info(self):
        """Nothing to tee otherwise: a server runs at WARNING unless told otherwise."""
        logging.getLogger("plct_server.ai").setLevel(logging.NOTSET)

        await self.events(debug=True)

        self.assertLessEqual(logging.getLogger("plct_server.ai").getEffectiveLevel(),
                             logging.INFO)

    async def test_pipeline_log_is_not_streamed_unless_debug_mode_is_on(self):
        events = await self.events()

        self.assertNotIn("debug", [event["type"] for event in events])

    async def test_debug_mode_streams_the_pipeline_log_alongside_the_answer(self):
        events = await self.events(debug=True)

        self.assertEqual(
            [event["type"] for event in events],
            ["debug", "progress", "debug", "debug", "progress", "debug",
             "content", "done"],
            "records are teed where they happen, in among the answer's own events")
        traced = [event for event in events if event["type"] == "debug"]
        self.assertEqual(
            [event["message"] for event in traced],
            ["progress -> Pripremam odgovor...",
             "tool round 1/4: 2 call(s)",
             "progress -> Tražim relevantne delove sadržaja... [search_course]",
             "answered in 1 tool round(s)"])
        self.assertEqual([event["source"] for event in traced],
                         ["ui", "ai.engine", "ui", "ai.engine"])
        self.assertEqual({event["level"] for event in traced}, {"INFO"})
        self.assertTrue(all(isinstance(event["elapsed"], float) for event in traced))

    async def test_capture_does_not_outlive_the_request_that_bound_it(self):
        await self.events(debug=True)
        self.assertIsNone(debug_stream._trace.get())

        PIPELINE_LOGGER.info("a record logged with nothing listening must be harmless")

    async def test_every_published_stage_has_a_message(self):
        """The stage set is a wire contract: publishing one that is absent raises."""
        self.assertEqual(set(PROGRESS_MESSAGES), {"preparing_answer", "retrieving"})


if __name__ == "__main__":
    unittest.main()
