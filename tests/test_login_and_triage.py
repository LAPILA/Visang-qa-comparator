"""Test-account login (credentials never leave the machine) and review triage."""
import json
import os
import tempfile
import threading
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from app import Server, csv_report
from qa.config import parse_options
from qa.engine import run_scan
from qa.secrets import load_credentials
from qa.triage import apply_triage, triage_row

DEMO_LOGIN = {'usernameSelector': '#login-id', 'passwordSelector': '#login-pw', 'submitSelector': '#login-submit',
              'successSelector': '#session-state', 'failureSelector': '#login-error'}


class SecretsTests(unittest.TestCase):
    def test_environment_precedence_and_file_fallback(self):
        env = {'QA_LOGIN_A_ID': 'tester-a', 'QA_LOGIN_A_PW': 'pw-a', 'QA_LOGIN_ID': 'shared', 'QA_LOGIN_PW': 'pw-shared'}
        self.assertEqual(load_credentials('a', environ=env).username, 'tester-a')
        self.assertEqual(load_credentials('b', environ=env).username, 'shared')
        self.assertIsNone(load_credentials('a', environ={}, root=tempfile.gettempdir() + '/nonexistent-qa-secrets'))
        with tempfile.TemporaryDirectory() as directory:
            secrets = Path(directory) / 'secrets'
            secrets.mkdir()
            (secrets / 'accounts.json').write_text(json.dumps({'accounts': {
                'default': {'id': 'file-user', 'pw': 'file-pw'}, 'default.b': {'id': 'file-b', 'pw': 'pw-b'}}}), encoding='utf-8')
            self.assertEqual(load_credentials('a', environ={}, root=directory).username, 'file-user')
            self.assertEqual(load_credentials('b', environ={}, root=directory).username, 'file-b')
            self.assertEqual(load_credentials('b', 'missing-key', environ={}, root=directory), None)
        credentials = load_credentials('a', environ=env)
        self.assertNotIn('pw-a', repr(credentials))
        self.assertNotIn('tester-a', str(credentials))

    def test_api_rejects_credentials_but_accepts_form_description(self):
        with self.assertRaises(ValueError):
            parse_options({'profileId': 'synthetic-demo', 'login': dict(DEMO_LOGIN, password='x')}, 'http://127.0.0.1:1')
        with self.assertRaises(ValueError):
            parse_options({'profileId': 'synthetic-demo', 'login': {'usernameSelector': '#id'}}, 'http://127.0.0.1:1')
        options = parse_options({'profileId': 'synthetic-demo', 'login': DEMO_LOGIN}, 'http://127.0.0.1:1')
        self.assertEqual(options['login']['accountKey'], 'default')
        self.assertTrue(options['route_equivalence'])
        self.assertFalse(parse_options({'profileId': 'synthetic-demo', 'routeEquivalence': False}, 'http://127.0.0.1:1')['route_equivalence'])


class LoginBrowserTests(unittest.TestCase):
    def run_demo(self, environ, **extra):
        temporary_root = Path(__file__).resolve().parents[1] / 'output' / 'tmp'
        temporary_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temporary_root) as directory:
            runs = Path(directory) / 'runs'
            server = Server(('127.0.0.1', 0), runs_dir=runs)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            try:
                options = parse_options({'profileId': 'synthetic-demo', 'operatorId': 'login-test', 'testType': 'single',
                                         'maxPages': 1, 'maxDepth': 0, 'maxActions': 5, 'mode': 'visual',
                                         'timeoutSeconds': 60, 'login': dict(DEMO_LOGIN, url=server.base_origin + '/demo/a/login'),
                                         **extra}, server.base_origin)
                with patch.dict(os.environ, environ, clear=False), patch('qa.secrets.DEFAULT_SECRETS_FILE', Path('definitely-missing.json')):
                    for key in ('QA_LOGIN_ID', 'QA_LOGIN_PW', 'QA_LOGIN_A_ID', 'QA_LOGIN_A_PW', 'QA_SECRETS_FILE'):
                        if key not in environ:
                            os.environ.pop(key, None)
                    return run_scan(options, str(uuid.uuid4()), runs, lambda message: None, lambda: False)
            finally:
                server.shutdown()
                server.server_close()

    def login_check(self, report):
        start = next(row for row in report['results'] if row['region_id'] == 'page')
        return start, next(item for item in start['checks'] if item['check_id'] == 'a.login')

    def test_login_success_is_evidence_and_secret_never_reaches_report(self):
        report = self.run_demo({'QA_LOGIN_A_ID': 'qa-tester', 'QA_LOGIN_A_PW': 'demo-pass'})
        start, item = self.login_check(report)
        self.assertEqual((item['status'], item['reason_code']), ('PASS', 'TEST_ACCOUNT_LOGIN_OK'))
        self.assertEqual(report['manifest']['login']['method'], 'TEST_ACCOUNT')
        self.assertFalse(report['manifest']['login']['credentialsStored'])
        serialized = json.dumps(report, ensure_ascii=False)
        self.assertNotIn('demo-pass', serialized)
        self.assertNotIn('qa-tester', serialized)
        self.assertNotIn(start['status'], ('BLOCKED', 'ERROR'))
        self.assertIn(triage_row(start)['bucket'], ('OK', 'HUMAN_CHECK'))

    def test_wrong_password_blocks_with_retest_triage(self):
        report = self.run_demo({'QA_LOGIN_A_ID': 'qa-tester', 'QA_LOGIN_A_PW': 'wrong'})
        start, item = self.login_check(report)
        self.assertEqual((item['status'], item['reason_code']), ('BLOCKED', 'LOGIN_FAILED'))
        self.assertEqual(start['status'], 'BLOCKED')
        self.assertEqual(triage_row(start)['bucket'], 'RETEST')
        self.assertEqual(triage_row(start)['reason'], 'AUTH_REQUIRED')

    def test_missing_credentials_never_guess(self):
        report = self.run_demo({})
        _, item = self.login_check(report)
        self.assertEqual((item['status'], item['reason_code']), ('BLOCKED', 'LOGIN_CREDENTIALS_MISSING'))


class TriageTests(unittest.TestCase):
    def row(self, status, checks):
        return {'id': 'r', 'status': status, 'checks': checks, 'region_id': 'page'}

    def test_buckets_follow_the_documented_decision_table(self):
        self.assertEqual(triage_row(self.row('PASS', [{'check_id': 'a.document', 'status': 'PASS', 'reason_code': 'DOCUMENT_REACHABLE'}]))['bucket'], 'OK')
        self.assertEqual(triage_row(self.row('SKIP', []))['bucket'], 'NOT_RUN')
        page_error = self.row('FAIL', [{'check_id': 'a.document', 'status': 'FAIL', 'reason_code': 'DOCUMENT_HTTP_ERROR', 'actual': 500}])
        self.assertEqual((triage_row(page_error)['bucket'], triage_row(page_error)['reason']), ('ISSUE', 'PAGE_UNREACHABLE'))
        missing = self.row('FAIL', [{'check_id': 'a.document', 'status': 'PASS', 'reason_code': 'DOCUMENT_REACHABLE'},
                                    {'check_id': 'a.region.help', 'status': 'FAIL', 'reason_code': 'REQUIRED_REGION_MISSING'}])
        self.assertEqual(triage_row(missing)['bucket'], 'ISSUE')
        scenario = self.row('FAIL', [{'check_id': 'a.document', 'status': 'PASS', 'reason_code': 'DOCUMENT_REACHABLE'},
                                     {'check_id': 'a.search.results', 'status': 'FAIL', 'reason_code': 'RESULT_COUNT_MISMATCH', 'scenario_id': 'demo.search'}])
        self.assertEqual(triage_row(scenario)['reason'], 'FUNCTIONAL_CONTRACT_VIOLATED')
        broken_image = self.row('FAIL', [
            {'check_id': 'a.document', 'status': 'PASS', 'reason_code': 'DOCUMENT_REACHABLE'},
            {'check_id': 'a.observation.1', 'status': 'FAIL', 'reason_code': 'BROKEN_IMAGE',
             'observation': {'category': 'BROKEN_IMAGE', 'resourceType': 'image', 'statusCode': 404}}])
        self.assertEqual((triage_row(broken_image)['bucket'], triage_row(broken_image)['reason']), ('HUMAN_CHECK', 'ERRORS_BUT_PAGE_WORKS'))
        js = self.row('FAIL', [{'check_id': 'a.document', 'status': 'PASS', 'reason_code': 'DOCUMENT_REACHABLE'},
                               {'check_id': 'a.observation.2', 'status': 'FAIL', 'reason_code': 'JS_ERROR', 'observation': {'category': 'JS_ERROR'}}])
        self.assertEqual(triage_row(js)['bucket'], 'HUMAN_CHECK')
        diff = self.row('DIFF', [{'check_id': 'visual', 'status': 'DIFF', 'reason_code': 'VISUAL_DIFFERENCE'}])
        self.assertEqual((triage_row(diff)['bucket'], triage_row(diff)['suggestedReview']), ('HUMAN_CHECK', 'VERIFIED_OK'))
        self.assertEqual(triage_row(self.row('REVIEW', [{'check_id': 'match', 'status': 'REVIEW', 'reason_code': 'REVIEW_MATCH'}]))['reason'], 'MAPPING_REVIEW')
        self.assertEqual(triage_row(self.row('REVIEW', [{'check_id': 'a.observation.3', 'status': 'REVIEW', 'reason_code': 'HTTP_4XX'}]))['reason'], 'ERRORS_BUT_PAGE_WORKS')
        self.assertEqual(triage_row(self.row('BLOCKED', [{'check_id': 'a.document', 'status': 'BLOCKED', 'reason_code': 'LOGIN_REQUIRED'}]))['reason'], 'AUTH_REQUIRED')
        self.assertEqual(triage_row(self.row('BLOCKED', [{'check_id': 'a.c', 'status': 'BLOCKED', 'reason_code': 'INSUFFICIENT_DATA'}]))['reason'], 'DATA_PRECONDITION')
        self.assertEqual(triage_row(self.row('ERROR', [{'check_id': 'a.c', 'status': 'ERROR', 'reason_code': 'NAVIGATION_ERROR'}]))['bucket'], 'RETEST')

    def test_apply_totals_and_csv_columns(self):
        report = {'results': [self.row('PASS', []), self.row('DIFF', [])], 'totals': {}}
        report['results'][1]['id'] = 'r2'
        apply_triage(report)
        self.assertEqual(report['totals']['triage'], {'ISSUE': 0, 'HUMAN_CHECK': 1, 'RETEST': 0, 'OK': 1, 'NOT_RUN': 0})
        header = csv_report({'id': 'run', 'report': report}).decode('utf-8').splitlines()[0]
        self.assertIn('검수 분류', header)
        self.assertIn('분류 사유', header)


if __name__ == '__main__':
    unittest.main()
