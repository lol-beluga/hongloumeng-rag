import json
import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch

from agent_harness import AgentConfig, ResearchAgent, public_result
from rag_system import RagSystem, chapter_number
from research_tools import SCHEMAS, validate, validate_report
from run_store import RunStore


def response(name, args, content=""):
    call = NS(id="call_" + uuid.uuid4().hex, function=NS(name=name, arguments=json.dumps(args)))
    return NS(choices=[NS(message=NS(content=content, tool_calls=[call]))],
              usage=NS(total_tokens=20, prompt_tokens=15, completion_tokens=5))


class ScriptedClient:
    def __init__(self, steps):
        self.steps, self.requests = list(steps), []
        self.chat = NS(completions=NS(create=self.create))

    def create(self, **kwargs):
        self.requests.append(json.loads(json.dumps(kwargs)))
        step = self.steps.pop(0)
        if isinstance(step, Exception):
            raise step
        return step(kwargs) if callable(step) else step


class ResearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.docs = cls.root / "docs"
        cls.docs.mkdir()
        # Two independently retrievable sources; no real API or private local files are read.
        (cls.docs / "第三十三回 宝玉受责.txt").write_text(
            "宝玉受到父亲责打，袭人照看宝玉。黛玉听到消息之后前来看望。", encoding="utf-8")
        (cls.docs / "第三十四回 情中情.txt").write_text(
            "宝钗前来探望宝玉，带着药丸嘱咐袭人调敷。黛玉随后也来看望受伤的宝玉。", encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        self.rag = RagSystem(docs_dir=self.docs, cache_dir=self.root / "cache")
        self.rag.initialize()
        self.store = RunStore(self.root / (uuid.uuid4().hex + ".sqlite3"))
        self.chunk = self.rag.search_chunks("宝钗 探望")[0]

    def report(self, chunk=None):
        chunk = chunk or self.chunk
        return {"claims": [{"statement": "宝钗前来探望宝玉。", "kind": "fact", "citations": [
            {"evidence_id": chunk["evidence_id"], "quote": chunk["content"][:18]}]}], "limitations": []}

    def client(self, steps):
        self.rag.client = ScriptedClient(steps)
        return self.rag.client

    def test_chapter_numbers_and_scope(self):
        self.assertEqual([chapter_number(f"第{x}回") for x in ("十", "二十", "一百零九", "一百二十")],
                         [10, 20, 109, 120])
        results = self.rag.search_chunks("宝玉", chapter_start=34, chapter_end=34)
        self.assertTrue(results)
        self.assertTrue(all(c["chapter"] == 34 for c in results))
        self.assertEqual(self.rag.list_chapters()["total"], 2)

    def test_invalid_quote_and_unknown_evidence_rejected(self):
        report = self.report()
        report["claims"][0]["citations"][0]["quote"] = "原著中从来没有出现的捏造句子"
        with self.assertRaisesRegex(ValueError, "引用文字"):
            validate_report(report, {self.chunk["evidence_id"]: self.chunk})
        with self.assertRaisesRegex(ValueError, "尚未读取"):
            validate_report(self.report(), {})

    def test_bool_and_path_arguments_rejected(self):
        with self.assertRaises(ValueError):
            validate(SCHEMAS["search_text"], {"query": "宝玉", "top_k": True})
        with self.assertRaises(ValueError):
            validate(SCHEMAS["read_passage"], {"evidence_id": "abc", "path": ".env"})
        with self.assertRaises(ValueError):
            self.rag.read_passage("../../.env")

    def test_model_selects_tools_and_submits_grounded_report(self):
        client = self.client([
            response("plan_research", {"questions": ["宝钗如何探望宝玉？"]}),
            response("search_text", {"query": "宝钗 探望", "chapter_start": 34, "chapter_end": 34}),
            response("read_passage", {"evidence_id": self.chunk["evidence_id"], "neighbors": 1}),
            response("submit_answer", self.report())])
        state = ResearchAgent(self.rag, self.store).start("宝钗如何探望宝玉？")
        self.assertEqual(state["status"], "completed")
        self.assertIn(self.chunk["evidence_id"], state["answer"])
        self.assertEqual(state["tool_calls"], 4)
        self.assertEqual(len(client.requests), 4)
        self.assertTrue(any(m["role"] == "tool" for m in client.requests[1]["messages"]))
        assistant = next(m for m in client.requests[1]["messages"] if m.get("tool_calls"))
        self.assertEqual(len(assistant["tool_calls"]), 1)
        self.assertTrue(all(m.get("tool_calls") != [] for m in client.requests[1]["messages"]))
        self.assertEqual(self.store.load(state["run_id"])["status"], "completed")

    def test_bad_final_quote_is_repaired_before_display(self):
        bad = self.report()
        bad["claims"][0]["citations"][0]["quote"] = "完全不存在于原文中的捏造内容"
        self.client([response("search_text", {"query": "宝钗 探望"}),
                     response("submit_answer", bad), response("submit_answer", self.report())])
        state = ResearchAgent(self.rag, self.store).start("宝钗如何探望？")
        self.assertEqual(state["status"], "completed")
        self.assertNotIn("捏造内容", state["answer"])
        self.assertTrue(any(e["kind"] == "tool" and not e["success"] for e in state["events"]))

    def test_truncated_tool_json_gets_actionable_feedback(self):
        truncated = response("submit_answer", {})
        truncated.choices[0].message.tool_calls[0].function.arguments = '{"claims":[{"statement":"'
        truncated.choices[0].finish_reason = "length"
        client = self.client([response("search_text", {"query": "宝钗 探望"}), truncated,
                              response("submit_answer", self.report())])
        state = ResearchAgent(self.rag, self.store).start("宝钗如何探望？")
        self.assertEqual(state["status"], "completed")
        self.assertIn("截断", client.requests[-1]["messages"][-1]["content"])

    def test_empty_search_can_end_with_explicit_insufficiency(self):
        self.client([response("search_text", {"query": "zzzzzzzzzz"}), response("submit_answer", {
            "claims": [], "limitations": ["当前语料未找到相关证据，无法判断。"]})])
        state = ResearchAgent(self.rag, self.store).start("当前文本没有的内容？")
        self.assertEqual(state["evidence"], {})
        self.assertEqual(state["status"], "completed")
        self.assertIn("无法判断", state["answer"])

    def test_tool_budget_pauses_and_explicit_extension_resumes(self):
        client = self.client([response("search_text", {"query": "宝钗 探望"}),
                              response("submit_answer", self.report())])
        agent = ResearchAgent(self.rag, self.store, AgentConfig(max_tool_calls=1))
        state = agent.start("宝钗如何探望？")
        self.assertEqual(state["stop_reason"], "tool_budget")
        again = agent.resume(state["run_id"])
        self.assertEqual(len(client.requests), 1)
        finished = agent.resume(again["run_id"], extend_budget=True)
        self.assertEqual(finished["status"], "completed")
        self.assertEqual(len(client.requests), 2)

    def test_interrupted_batch_resumes_pending_tool_without_repeating_search(self):
        first = response("search_text", {"query": "宝钗 探望"})
        extra = response("read_passage", {"evidence_id": self.chunk["evidence_id"]})
        first.choices[0].message.tool_calls += extra.choices[0].message.tool_calls
        client = self.client([first, response("submit_answer", self.report())])

        def interrupt(event):
            if event["kind"] == "tool" and event["name"] == "search_text":
                raise InterruptedError("simulated process interruption")

        with self.assertRaises(InterruptedError):
            ResearchAgent(self.rag, self.store).start("宝钗如何探望？", on_event=interrupt)
        saved = self.store.recent()[0]
        self.assertEqual(len(saved["pending"]), 1)
        state = ResearchAgent(self.rag, self.store).resume(saved["run_id"])
        self.assertEqual(state["status"], "completed")
        self.assertEqual(len(client.requests), 2)
        self.assertEqual(sum(e["kind"] == "tool" and e["name"] == "search_text" for e in state["events"]), 1)

    def test_transient_request_retry_is_bounded(self):
        class FakeTimeout(Exception):
            pass
        client = self.client([FakeTimeout("private detail"), FakeTimeout("private detail")])
        with patch("agent_harness.time.sleep"):
            state = ResearchAgent(self.rag, self.store, AgentConfig(retries=1)).start("宝玉？")
        self.assertEqual(len(client.requests), 2)
        self.assertEqual(state["stop_reason"], "api_retry_exhausted")
        self.assertNotIn("private detail", json.dumps(public_result(state)))

    def test_permanent_error_does_not_retry_or_log_sensitive_details(self):
        error = RuntimeError("sk-private-example")
        error.status_code = 401
        client = self.client([error])
        state = ResearchAgent(self.rag, self.store).start("宝玉？")
        self.assertEqual(len(client.requests), 1)
        self.assertEqual(state["stop_reason"], "api_configuration_error")
        self.assertNotIn("sk-private-example", json.dumps(state))

    def test_token_budget_stops_further_requests(self):
        client = self.client([response("search_text", {"query": "宝钗 探望"})])
        state = ResearchAgent(self.rag, self.store, AgentConfig(max_total_tokens=1)).start("宝钗？")
        self.assertEqual(state["stop_reason"], "token_budget")
        self.assertEqual(len(client.requests), 1)

    def test_context_compaction_keeps_question_and_evidence(self):
        client = self.client([response("search_text", {"query": "宝钗 探望"}, content="冗余内容" * 7000),
                              response("submit_answer", self.report())])
        state = ResearchAgent(self.rag, self.store, AgentConfig(max_context_chars=14000)).start("宝钗如何探望？")
        self.assertEqual(state["status"], "completed")
        self.assertTrue(any(e["kind"] == "context_compacted" for e in state["events"]))
        self.assertIn(self.chunk["evidence_id"], json.dumps(client.requests[1]["messages"]))

    def test_completed_task_does_not_call_model_again(self):
        client = self.client([response("submit_answer", {"claims": [], "limitations": ["当前证据不足。"]})])
        agent = ResearchAgent(self.rag, self.store)
        state = agent.start("无法查证的问题")
        agent.resume(state["run_id"], extend_budget=True)
        self.assertEqual(len(client.requests), 1)

    def test_provider_tool_metadata_is_roundtripped_but_not_exported(self):
        first = response("search_text", {"query": "宝钗 探望"})
        first.choices[0].message.reasoning_content = "provider-private-protocol-field"
        client = self.client([first, response("submit_answer", self.report())])
        state = ResearchAgent(self.rag, self.store).start("宝钗如何探望？")
        self.assertEqual(state["status"], "completed")
        self.assertIn("provider-private-protocol-field", json.dumps(client.requests[1]["messages"]))
        self.assertNotIn("provider-private-protocol-field", json.dumps(public_result(state)))

    def test_lease_prevents_duplicate_execution(self):
        self.client([response("submit_answer", {"claims": [], "limitations": ["当前证据不足。"]})])
        state = ResearchAgent(self.rag, self.store).start("宝玉？")
        owner = self.store.acquire(state["run_id"], 30)
        with self.assertRaises(RuntimeError):
            ResearchAgent(self.rag, self.store).resume(state["run_id"])
        self.store.release(state["run_id"], owner)

    def test_changed_corpus_invalidates_cache_and_blocks_old_run_resume(self):
        self.client([response("submit_answer", {"claims": [], "limitations": ["当前证据不足。"]})])
        state = ResearchAgent(self.rag, self.store).start("宝玉？")
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            (path / "第一回 新文本.txt").write_text("甄士隐梦幻识通灵，贾雨村风尘怀闺秀。", encoding="utf-8")
            changed = RagSystem(docs_dir=path, cache_dir=self.root / "cache")
            changed.initialize()
            old_id = changed.corpus_id
            (path / "第一回 新文本.txt").write_text("甄士隐梦幻识通灵，新的原著文本内容。", encoding="utf-8")
            changed.initialize()
            self.assertNotEqual(changed.corpus_id, old_id)
            with self.assertRaisesRegex(ValueError, "语料已变化"):
                ResearchAgent(changed, self.store).resume(state["run_id"])


if __name__ == "__main__":
    unittest.main()
