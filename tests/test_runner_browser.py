"""Real Chromium regression against only the in-process synthetic loopback site."""
import json
import tempfile
import threading
import unittest
import uuid
from pathlib import Path

from app import Server
from qa.config import parse_options
from qa.demo import get_demo_summary, reset_demo_counts
from qa.engine import run_scan


class RunnerBrowserTests(unittest.TestCase):
    def test_alias_regions_scenarios_and_mutation_guards_end_to_end(self):
        temporary_root = Path(__file__).resolve().parents[1] / 'output' / 'tmp'
        temporary_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temporary_root) as directory:
            runs = Path(directory) / 'runs'
            server = Server(('127.0.0.1', 0), runs_dir=runs)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                reset_demo_counts()
                options = parse_options({'profileId': 'synthetic-demo', 'operatorId': 'regression',
                                         'maxPages': 3, 'maxDepth': 2, 'maxActions': 80,
                                         'actionInterval': 0.1, 'timeoutSeconds': 90}, server.base_origin)
                run_id = str(uuid.uuid4())
                report = run_scan(options, run_id, runs, lambda message: None, lambda: False)
                self.assertEqual(report['totals']['baselineVisited'], 3)
                self.assertEqual(report['totals']['candidateVisited'], 3)
                self.assertEqual(report['totals']['error'], 0)
                pages = [row for row in report['results'] if row['region_id'] == 'page'
                         and row['match']['method'] != 'NOT_EXECUTED']
                self.assertTrue(all(row['match']['method'] == 'EXPLICIT_ALIAS' for row in pages))
                self.assertTrue(any(row['region_id'] == 'required-help' and row['status'] == 'FAIL'
                                    and any(item['reason_code'] == 'REQUIRED_REGION_MISSING' for item in row['checks'])
                                    for row in report['results']))
                scenario_checks = [item for row in pages for item in row['checks']
                                   if item.get('scenario_id', '').startswith('demo.')]
                self.assertEqual(len(scenario_checks), 30)
                self.assertEqual(len({item['check_id'] for item in scenario_checks}), 30)
                self.assertEqual({item['environment'] for item in scenario_checks}, {'a', 'b'})
                self.assertTrue(all(item['status'] == 'PASS' for item in scenario_checks))
                self.assertEqual(get_demo_summary()['mutation_counts'],
                                 {'a': {'save': 0, 'delete': 0}, 'b': {'save': 0, 'delete': 0}})
                self.assertGreater(report['totals']['blockedActions'], 0)
                self.assertGreater(report['coverage']['deferredPages'], 0)
                self.assertTrue(report['coverage']['incomplete'])
                self.assertEqual(report['totals']['attemptedActions'], report['totals']['executedActions'])
                self.assertGreater(report['totals']['executedActions'], 2)
                for row in report['results']:
                    for side in ('baseline', 'candidate'):
                        artifact = (row[side] or {}).get('screenshot')
                        if artifact:
                            relative = artifact.removeprefix('/artifacts/')
                            self.assertTrue((runs / relative).is_file(), artifact)
                server.service.store.save({'id': run_id, 'state': 'done', 'report': report})
                saved_path = runs / run_id / 'report.json'
                saved = json.loads(saved_path.read_text(encoding='utf-8'))
                self.assertEqual(saved['report']['totals'], report['totals'])
                self.assertNotIn('screenshotFile', saved_path.read_text(encoding='utf-8'))
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)


if __name__ == '__main__':
    unittest.main()
