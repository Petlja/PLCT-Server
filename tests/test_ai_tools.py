"""The answering harness's own logic: the ledger, the loop, and script detection.

No network and no API key. The loop is exercised against a fake completion that emits the
same shape the OpenAI stream does -- tool calls arriving as fragments across chunks -- which
is the part most likely to break silently, because a half-assembled call still looks like a
call.
"""

import unittest

from plct_server.ai.language import CYRILLIC, LATIN, dominant_script
from plct_server.ai.tools import course_tools, knowledge_tools, page_context
from plct_server.ai.tools.evidence import Evidence
from plct_server.ai.tools.loop import ToolLoop
from plct_server.knowledge.chunk_order import chunks_to_tokens, fuse, reconstruct


# --------------------------------------------------------------------------- fakes


class Fragment:
    """One streamed tool-call fragment, shaped like the SDK's delta objects."""

    class _Function:
        def __init__(self, name, arguments):
            self.name = name
            self.arguments = arguments

    def __init__(self, index, id=None, name=None, arguments=None):
        self.index = index
        self.id = id
        self.function = self._Function(name, arguments)


class Delta:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls


class Chunk:
    class _Choice:
        def __init__(self, delta):
            self.delta = delta

    def __init__(self, delta):
        self.choices = [self._Choice(delta)]


def stream_of(deltas):
    async def generator():
        for delta in deltas:
            yield Chunk(delta)
    return generator()


class RecordingTool:
    def __init__(self, name="search_course", output=None):
        self.name = name
        self.definition = {"type": "function", "function": {"name": name}}
        self.output = output if output is not None else {"passages": []}
        self.calls = []

    async def run(self, arguments):
        self.calls.append(arguments)
        return self.output


# --------------------------------------------------------------------------- tests


class EvidenceTests(unittest.TestCase):
    def test_a_repeated_passage_comes_back_without_its_text(self):
        evidence = Evidence(max_tokens=1000, count_tokens=lambda t: len(t))
        first = evidence.deliver("a", "tekst lekcije", lesson="Rekurzija")
        second = evidence.deliver("a", "tekst lekcije", lesson="Rekurzija")

        self.assertEqual(first["text"], "tekst lekcije")
        self.assertNotIn("text", second)
        self.assertEqual(second["status"], "already_provided")
        # Labels ride along either way, so the model can tell which passage is meant.
        self.assertEqual(second["lesson"], "Rekurzija")
        self.assertEqual(len(evidence.delivered), 1)

    def test_the_first_passage_is_delivered_even_when_it_blows_the_budget(self):
        """Returning nothing at all reads as an empty knowledge base, not a spent budget."""
        evidence = Evidence(max_tokens=5, count_tokens=lambda t: len(t))
        first = evidence.deliver("a", "x" * 500)
        second = evidence.deliver("b", "y" * 500)

        self.assertIn("text", first)
        self.assertEqual(second["status"], "budget_exhausted")
        self.assertTrue(evidence.exhausted)

    def test_a_refused_passage_is_not_recorded_as_delivered(self):
        """It must stay available to a later, smaller call rather than reporting as sent."""
        evidence = Evidence(max_tokens=5, count_tokens=lambda t: len(t))
        evidence.deliver("a", "x" * 500)
        evidence.deliver("b", "y" * 500)

        self.assertFalse(evidence.holds("b"))

    def test_provenance_records_only_what_actually_went_out(self):
        evidence = Evidence(max_tokens=5, count_tokens=lambda t: len(t))
        evidence.deliver("a", "x" * 500, record={"activity_key": "act-1"})
        evidence.deliver("b", "y" * 500, record={"activity_key": "act-2"})

        self.assertEqual(evidence.provenance, [{"activity_key": "act-1"}])


class ToolLoopTests(unittest.IsolatedAsyncioTestCase):
    async def _run(self, loop):
        return "".join([delta async for delta in loop.stream(
            [{"role": "user", "content": "Pitanje"}])])

    async def test_a_turn_without_tool_calls_is_the_answer_and_is_streamed(self):
        async def complete(*, messages, tools, stream):
            return stream_of([Delta(content="Prvi "), Delta(content="red")])

        loop = ToolLoop(complete=complete, tools=[RecordingTool()])
        self.assertEqual(await self._run(loop), "Prvi red")
        self.assertEqual(loop.result.rounds, 0)

    async def test_tool_call_fragments_are_reassembled_across_chunks(self):
        tool = RecordingTool(output={"passages": [{"text": "gradivo"}]})
        turns = []

        async def complete(*, messages, tools, stream):
            turns.append(messages)
            if len(turns) == 1:
                # id and name arrive once, arguments a few characters at a time.
                return stream_of([
                    Delta(tool_calls=[Fragment(0, id="call_1", name="search_course")]),
                    Delta(tool_calls=[Fragment(0, arguments='{"questi')]),
                    Delta(tool_calls=[Fragment(0, arguments='ons": ["Sta')]),
                    Delta(tool_calls=[Fragment(0, arguments=' je rekurzija?"]}')]),
                ])
            return stream_of([Delta(content="Odgovor")])

        loop = ToolLoop(complete=complete, tools=[tool])
        self.assertEqual(await self._run(loop), "Odgovor")
        self.assertEqual(tool.calls, [{"questions": ["Sta je rekurzija?"]}])
        self.assertEqual(loop.result.rounds, 1)

        second = turns[1]
        self.assertEqual(second[-2]["tool_calls"][0]["id"], "call_1")
        self.assertEqual(second[-1]["role"], "tool")
        self.assertEqual(second[-1]["tool_call_id"], "call_1")

    async def test_parallel_calls_in_one_turn_count_as_one_round(self):
        """A turn costs one request however many calls it batches."""
        course = RecordingTool("search_course")
        handbook = RecordingTool("consult_teaching_literature")
        turns = []

        async def complete(*, messages, tools, stream):
            turns.append(messages)
            if len(turns) == 1:
                return stream_of([Delta(tool_calls=[
                    Fragment(0, id="a", name="search_course", arguments='{"questions":["x"]}'),
                    Fragment(1, id="b", name="consult_teaching_literature",
                             arguments='{"questions":["y"]}'),
                ])])
            return stream_of([Delta(content="Odgovor")])

        loop = ToolLoop(complete=complete, tools=[course, handbook])
        await self._run(loop)
        self.assertEqual(loop.result.rounds, 1)
        self.assertEqual(loop.result.calls, 2)
        self.assertEqual(course.calls, [{"questions": ["x"]}])
        self.assertEqual(handbook.calls, [{"questions": ["y"]}])

    async def test_tools_are_withheld_on_the_last_round_so_the_model_must_answer(self):
        offered = []

        async def complete(*, messages, tools, stream):
            offered.append(bool(tools))
            if tools:
                return stream_of([Delta(tool_calls=[
                    Fragment(0, id="a", name="search_course", arguments="{}")])])
            return stream_of([Delta(content="Odgovor")])

        loop = ToolLoop(complete=complete, tools=[RecordingTool()], max_rounds=2)
        self.assertEqual(await self._run(loop), "Odgovor")
        self.assertEqual(offered, [True, True, False])

    async def test_a_broken_call_is_reported_to_the_model_rather_than_raised(self):
        tool = RecordingTool()
        turns = []

        async def complete(*, messages, tools, stream):
            turns.append(messages)
            if len(turns) == 1:
                return stream_of([Delta(tool_calls=[
                    Fragment(0, id="a", name="search_course", arguments="{not json")])])
            return stream_of([Delta(content="Odgovor")])

        loop = ToolLoop(complete=complete, tools=[tool])
        self.assertEqual(await self._run(loop), "Odgovor")
        self.assertEqual(tool.calls, [])
        self.assertIn("valid JSON", turns[1][-1]["content"])

    async def test_an_unknown_tool_is_reported_rather_than_raised(self):
        turns = []

        async def complete(*, messages, tools, stream):
            turns.append(messages)
            if len(turns) == 1:
                return stream_of([Delta(tool_calls=[
                    Fragment(0, id="a", name="get_lecture", arguments="{}")])])
            return stream_of([Delta(content="Odgovor")])

        loop = ToolLoop(complete=complete, tools=[RecordingTool()])
        await self._run(loop)
        self.assertIn("Unknown tool", turns[1][-1]["content"])

    async def test_no_tools_means_a_single_turn(self):
        turns = []

        async def complete(*, messages, tools, stream):
            turns.append(tools)
            return stream_of([Delta(content="Odgovor")])

        loop = ToolLoop(complete=complete, tools=[])
        self.assertEqual(await self._run(loop), "Odgovor")
        self.assertEqual(turns, [None])


class ScriptTests(unittest.TestCase):
    def test_majority_not_presence(self):
        # The case the rule exists for: Latin-script Serbian quoting a Cyrillic title.
        self.assertEqual(
            dominant_script("Kako da objasnim lekciju Рекурзија ucenicima?"), LATIN)
        # ...and its mirror: a Cyrillic question naming a Python keyword.
        self.assertEqual(dominant_script("Шта ради ова Python for петља?"), CYRILLIC)

    def test_other_latin_languages_and_empty_input_fall_to_latin(self):
        self.assertEqual(dominant_script("¿Cómo explico la recursión?"), LATIN)
        self.assertEqual(dominant_script("How do I add a student?"), LATIN)
        self.assertEqual(dominant_script(""), LATIN)
        self.assertEqual(dominant_script("12345 ???"), LATIN)


class Hit:
    def __init__(self, id, distance, activity_key):
        self.id = id
        self.distance = distance
        self.metadata = {"activity_key": activity_key}


class FakeCourseSource:
    """Returns the hits it was given. `here_hits` answers the activity-filtered pass."""

    def __init__(self, hits):
        self.hits = hits
        self.here_hits = []

    def search(self, embedding, *, k, where):
        return (self.here_hits if "$and" in where else self.hits)[:k]


class FakeCourseDB:
    """The corpus as `chunks[activity_key] = {chunk_id: text}`, in document order."""

    def __init__(self, chunks):
        self.chunks = chunks

    def get_by_activity(self, course_key, activity_key):
        return dict.fromkeys(self.chunks.get(activity_key, {}), {})

    def _text(self, chunk_id):
        for activity in self.chunks.values():
            if chunk_id in activity:
                return activity[chunk_id]
        return None

    def runs(self, chunk_ids, *, whole=False):
        # The real ordering, over the fixture's text: these tests are about what the
        # tools do with the runs, not about how the runs are found.
        chunks = {i: text for i in chunk_ids if (text := self._text(i)) is not None}
        if not chunks:
            return []
        return [reconstruct(chunks)] if whole else fuse(chunks)

    def titles(self, course_key, activity_key):
        # Blanks keep these tests about grouping and budgeting, not about labelling.
        return "", ""


class CourseSearchToolTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    async def _embed(text):
        return [0.0]

    def _tool(self, chunks, *, activity_key="", **limits):
        """`chunks` is {activity_key: {chunk_id: text}}; every chunk is a hit, in order."""
        hits = [Hit(chunk_id, 0.30 + n / 100, activity_key)
                for n, (activity_key, activity) in enumerate(chunks.items())
                for chunk_id in activity]
        limits.setdefault("k", 50)
        return course_tools.CourseSearchTool(
            name="search_course", description="d", course_key="c",
            source=FakeCourseSource(hits), db=FakeCourseDB(chunks),
            embed=self._embed, evidence=Evidence(count_tokens=len),
            activity_key=activity_key, limits=course_tools.Limits(**limits))

    async def test_only_the_closest_activities_are_delivered_and_the_rest_are_named(self):
        """A hit delivers a whole page, so an uncapped call would spend the budget."""
        chunks = {f"act-{i}": {f"id{i}": f"tekst {i}"} for i in range(6)}
        tool = self._tool(chunks, max_activities=2)

        result = await tool.run({"questions": ["Sta je rekurzija?"]})

        self.assertEqual([p["text"] for p in result["passages"]], ["tekst 0", "tekst 1"])
        self.assertIn("4 further place(s)", result["note"])

    async def test_a_short_page_is_delivered_whole_even_from_a_single_hit(self):
        """95% of activities are three chunks or fewer, and half a lesson is worth little."""
        overlap = "Rekurzija je kada funkcija poziva samu sebe. " * 40
        first, second = "POCETAK. " + overlap, overlap + "KRAJ."
        tool = self._tool({"act-1": {"a": first, "b": second}})
        # Only the first chunk matches; the page is short, so the whole page comes back.
        tool.source.hits = [Hit("a", 0.30, "act-1")]

        result = await tool.run({"questions": ["Sta je rekurzija?"]})

        self.assertEqual(len(result["passages"]), 1)
        text = result["passages"][0]["text"]
        self.assertTrue(text.startswith("POCETAK."))
        self.assertTrue(text.endswith("KRAJ."))
        self.assertNotIn("excerpt", result["passages"][0])
        # The overlap the two chunks share is carried once, not twice.
        self.assertEqual(len(text), len(first) + len(second) - len(overlap))

    async def test_a_long_page_yields_only_the_chunks_that_matched(self):
        """The 53-chunk task pages: unrelated problems, so the matched ones are the answer.

        Each comes back as its own passage. Concatenating unrelated problems would present
        them as continuous text and make them one all-or-nothing charge on the budget.
        """
        page = {f"id{i}": f"zadatak {i}" for i in range(8)}
        tool = self._tool({"act-1": page}, whole_page_max_tokens=chunks_to_tokens(3))
        tool.source.hits = [Hit("id2", 0.30, "act-1"), Hit("id5", 0.31, "act-1")]

        result = await tool.run({"questions": ["Sta je rekurzija?"]})

        texts = [p["text"] for p in result["passages"]]
        self.assertEqual(texts, ["zadatak 2", "zadatak 5"])
        # Flagged as partial, so the model can ask again rather than assume it has the page.
        self.assertTrue(all(p["excerpt"] for p in result["passages"]))

    async def test_widening_stops_when_the_budget_will_not_hold_the_page(self):
        """Later pages fall back to their matched chunks instead of crowding out layer 2."""
        pages = {"act-1": {"a": "prvi " * 400, "b": "drugi " * 400},
                 "act-2": {"c": "treci " * 400, "d": "cetvrti " * 400}}
        tool = self._tool(pages)
        tool.evidence.max_tokens = 8000
        tool.source.hits = [Hit("a", 0.30, "act-1"), Hit("c", 0.31, "act-2")]

        result = await tool.run({"questions": ["Sta je rekurzija?"]})

        first, second = result["passages"]
        self.assertNotIn("excerpt", first)
        self.assertTrue(second["excerpt"])
        self.assertNotIn("cetvrti", second["text"])

    async def test_the_page_the_teacher_is_on_is_searched_and_never_dropped(self):
        """A big current page loses course-wide top-k, so it gets its own pass and a slot."""
        pages = {f"act-{i}": {f"id{i}": f"lekcija {i}"} for i in range(5)}
        pages["here"] = {f"h{i}": f"zadatak {i}" for i in range(20)}
        tool = self._tool(pages, activity_key="here", max_activities=2)
        tool.source.hits = [Hit(f"id{i}", 0.30 + i / 100, f"act-{i}") for i in range(5)]
        tool.source.here_hits = [Hit("h7", 0.90, "here"), Hit("h12", 0.91, "here")]

        result = await tool.run({"questions": ["Tehnika dva pokazivaca"]})

        first = result["passages"][0]
        self.assertEqual(first["text"], "zadatak 7")
        self.assertTrue(first["excerpt"])
        # Pinned first despite being the worst match, and only the matched tasks come back.
        self.assertNotIn("zadatak 0", [p.get("text") for p in result["passages"]])

    async def test_a_short_current_page_still_arrives_whole(self):
        """The extra pass must not turn an ordinary lesson into an excerpt."""
        tool = self._tool({"here": {"a": "prvi deo", "b": "drugi deo"}}, activity_key="here")
        tool.source.hits = []
        tool.source.here_hits = [Hit("a", 0.40, "here")]

        result = await tool.run({"questions": ["Sta je rekurzija?"]})

        self.assertEqual(len(result["passages"]), 1)
        self.assertNotIn("excerpt", result["passages"][0])
        self.assertIn("drugi deo", result["passages"][0]["text"])

    async def test_a_second_call_reports_what_the_model_already_has(self):
        tool = self._tool({"act-1": {"a": "tekst lekcije"}})

        first = await tool.run({"questions": ["Sta je rekurzija?"]})
        second = await tool.run({"questions": ["Sta je rekurzija?"]})

        self.assertIn("text", first["passages"][0])
        self.assertEqual(second["passages"], [])
        self.assertIn("already given to you", second["note"])

    async def test_a_hit_on_a_page_already_delivered_whole_is_not_re_sent(self):
        """The widening has to mark the whole page spent, not just the chunk that matched."""
        tool = self._tool({"act-1": {"a": "prvi deo", "b": "drugi deo"}})
        tool.source.hits = [Hit("a", 0.30, "act-1")]
        await tool.run({"questions": ["Sta je rekurzija?"]})

        tool.source.hits = [Hit("b", 0.30, "act-1")]
        second = await tool.run({"questions": ["A maksimum?"]})

        self.assertEqual(second["passages"], [])
        self.assertIn("already given to you", second["note"])

    async def test_a_page_the_budget_refuses_is_not_reported_as_already_given(self):
        """Refused and already-sent are different facts; the note must not confuse them."""
        pages = {"act-1": {"a": "prvi " * 100}, "act-2": {"b": "drugi " * 400}}
        tool = self._tool(pages)
        tool.evidence.max_tokens = 1000
        tool.source.hits = [Hit("a", 0.30, "act-1"), Hit("b", 0.31, "act-2")]

        result = await tool.run({"questions": ["Sta je rekurzija?"]})

        self.assertEqual(len(result["passages"]), 1)
        self.assertIn("budget", result["note"])
        self.assertNotIn("already given", result["note"])

    async def test_an_empty_result_is_a_note_not_an_error(self):
        result = await self._tool({}).run({"questions": ["Sta je rekurzija?"]})

        self.assertEqual(result["passages"], [])
        self.assertIn("Reword", result["note"])

    async def test_a_hit_too_far_to_be_an_answer_is_dropped(self):
        """Search returns k neighbours whether or not one is relevant; the far ones cost."""
        chunks = {"act-1": {"a": "rekurzija"}, "act-2": {"b": "sortiranje"}}
        tool = self._tool(chunks)
        tool.source.hits = [Hit("a", 0.30, "act-1"), Hit("b", 0.48, "act-2")]

        result = await tool.run({"questions": ["Sta je rekurzija?"]})

        self.assertEqual([p["text"] for p in result["passages"]], ["rekurzija"])
        self.assertNotIn("note", result)

    async def test_a_question_nothing_answers_is_named_back_to_the_model(self):
        """Otherwise it reads the nearest unrelated page as this question's answer."""
        tool = self._tool({"act-1": {"a": "rekurzija"}})
        tool.source.hits = [Hit("a", 0.61, "act-1")]

        result = await tool.run({"questions": ["Ima li vec ugradjenih kvizova?"]})

        self.assertEqual(result["passages"], [])
        self.assertIn("Ima li vec ugradjenih kvizova?", result["note"])
        self.assertIn("Reword", result["note"])

    async def test_one_far_question_does_not_speak_for_the_others(self):
        """A batch is only as answerable as each question in it, and it is said per question."""
        tool = self._tool({"act-1": {"a": "rekurzija"}})
        answers = [[Hit("a", 0.30, "act-1")], [Hit("a", 0.61, "act-1")]]
        tool.source.search = lambda embedding, *, k, where: answers.pop(0)

        result = await tool.run({"questions": ["Sta je rekurzija?", "Ima li kviza?"]})

        self.assertEqual([p["text"] for p in result["passages"]], ["rekurzija"])
        self.assertIn('"Ima li kviza?"', result["note"])
        self.assertNotIn("Sta je rekurzija?", result["note"])

    async def test_the_page_the_teacher_is_on_is_not_held_to_the_cutoff(self):
        """It is relevant by where the teacher is, and capped at here_k either way."""
        tool = self._tool({"here": {"a": "zadatak"}}, activity_key="here")
        tool.source.hits = []
        tool.source.here_hits = [Hit("a", 0.88, "here")]

        result = await tool.run({"questions": ["Tehnika dva pokazivaca"]})

        self.assertEqual([p["text"] for p in result["passages"]], ["zadatak"])

    async def test_bad_arguments_come_back_as_data(self):
        tool = self._tool({})
        self.assertIn("error", await tool.run({}))
        self.assertIn("error", await tool.run({"questions": []}))
        self.assertIn("error", await tool.run({"questions": ["  "]}))
        self.assertIn("error", await tool.run({"questions": "Sta je rekurzija?"}))


class CurrentPageTests(unittest.IsolatedAsyncioTestCase):
    """The page the teacher is on, as the system message carries it."""

    def setUp(self):
        self.searched = []

    async def _embed(self, text):
        self.searched.append(text)
        return [0.0]

    async def _page(self, chunks, activity_key="here", query="Sta je rekurzija?",
                    hits=None, evidence=None, **kwargs):
        source = FakeCourseSource([])
        source.here_hits = hits or []
        self.evidence = evidence or Evidence(count_tokens=len)
        return await page_context.current_page(
            course_key="c", activity_key=activity_key, query=query, source=source,
            db=FakeCourseDB(chunks), embed=self._embed, evidence=self.evidence, **kwargs)

    async def test_a_short_page_goes_in_whole_without_embedding_anything(self):
        page = await self._page({"here": {"a": "prvi deo", "b": "drugi deo"}}, max_chunks=3)

        self.assertTrue(page.whole)
        self.assertEqual((page.used, page.total), (2, 2))
        self.assertIn("prvi deo", page.text)
        self.assertIn("drugi deo", page.text)
        # The common case must not cost an embedding call.
        self.assertEqual(self.searched, [])

    async def test_a_long_page_is_searched_with_the_teachers_own_question(self):
        chunks = {"here": {f"id{i}": f"zadatak {i}" for i in range(20)}}
        page = await self._page(chunks, query="Tehnika dva pokazivaca", max_chunks=3,
                                hits=[Hit("id4", 0.3, "here"), Hit("id9", 0.4, "here")])

        self.assertFalse(page.whole)
        self.assertEqual((page.used, page.total), (2, 20))
        self.assertEqual(self.searched, ["Tehnika dva pokazivaca"])
        # Unrelated tasks, so they are marked as separated rather than run together.
        self.assertIn("[...]", page.text)
        self.assertNotIn("zadatak 5", page.text)

    async def test_adjacent_chunks_of_a_long_page_are_fused(self):
        overlap = "Rekurzija je kada funkcija poziva samu sebe. " * 40
        chunks = {"here": dict({"a": "POCETAK. " + overlap, "b": overlap + "KRAJ."},
                               **{f"z{i}": f"drugo {i}" for i in range(9)})}
        page = await self._page(chunks, max_chunks=2,
                                hits=[Hit("a", 0.3, "here"), Hit("b", 0.4, "here")])

        self.assertFalse(page.whole)
        self.assertNotIn("[...]", page.text)      # one run, so nothing was left out
        self.assertEqual(len(page.text), len(overlap) + len("POCETAK. ") + len("KRAJ."))

    async def test_the_page_is_booked_so_a_later_tool_call_does_not_resend_it(self):
        """The prompt and the tools share one ledger; this is what makes that pay off."""
        chunks = {"here": {"a": "tekst lekcije"}}
        evidence = Evidence(count_tokens=len)
        await self._page(chunks, evidence=evidence)

        self.assertTrue(evidence.holds("a"))
        self.assertEqual([r["via"] for r in evidence.provenance], ["context"])

        tool = course_tools.CourseSearchTool(
            name="search_course", description="d", course_key="c", activity_key="here",
            source=FakeCourseSource([Hit("a", 0.3, "here")]), db=FakeCourseDB(chunks),
            embed=self._embed, evidence=evidence)
        result = await tool.run({"questions": ["Sta je rekurzija?"]})

        self.assertEqual(result["passages"], [])
        self.assertIn("already given to you", result["note"])

    async def test_a_page_with_no_indexed_text_is_None(self):
        self.assertIsNone(await self._page({}, activity_key="missing"))


class BundleHit:
    def __init__(self, id, distance, metadata):
        self.id = id
        self.distance = distance
        self.metadata = metadata


class FakeBundleSource:
    """One AIKT bundle: chunks in document order, concepts pointing back at them."""

    def __init__(self, chunks, concepts=None, unit="Handbook-for-Teachers"):
        self.key = "handbook"
        self.knowledge_unit = unit
        self.texts = dict(chunks)
        self.records = {chunk_id: {"ordinal": n, "title": "T",
                                   "heading_path": ["Assessment"], "token_count": 1}
                        for n, chunk_id in enumerate(chunks, start=1)}
        self.records.update({c: {"name": c} for c in (concepts or {})})
        self.concept_chunks = dict(concepts or {})
        self.chunk_hits = [BundleHit(i, 0.3, self.records[i]) for i in chunks]
        self.concept_hits = [BundleHit(c, 0.4, self.records[c]) for c in (concepts or {})]

    def search(self, embedding, *, k, where):
        kind = where["kind"]
        return (self.chunk_hits if kind == "chunk" else self.concept_hits)[:k]

    def text(self, record_id):
        return self.texts[record_id]


class BundleOfferingTests(unittest.TestCase):
    def test_every_offered_unit_names_itself_the_same_way(self):
        for unit, offered in knowledge_tools.BUNDLE_TOOLS.items():
            self.assertTrue(offered.name.isidentifier(), unit)
            self.assertTrue(offered.description.strip() and offered.label.strip(), unit)

    def test_a_bundle_no_tool_offers_stops_the_server_and_says_how_to_fix_it(self):
        """Indexed but unreachable is the failure nothing else would report."""
        source = FakeBundleSource({"a": "text"}, unit="Some-Other-Unit")

        with self.assertRaises(ValueError) as raised:
            knowledge_tools.offering(source)

        message = str(raised.exception)
        self.assertIn("Some-Other-Unit", message)
        self.assertIn("Handbook-for-Teachers", message)     # what is offered


class BundleSearchToolTests(unittest.IsolatedAsyncioTestCase):
    def _tool(self, source, evidence=None, **limits):
        self.embeddings = []

        async def embed(text):
            self.embeddings.append(text)
            return [0.0]

        return knowledge_tools.bundle_search_tool(
            source=source, embed=embed, evidence=evidence or Evidence(count_tokens=len),
            limits=knowledge_tools.Limits(**limits))

    async def test_adjacent_chunks_arrive_as_one_passage_and_scattered_ones_apart(self):
        """Merged before delivery, so the ledger charges what the model actually receives."""
        source = FakeBundleSource({"a": "prvi", "b": "drugi", "d": "cetvrti"})
        source.records["d"]["ordinal"] = 4          # a gap after "b"
        tool = self._tool(source)

        result = await tool.run({"questions": ["How do I grade group work?"]})

        self.assertEqual([p["text"] for p in result["passages"]],
                         ["prvi\n\ndrugi", "cetvrti"])
        self.assertEqual(result["passages"][0]["source"],
                         knowledge_tools.TEACHING_LITERATURE.label)

    async def test_a_matched_concept_pulls_its_chunks_and_is_named_back(self):
        source = FakeBundleSource({"a": "prvi"}, concepts={"Assessment Rubrics": ["a"]})
        source.chunk_hits = []                       # only the concept matches
        tool = self._tool(source)

        result = await tool.run({"questions": ["rubrics?"]})

        self.assertEqual(result["matched_concepts"], ["Assessment Rubrics"])
        self.assertEqual([p["text"] for p in result["passages"]], ["prvi"])

    async def test_one_question_costs_one_embedding_for_both_kinds(self):
        """Concepts and chunks share a collection and an embedder -- and now a vector."""
        tool = self._tool(FakeBundleSource({"a": "prvi"},
                                           concepts={"Assessment Rubrics": ["a"]}))

        await tool.run({"questions": ["one", "two"]})

        self.assertEqual(self.embeddings, ["one", "two"])

    async def test_a_chunk_too_far_to_be_an_answer_is_dropped(self):
        """This handbook has no programming didactics; without a cutoff it answers anyway."""
        source = FakeBundleSource({"a": "prvi", "b": "drugi"})
        source.records["b"]["ordinal"] = 5              # a gap, so no run merging
        source.chunk_hits = [BundleHit("a", 0.30, source.records["a"]),
                             BundleHit("b", 0.52, source.records["b"])]
        tool = self._tool(source)

        result = await tool.run({"questions": ["How do I grade group work?"]})

        self.assertEqual([p["text"] for p in result["passages"]], ["prvi"])

    async def test_a_far_concept_is_neither_expanded_nor_named_back(self):
        """A concept vector is a short name and sits near anything -- its own cutoff."""
        source = FakeBundleSource({"a": "prvi"}, concepts={"Multiple Intelligences": ["a"]})
        source.chunk_hits = []
        source.concept_hits = [BundleHit("Multiple Intelligences", 0.50,
                                         source.records["Multiple Intelligences"])]
        tool = self._tool(source)

        result = await tool.run({"questions": ["How do I grade group work?"]})

        self.assertEqual(result["passages"], [])
        self.assertNotIn("matched_concepts", result)
        self.assertIn("How do I grade group work?", result["note"])

    async def test_only_the_closest_chunks_are_delivered_and_the_rest_are_named(self):
        """Ranked by distance rather than by ordinal, so the cap keeps the best of them."""
        source = FakeBundleSource({"a": "prvi", "b": "drugi", "c": "treci"})
        for n, chunk_id in enumerate("abc"):
            source.records[chunk_id]["ordinal"] = 1 + 2 * n
        source.chunk_hits = [BundleHit("c", 0.44, source.records["c"]),
                             BundleHit("a", 0.30, source.records["a"]),
                             BundleHit("b", 0.38, source.records["b"])]
        tool = self._tool(source, max_chunks=2)

        result = await tool.run({"questions": ["How do I grade group work?"]})

        self.assertEqual([p["text"] for p in result["passages"]], ["prvi", "drugi"])
        self.assertIn("1 further passage(s)", result["note"])

    async def test_a_chunk_the_question_hit_outranks_one_a_concept_led_to(self):
        """Concept distances run lower by construction; one ranking would invert these."""
        source = FakeBundleSource({"a": "prvi", "b": "drugi"},
                                  concepts={"Assessment Rubrics": ["b"]})
        source.records["b"]["ordinal"] = 5
        source.chunk_hits = [BundleHit("a", 0.44, source.records["a"])]
        source.concept_hits = [BundleHit("Assessment Rubrics", 0.20,
                                         source.records["Assessment Rubrics"])]
        tool = self._tool(source, max_chunks=1)

        result = await tool.run({"questions": ["rubrics?"]})

        self.assertEqual([p["text"] for p in result["passages"]], ["prvi"])

    async def test_a_second_call_counts_what_the_model_has_rather_than_sending_a_status(self):
        """Passages carry text and nothing else; the rest of it is said in prose."""
        tool = self._tool(FakeBundleSource({"a": "prvi"}))

        first = await tool.run({"questions": ["How do I grade group work?"]})
        second = await tool.run({"questions": ["How do I grade group work?"]})

        self.assertIn("text", first["passages"][0])
        self.assertEqual(second["passages"], [])
        self.assertIn("already given to you", second["note"])

    async def test_nothing_close_enough_is_data_rather_than_an_empty_answer(self):
        source = FakeBundleSource({"a": "prvi"})
        source.chunk_hits = []
        tool = self._tool(source)

        result = await tool.run({"questions": ["quantum chromodynamics?"]})

        self.assertEqual(result["passages"], [])
        self.assertIn("does not cover", result["note"])


if __name__ == "__main__":
    unittest.main()
