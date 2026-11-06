import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from agent_harness import ResearchAgent
from java_worker import execute
from rag_system import RagSystem
from run_store import RunStore
from test_research import ScriptedClient, response


class JavaWorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        docs = self.root / 'docs'
        docs.mkdir()
        (docs / '第三十四回.txt').write_text('宝钗带着药丸来探望宝玉，嘱咐袭人调敷。', encoding='utf-8')
        self.rag = RagSystem(docs_dir=docs, cache_dir=self.root / 'cache')
        self.rag.initialize()
        self.job = {'id': uuid.uuid4().hex, 'question': '宝钗探望宝玉', 'mode': 'research'}

    def worker(self, job):
        with patch('rag_system.RagSystem', return_value=self.rag), \
             patch('rag_system.PROJECT_DIR', self.root), \
             patch('rag_system.load_api_key', return_value=None):
            return execute(job)

    def test_bridge_reuses_checkpoint_and_completed_run_without_second_model_call(self):
        self.rag.client = ScriptedClient([
            response('submit_answer', {'claims': [], 'limitations': ['暂缺可核对的引文。']})])
        first = self.worker(self.job)
        again = self.worker(self.job)
        self.assertEqual(first['run_id'], self.job['id'])
        self.assertEqual(again['status'], 'completed')
        self.assertEqual(len(self.rag.client.requests), 1)
        changed = dict(self.job, question='黛玉葬花')
        with self.assertRaisesRegex(ValueError, 'mismatch'):
            self.worker(changed)

    def test_lookup_never_calls_model_or_loads_key(self):
        self.rag.client = ScriptedClient([])
        with patch('rag_system.load_api_key', side_effect=AssertionError('must not read key')), \
             patch('rag_system.RagSystem', return_value=self.rag):
            result = execute(dict(self.job, mode='lookup'))
        self.assertTrue(result['sources'])
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(self.rag.client.requests, [])

    def test_external_run_id_does_not_overwrite_existing_checkpoint(self):
        store = RunStore(self.root / 'state.sqlite3')
        agent = ResearchAgent(self.rag, store)
        self.rag.client = ScriptedClient([
            response('submit_answer', {'claims': [], 'limitations': ['资料不足。']})])
        agent.start(self.job['question'], run_id=self.job['id'])
        with self.assertRaises(Exception):
            agent.start('另一个问题', run_id=self.job['id'])
        self.assertEqual(store.load(self.job['id'])['question'], self.job['question'])


if __name__ == '__main__':
    unittest.main()
