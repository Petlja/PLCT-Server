import json
import unittest
from unittest.mock import patch

from plct_server.endpoints.ui_api import PROGRESS_MESSAGES, ChatInput, stream_response


class FakeAiEngine:
    async def generate_answer(self, **kwargs):
        progress_callback = kwargs["progress_callback"]
        await progress_callback("preparing_answer")
        await progress_callback("retrieving", "search_course")

        async def answer():
            yield "Prvi\nred"

        return answer(), None


class StreamResponseTests(unittest.IsolatedAsyncioTestCase):
    async def test_streams_typed_ndjson_events_in_order(self):
        chat_input = ChatInput(
            question="Pitanje",
            model="model",
            contextAttributes={"course_key": "course", "activity_key": "activity"},
        )

        with patch("plct_server.endpoints.ui_api.get_ai_engine", return_value=FakeAiEngine()):
            chunks = [chunk async for chunk in stream_response(chat_input)]

        self.assertTrue(all(chunk.endswith(b"\n") for chunk in chunks))
        events = [json.loads(chunk) for chunk in chunks]
        self.assertEqual(
            [event["type"] for event in events],
            ["progress", "progress", "content", "done"],
        )
        self.assertEqual(events[1]["detail"], "search_course")
        self.assertNotIn("detail", events[0])
        self.assertEqual(events[2]["text"], "Prvi\nred")

    async def test_every_published_stage_has_a_message(self):
        """The stage set is a wire contract: publishing one that is absent raises."""
        self.assertEqual(set(PROGRESS_MESSAGES), {"preparing_answer", "retrieving"})


if __name__ == "__main__":
    unittest.main()
