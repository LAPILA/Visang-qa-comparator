"""Real Chromium regression against only the in-process synthetic loopback site."""
import json
import tempfile
import threading
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from app import Server
from qa.config import parse_options
from qa.demo import get_demo_summary, handle_demo, reset_demo_counts
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
                self.assertEqual(report['manifest']['schemaVersion'], '2.0')
                self.assertEqual(report['manifest']['testType'], 'comparison')
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
                self.assertGreater(report['totals']['blocked'], 0)
                self.assertEqual(report['manifest']['status'], 'PARTIAL')
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

    def test_single_regression_and_conditions_never_visit_b(self):
        temporary_root = Path(__file__).resolve().parents[1] / 'output' / 'tmp'
        temporary_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temporary_root) as directory:
            runs = Path(directory) / 'runs'
            server = Server(('127.0.0.1', 0), runs_dir=runs)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                paths = []
                def observed_demo(handler, path):
                    paths.append(path)
                    return handle_demo(handler, path)
                reset_demo_counts()
                for test_type in ('single', 'regression', 'conditional'):
                    conditions = ([{'id': 'nav', 'selector': '#site-nav', 'kind': 'visible', 'expected': True},
                                   {'id': 'deliberate-fail', 'selector': '#required-action', 'kind': 'visible', 'expected': False},
                                   {'id': 'data-prerequisite', 'selector': '#site-nav', 'kind': 'count', 'expected': {'min': 1},
                                    'case': 'pagination', 'preconditions': [{'selector': '#no-such-fixture-data', 'kind': 'visible', 'expected': True}]}]
                                  if test_type == 'conditional' else [])
                    payload = {'profileId': 'synthetic-demo', 'operatorId': 'regression', 'testType': test_type,
                               'maxPages': 1, 'maxDepth': 0, 'maxActions': 80, 'mode': 'visual',
                               'scenarioIds': [], 'safeActions': [], 'conditions': conditions,
                               'previousRunId': str(uuid.uuid4()) if test_type == 'regression' else None}
                    options = parse_options(payload, server.base_origin)
                    with patch('qa.demo.handle_demo', side_effect=observed_demo):
                        report = run_scan(options, str(uuid.uuid4()), runs, lambda _: None, lambda: False)
                    self.assertEqual(report['totals']['baselineVisited'], 1)
                    self.assertEqual(report['totals']['candidateVisited'], 0)
                    self.assertIsNone(report['candidateUrl'])
                    self.assertEqual(report['totals']['error'], 0)
                    self.assertTrue(all(row['candidate'] is None and row['visual'] is None for row in report['results']))
                    self.assertTrue(all(row['match']['method'] == 'SINGLE_ENVIRONMENT' for row in report['results']))
                    self.assertFalse(any('NOT_DISCOVERED' in row['flags'] for row in report['results']))
                    self.assertEqual(report['manifest']['scope']['targetShape'], 'single')
                    if test_type == 'conditional':
                        checks = {item['check_id']: item for row in report['results'] for item in row['checks']}
                        self.assertEqual(checks['a.condition.nav']['status'], 'PASS')
                        self.assertEqual(checks['a.condition.deliberate-fail']['status'], 'FAIL')
                        self.assertEqual(checks['a.condition.data-prerequisite']['status'], 'BLOCKED')
                self.assertTrue(paths)
                self.assertTrue(all(not path.startswith('/demo/b/') for path in paths))
                self.assertEqual(get_demo_summary()['mutation_counts'],
                                 {'a': {'save': 0, 'delete': 0}, 'b': {'save': 0, 'delete': 0}})
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)


if __name__ == '__main__':
    unittest.main()
