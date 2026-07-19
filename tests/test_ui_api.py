import json
import unittest
from unittest.mock import patch

from plct_server.endpoints.ui_api import ChatInput, stream_response


class FakeAiEngine:
    async def generate_answer(self, **kwargs):
        progress_callback = kwargs["progress_callback"]
        await progress_callback("classifying")
        await progress_callback("retrieving")

        async def answer():
            yield "Prvi\nred"

        return answer(), ["Sledeće pitanje?"], None

    async def generate_condensed_history(self, **kwargs):
        return "Sažetak"


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
            ["progress", "progress", "progress", "metadata", "progress", "content", "done"],
        )
        self.assertEqual(events[3]["condensed_history"], "Sažetak")
        self.assertEqual(events[5]["text"], "Prvi\nred")


if __name__ == "__main__":
    unittest.main()