import unittest
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

import app_ui
from rag_system import RagSystem
from run_store import RunStore


class UiTests(unittest.TestCase):
    def test_startup_and_switch_modes_without_api_calls(self):
        with patch.object(app_ui, "load_api_key", return_value=""):
            app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "streamlit_app.py"),
                                   default_timeout=40).run()
            self.assertEqual(len(app.exception), 0)
            self.assertTrue(app.chat_input[0].disabled)
            app.radio[0].set_value("普通问答").run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(app.radio[0].value, "普通问答")

    def test_chat_report_and_completed_task_resume(self):
        rag = RagSystem()
        rag.initialize()
        chunk = rag._by_id["9f957caa3908:0010"]
        report = {"claims": [{"statement": "甄士隐的女儿乳名英莲。", "kind": "fact", "citations": [
            {"evidence_id": chunk["evidence_id"], "quote": "只有一女，乳名唤作英莲，年方三岁"}]}], "limitations": []}
        calls = []

        def create(**kwargs):
            calls.append(kwargs)
            name, args = ("search_text", {"query": "乳名 英莲", "chapter_start": 1, "chapter_end": 1}) if len(calls) == 1 else ("submit_answer", report)
            call = NS(id=f"call_{len(calls)}", function=NS(name=name, arguments=json.dumps(args)))
            return NS(choices=[NS(message=NS(content="", tool_calls=[call]))],
                      usage=NS(total_tokens=20, prompt_tokens=15, completion_tokens=5))

        client = NS(chat=NS(completions=NS(create=create)), close=lambda: None)
        with tempfile.TemporaryDirectory() as folder:
            store = RunStore(Path(folder) / "ui.sqlite3")
            with patch.object(app_ui, "load_api_key", return_value="offline-test-key"), \
                 patch.object(app_ui, "OpenAI", return_value=client), \
                 patch.object(app_ui, "RunStore", return_value=store):
                app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "streamlit_app.py"),
                                       default_timeout=40).run()
                app.chat_input[0].set_value("甄士隐的女儿叫什么？").run()
                self.assertEqual(len(app.exception), 0)
                self.assertEqual(len(calls), 2)
                state = store.recent()[0]
                self.assertEqual(state["status"], "completed")
                self.assertIn("英莲", state["answer"])
                next(b for b in app.button if b.label == "继续所选任务").click().run()
                self.assertEqual(len(app.exception), 0)
                self.assertEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()
