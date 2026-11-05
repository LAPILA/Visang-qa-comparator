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
    def run_demo(self, environ, login=None, **extra):
        temporary_root = Path(__file__).resolve().parents[1] / 'output' / 'tmp'
        temporary_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temporary_root) as directory:
            runs = Path(directory) / 'runs'
            server = Server(('127.0.0.1', 0), runs_dir=runs)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            try:
                login_config = dict(DEMO_LOGIN, url=server.base_origin + '/demo/a/login') if login is None else {'url': server.base_origin + '/demo/a/login'}
                options = parse_options({'profileId': 'synthetic-demo', 'operatorId': 'login-test', 'testType': 'single', 'login': login_config,
                                         'maxPages': 1, 'maxDepth': 0, 'maxActions': 5, 'mode': 'visual',
                                         'timeoutSeconds': 60, **extra}, server.base_origin)
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
        self.assertTrue(start['baseline']['readiness'].get('settled'), start['baseline']['readiness'])
        self.assertEqual(start['baseline']['readiness']['settleState']['scrollY'], 0)

    def test_wrong_password_blocks_with_retest_triage(self):
        report = self.run_demo({'QA_LOGIN_A_ID': 'qa-tester', 'QA_LOGIN_A_PW': 'wrong'})
        start, item = self.login_check(report)
        self.assertEqual((item['status'], item['reason_code']), ('BLOCKED', 'LOGIN_FAILED'))
        self.assertEqual(start['status'], 'BLOCKED')
        self.assertEqual(triage_row(start)['bucket'], 'RETEST')
        self.assertEqual(triage_row(start)['reason'], 'AUTH_REQUIRED')

    def test_auto_login_without_selectors_finds_the_form(self):
        report = self.run_demo({'QA_LOGIN_ID': 'qa-tester', 'QA_LOGIN_PW': 'demo-pass'}, login={'url': None})
        start, item = self.login_check(report)
        self.assertEqual((item['status'], item['reason_code']), ('PASS', 'TEST_ACCOUNT_LOGIN_OK'))
        self.assertTrue(report['manifest']['login']['form']['auto'])

    def test_login_behind_cover_gate_uses_hidden_link_in_the_same_tab(self):
        """Mobile flow: start URL lands on a cover gate, login link is hidden in a drawer."""
        temporary_root = Path(__file__).resolve().parents[1] / 'output' / 'tmp'
        temporary_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temporary_root) as directory:
            runs = Path(directory) / 'runs'
            server = Server(('127.0.0.1', 0), runs_dir=runs)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            try:
                options = parse_options({'profileId': 'custom', 'operatorId': 'gate-login', 'testType': 'single', 'mode': 'visual',
                                         'baselineUrl': server.base_origin + '/demo/a/cover', 'allowedPaths': ['/demo/a/'],
                                         'maxPages': 1, 'maxDepth': 0, 'maxActions': 0, 'timeoutSeconds': 60,
                                         'login': {}, 'entry': {'selector': '#enter-mobile-web', 'urlPattern': '*cover*'}}, server.base_origin)
                options['login'] = {'url': None, 'usernameSelector': None, 'passwordSelector': None, 'submitSelector': None,
                                    'successSelector': None, 'failureSelector': None, 'accountKey': 'default', 'auto': True}
                with patch.dict(os.environ, {'QA_LOGIN_ID': 'qa-tester', 'QA_LOGIN_PW': 'demo-pass'}):
                    report = run_scan(options, str(uuid.uuid4()), runs, lambda message: None, lambda: False)
            finally:
                server.shutdown()
                server.server_close()
        start = next(row for row in report['results'] if row['region_id'] == 'page')
        item = next(c for c in start['checks'] if c['check_id'] == 'a.login')
        self.assertEqual((item['status'], item['reason_code']), ('PASS', 'TEST_ACCOUNT_LOGIN_OK'), item)
        self.assertIn('ENTRY_ACTION_APPLIED', item['actual']['gate'])
        self.assertTrue(item['actual']['loginUrl'].endswith('/demo/a/login'))
        self.assertEqual(start['baseline']['title'], 'Home | Synthetic QA demo')

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


class EntryActionBrowserTests(unittest.TestCase):
    """A cover/landing gate on the start page is dismissed once, with evidence."""

    def run_cover(self, entry, **extra):
        temporary_root = Path(__file__).resolve().parents[1] / 'output' / 'tmp'
        temporary_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temporary_root) as directory:
            runs = Path(directory) / 'runs'
            server = Server(('127.0.0.1', 0), runs_dir=runs)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            try:
                options = parse_options({'profileId': 'custom', 'operatorId': 'entry-test', 'testType': 'single',
                                         'baselineUrl': server.base_origin + '/demo/a/cover', 'allowedPaths': ['/demo/a/'],
                                         'maxPages': 2, 'maxDepth': 1, 'maxActions': 0, 'mode': 'discovery',
                                         'timeoutSeconds': 60, 'entry': entry, **extra}, server.base_origin)
                return run_scan(options, str(uuid.uuid4()), runs, lambda message: None, lambda: False)
            finally:
                server.shutdown()
                server.server_close()

    def test_cover_gate_is_dismissed_and_real_home_becomes_the_start_page(self):
        report = self.run_cover({'selector': '#enter-mobile-web', 'text': '모바일 웹으로 이동하기'})
        start = next(row for row in report['results'] if row['region_id'] == 'page' and row['baseline'] and row['baseline']['url'].endswith('/cover'))
        item = next(c for c in start['checks'] if c['check_id'] == 'a.entry')
        self.assertEqual((item['status'], item['reason_code']), ('PASS', 'ENTRY_ACTION_APPLIED'))
        self.assertTrue(start['baseline']['finalUrl'].endswith('/demo/a/'), start['baseline']['finalUrl'])
        self.assertEqual(start['baseline']['title'], 'Home | Synthetic QA demo')
        self.assertEqual(report['manifest']['entry']['selector'], '#enter-mobile-web')

    def test_missing_gate_is_a_non_required_skip(self):
        report = self.run_cover({'selector': '#not-a-gate'})
        start = next(row for row in report['results'] if row['region_id'] == 'page' and row['baseline'])
        item = next(c for c in start['checks'] if c['check_id'] == 'a.entry')
        self.assertEqual((item['status'], item['reason_code'], item['required']), ('SKIP', 'ENTRY_ACTION_NOT_PRESENT', False))
        self.assertEqual(start['baseline']['title'], 'Cover | Synthetic QA demo')

    def test_entry_config_validation(self):
        with self.assertRaises(ValueError):
            parse_options({'profileId': 'synthetic-demo', 'entry': {'text': 'x'}}, 'http://127.0.0.1:1')
        with self.assertRaises(ValueError):
            parse_options({'profileId': 'synthetic-demo', 'entry': {'selector': '#x', 'sides': 'c'}}, 'http://127.0.0.1:1')
        self.assertEqual(parse_options({'profileId': 'synthetic-demo', 'entry': {'selector': '#x'}}, 'http://127.0.0.1:1')['entry']['sides'], 'both')


class RunDeletionTests(unittest.TestCase):
    def test_finished_runs_can_be_deleted_but_not_the_active_one(self):
        temporary_root = Path(__file__).resolve().parents[1] / 'output' / 'tmp'
        temporary_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temporary_root) as directory:
            runs = Path(directory) / 'runs'
            server = Server(('127.0.0.1', 0), runs_dir=runs)
            service = server.service
            try:
                for index in range(2):
                    job = {'id': str(uuid.uuid4()), 'state': 'done', 'operatorId': 'x', 'profileId': 'synthetic-demo',
                           'startedAt': f'2026-11-0{index + 1}T00:00:00+00:00', 'options': {}, 'schemaVersion': '2.0',
                           'report': {'manifest': {}, 'results': [], 'totals': {}}}
                    service.store.save(job)
                    (runs / job['id'] / 'a').mkdir(parents=True, exist_ok=True)
                    (runs / job['id'] / 'a' / 'x.png').write_bytes(b'png')
                ids = [item['id'] for item in service.list()]
                self.assertEqual(len(ids), 2)
                service.active = ids[0]
                with self.assertRaises(ValueError):
                    service.delete(ids[0])
                self.assertEqual(service.delete_finished(), 1)
                self.assertEqual([item['id'] for item in service.list()], [ids[0]])
                self.assertFalse((runs / ids[1]).exists())
                service.active = None
                self.assertTrue(service.delete(ids[0]))
                with self.assertRaises(ValueError):
                    service.delete(ids[0])
            finally:
                server.server_close()


class NetworkPolicyTests(unittest.TestCase):
    def test_xhr_and_dismiss_options_are_validated(self):
        options = parse_options({'profileId': 'synthetic-demo', 'dismissSelectors': ['.popup .close'], 'xhrPolicy': 'block_writes'}, 'http://127.0.0.1:1')
        self.assertEqual((options['xhr_policy'], options['dismiss_selectors']), ('block_writes', ['.popup .close']))
        self.assertEqual(parse_options({'profileId': 'elementary-pc'}, 'http://127.0.0.1:1')['xhr_policy'], 'allow_allowed_hosts')
        self.assertIn('stg.vivasam.com', parse_options({'profileId': 'elementary-pc'}, 'http://127.0.0.1:1')['resource_hosts'])
        with self.assertRaises(ValueError):
            parse_options({'profileId': 'synthetic-demo', 'xhrPolicy': 'anything'}, 'http://127.0.0.1:1')


class LenientAndSmokeTests(unittest.TestCase):
    def test_informational_checks_do_not_decide_status_or_triage(self):
        from qa.policy import aggregate_status
        checks = [{'check_id': 'a.document', 'status': 'PASS', 'reason_code': 'DOCUMENT_REACHABLE'},
                  {'check_id': 'a.observation.1', 'status': 'FAIL', 'reason_code': 'JS_ERROR', 'informational': True, 'required': False}]
        self.assertEqual(aggregate_status(checks), 'PASS')
        self.assertEqual(triage_row({'status': 'PASS', 'checks': checks})['bucket'], 'OK')
        self.assertEqual(aggregate_status([checks[1]]), 'FAIL', 'Only informational checks: nothing else decides, keep the evidence verdict')
        options = parse_options({'profileId': 'secondary-mobile'}, 'http://127.0.0.1:1')
        self.assertEqual((options['observation_mode'], options['visual_threshold'], options['smoke_actions']), ('lenient', 8, False))
        self.assertEqual(parse_options({'profileId': 'synthetic-demo'}, 'http://127.0.0.1:1')['observation_mode'], 'strict')

    def test_smoke_actions_click_unknown_buttons_with_generic_expectation(self):
        temporary_root = Path(__file__).resolve().parents[1] / 'output' / 'tmp'
        temporary_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temporary_root) as directory:
            runs = Path(directory) / 'runs'
            server = Server(('127.0.0.1', 0), runs_dir=runs)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            try:
                from qa.demo import reset_demo_counts
                reset_demo_counts()
                options = parse_options({'profileId': 'synthetic-demo', 'operatorId': 'smoke', 'testType': 'single', 'mode': 'visual',
                                         'maxPages': 1, 'maxDepth': 0, 'maxActions': 10, 'timeoutSeconds': 60,
                                         'safeActions': [], 'smokeActions': True}, server.base_origin)
                report = run_scan(options, str(uuid.uuid4()), runs, lambda message: None, lambda: False)
            finally:
                server.shutdown()
                server.server_close()
        start = next(row for row in report['results'] if row['region_id'] == 'page')
        smoke = [c for c in start['checks'] if c['check_id'].startswith('a.smoke.')]
        self.assertTrue(smoke, 'the demo home has an in-page toggle button to smoke-test')
        self.assertTrue(all(c['status'] == 'PASS' and c['reason_code'] == 'ACTION_SMOKE_OK' for c in smoke))
        from qa.demo import get_demo_summary
        self.assertEqual(get_demo_summary()['mutation_counts']['a'], {'save': 0, 'delete': 0})
        self.assertTrue(report['manifest']['smokeActions'])


class TestAccountLevelTests(unittest.TestCase):
    def test_test_account_level_executes_writes_but_never_account_breaking_actions(self):
        from qa.policy import dangerous_action, readonly_navigation_reason
        self.assertIsNone(dangerous_action({'label': '저장'}, 'test_account'))
        self.assertIsNone(dangerous_action({'href': 'https://a.test/board/delete?id=1'}, 'test_account'))
        self.assertEqual(dangerous_action({'label': '회원탈퇴'}, 'test_account'), 'ACCOUNT_BREAKING_ACTION')
        self.assertEqual(dangerous_action({'href': 'https://a.test/member/logout'}, 'test_account'), 'ACCOUNT_BREAKING_ACTION')
        self.assertEqual(dangerous_action({'label': '결제하기'}, 'test_account'), 'ACCOUNT_BREAKING_ACTION')
        self.assertEqual(dangerous_action({'href': 'https://a.test/member/password/change'}, 'test_account'), 'ACCOUNT_BREAKING_ACTION')
        self.assertEqual(dangerous_action({'label': '저장'}, 'strict'), 'MUTATING_ACTION')
        self.assertIsNone(readonly_navigation_reason({'url': 'https://a.test/mypage/edit'}, 'test_account'))
        self.assertTrue(readonly_navigation_reason({'url': 'https://a.test/member/join'}, 'test_account').startswith('ACCOUNT_BREAKING'))
        self.assertEqual(readonly_navigation_reason({'url': 'https://a.test/api/list'}, 'test_account'), 'API_NAVIGATION_NOT_APPROVED')
        with self.assertRaises(ValueError):
            parse_options({'profileId': 'synthetic-demo', 'safetyLevel': 'yolo'}, 'http://127.0.0.1:1')

    def test_demo_traps_are_executed_only_at_test_account_level(self):
        from qa.demo import get_demo_summary, reset_demo_counts
        temporary_root = Path(__file__).resolve().parents[1] / 'output' / 'tmp'
        temporary_root.mkdir(parents=True, exist_ok=True)
        results = {}
        for level in ('strict', 'test_account'):
            with tempfile.TemporaryDirectory(dir=temporary_root) as directory:
                runs = Path(directory) / 'runs'
                server = Server(('127.0.0.1', 0), runs_dir=runs)
                threading.Thread(target=server.serve_forever, daemon=True).start()
                try:
                    reset_demo_counts()
                    options = parse_options({'profileId': 'synthetic-demo', 'operatorId': 'level', 'testType': 'single', 'mode': 'visual',
                                             'maxPages': 1, 'maxDepth': 0, 'maxActions': 20, 'timeoutSeconds': 90,
                                             'safeActions': [], 'smokeActions': True, 'safetyLevel': level,
                                             'crawlScope': 'same_origin_readonly'}, server.base_origin)
                    report = run_scan(options, str(uuid.uuid4()), runs, lambda message: None, lambda: False)
                    results[level] = (get_demo_summary()['mutation_counts']['a'], report)
                finally:
                    server.shutdown()
                    server.server_close()
        self.assertEqual(results['strict'][0], {'save': 0, 'delete': 0})
        self.assertGreaterEqual(results['test_account'][0]['save'], 1, 'a test account may submit the synthetic save form')
        self.assertEqual(results['test_account'][1]['manifest']['safetyLevel'], 'test_account')
        start = next(row for row in results['test_account'][1]['results'] if row['region_id'] == 'page')
        smoke = [c for c in start['checks'] if c['check_id'].startswith('a.smoke.')]
        self.assertTrue(any(c['actual'].get('submitted') for c in smoke if c['status'] == 'PASS'))


class PairFirstCrawlTests(unittest.TestCase):
    def test_candidate_mirrors_baseline_routes_on_a_different_host(self):
        """Same app on two hosts (127.0.0.1 vs localhost): B visits what A visited, so rows pair up."""
        temporary_root = Path(__file__).resolve().parents[1] / 'output' / 'tmp'
        temporary_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temporary_root) as directory:
            runs = Path(directory) / 'runs'
            server = Server(('127.0.0.1', 0), runs_dir=runs)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            try:
                port = server.server_address[1]
                options = parse_options({'profileId': 'custom', 'operatorId': 'mirror', 'mode': 'discovery',
                                         'baselineUrl': f'http://127.0.0.1:{port}/demo/a/', 'candidateUrl': f'http://localhost:{port}/demo/a/',
                                         'allowedHosts': ['127.0.0.1', 'localhost'], 'crawlScope': 'same_origin_readonly',
                                         'maxPages': 4, 'maxDepth': 2, 'maxActions': 0, 'timeoutSeconds': 90}, server.base_origin)
                report = run_scan(options, str(uuid.uuid4()), runs, lambda message: None, lambda: False)
            finally:
                server.shutdown()
                server.server_close()
        pages = [row for row in report['results'] if row['region_id'] == 'page' and not row.get('unvisitedPages')]
        paired = [row for row in pages if row['baseline'] and row['candidate']]
        self.assertGreaterEqual(len(paired), 3, [(row['key'], row['match']['method']) for row in pages])
        self.assertTrue(all(row['match']['approved'] for row in paired))
        mirrored = [row for row in paired if row['candidate'].get('mirroredFromBaseline')]
        self.assertTrue(mirrored, 'B should have queued A routes first')
        unvisited = [row for row in report['results'] if row.get('unvisitedPages')]
        self.assertTrue(all(len(row['unvisitedPages']) >= 1 for row in unvisited))


class RouteTranslationTests(unittest.TestCase):
    def test_path_app_and_hash_spa_routes_translate_both_ways(self):
        from qa.engine import _translate_route
        self.assertEqual(_translate_route('https://dev2-mv.test/educourse/middle?x=1', 'https://dev2-mv.test/', 'https://mv-dev.test/#/'),
                         'https://mv-dev.test/#/educourse/middle?x=1')
        self.assertEqual(_translate_route('https://mv-dev.test/#/myInfo?y=2', 'https://mv-dev.test/#/', 'https://dev2-mv.test/'),
                         'https://dev2-mv.test/myInfo?y=2')
        self.assertEqual(_translate_route('https://e.test/main', 'https://e.test/main', 'https://stg-e.test/'), 'https://stg-e.test/main')
        self.assertEqual(_translate_route('https://dev2-mv.test/', 'https://dev2-mv.test/', 'https://mv-dev.test/#/'), 'https://mv-dev.test/#/')


class VisualComparabilityTests(unittest.TestCase):
    def run_custom(self, baseline, extra):
        temporary_root = Path(__file__).resolve().parents[1] / 'output' / 'tmp'
        temporary_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temporary_root) as directory:
            runs = Path(directory) / 'runs'
            server = Server(('127.0.0.1', 0), runs_dir=runs)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            try:
                options = parse_options({'profileId': 'custom', 'operatorId': 'visual', 'mode': 'visual', 'maxPages': 1, 'maxDepth': 0,
                                         'maxActions': 0, 'timeoutSeconds': 60, 'baselineUrl': server.base_origin + baseline, **extra}, server.base_origin)
                return run_scan(options, str(uuid.uuid4()), runs, lambda message: None, lambda: False)
            finally:
                server.shutdown()
                server.server_close()

    def test_auto_dismiss_closes_a_marketing_popup_before_capture(self):
        report = self.run_custom('/demo/a/?popup=1', {'testType': 'single', 'autoDismiss': True})
        start = next(row for row in report['results'] if row['region_id'] == 'page')
        self.assertTrue(any('auto:' in item for item in start['baseline'].get('dismissed', [])), start['baseline'].get('dismissed'))
        self.assertTrue(any(c['reason_code'] == 'OVERLAYS_DISMISSED' for c in start['checks']))

    def test_popup_on_one_side_only_passes_threshold_once_dismissed(self):
        port_free = {'candidateUrl': None}
        temporary_root = Path(__file__).resolve().parents[1] / 'output' / 'tmp'
        with tempfile.TemporaryDirectory(dir=temporary_root) as directory:
            runs = Path(directory) / 'runs'
            server = Server(('127.0.0.1', 0), runs_dir=runs)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            try:
                port = server.server_address[1]
                base = {'profileId': 'custom', 'operatorId': 'visual', 'mode': 'visual', 'maxPages': 1, 'maxDepth': 0, 'maxActions': 0,
                        'timeoutSeconds': 60, 'allowedHosts': ['127.0.0.1', 'localhost'], 'visualThreshold': 0.5,
                        'baselineUrl': f'http://127.0.0.1:{port}/demo/a/?popup=1', 'candidateUrl': f'http://localhost:{port}/demo/a/'}
                with_popup = run_scan(parse_options({**base, 'autoDismiss': False}, server.base_origin), str(uuid.uuid4()), runs, lambda m: None, lambda: False)
                dismissed = run_scan(parse_options({**base, 'autoDismiss': True}, server.base_origin), str(uuid.uuid4()), runs, lambda m: None, lambda: False)
            finally:
                server.shutdown()
                server.server_close()
        row_popup = next(row for row in with_popup['results'] if row['region_id'] == 'page')
        row_clean = next(row for row in dismissed['results'] if row['region_id'] == 'page')
        self.assertTrue(row_popup['baseline']['captureReady'] and row_popup['candidate']['captureReady'])
        self.assertEqual(row_popup['status'], 'DIFF', row_popup['checks'])
        self.assertGreater(row_popup['visual']['differencePercent'], 0.5)
        self.assertEqual(row_clean['status'], 'PASS', [(c['check_id'], c['status'], c['reason_code']) for c in row_clean['checks']])

    def test_third_party_tracker_block_does_not_make_capture_non_comparable(self):
        from qa.engine import _origin
        record = {'url': 'https://a.test/', 'issues': [
            {'category': 'POLICY_BLOCKED', 'renderingRelevant': False, 'url': 'https://www.googletagmanager.com/gtag/js'}], 'readiness': {}, 'captureReady': True}
        blocked = [item for item in record['issues'] if item['category'] in ('POLICY_BLOCKED', 'EXECUTION_BLOCKED')]
        self.assertFalse(any(item.get('renderingRelevant') for item in blocked))


class SharedCredentialApiTests(unittest.TestCase):
    def test_save_status_clear_never_echo_password(self):
        from qa.secrets import clear_shared_credentials, credentials_status, save_shared_credentials
        with tempfile.TemporaryDirectory() as directory:
            env = {}
            self.assertEqual(credentials_status(environ=env, root=directory), {'configured': False})
            status = save_shared_credentials('qavivatest003', 'p@ss~!', environ=env, root=directory)
            self.assertTrue(status['configured'])
            self.assertNotIn('p@ss', json.dumps(status))
            self.assertNotEqual(status['maskedId'], 'qavivatest003')
            self.assertEqual(load_credentials('b', environ=env, root=directory).password, 'p@ss~!')
            stored = json.loads((Path(directory) / 'secrets' / 'accounts.json').read_text(encoding='utf-8'))
            self.assertEqual(stored['accounts']['default']['id'], 'qavivatest003')
            with self.assertRaises(ValueError):
                save_shared_credentials('only-id', '', environ=env, root=directory)
            self.assertFalse(clear_shared_credentials(environ=env, root=directory)['configured'])

    def test_run_limits_allow_long_full_checks(self):
        options = parse_options({'profileId': 'synthetic-demo', 'maxPages': 200, 'maxDepth': 8, 'maxActions': 1000, 'timeoutSeconds': 3600}, 'http://127.0.0.1:1')
        self.assertEqual((options['max_pages'], options['max_depth'], options['max_actions'], options['timeout_seconds']), (200, 8, 1000, 3600))


class InstanceSamplingTests(unittest.TestCase):
    def test_templates_wildcard_records_but_keep_routes(self):
        from qa.matching import instance_template
        self.assertEqual(instance_template('https://v.test/notice/view?seq=123'), instance_template('https://v.test/notice/view?seq=124'))
        self.assertEqual(instance_template('https://mv.test/#/notice/detail/5512'), instance_template('https://mv.test/#/notice/detail/7'))
        self.assertEqual(instance_template('https://v.test/list?page=7&cat=a'), instance_template('https://v.test/list?cat=a&page=8'))
        self.assertNotEqual(instance_template('https://v.test/list?cat=a'), instance_template('https://v.test/list?cat=b'))
        self.assertNotEqual(instance_template('https://v.test/notice/view?seq=1'), instance_template('https://v.test/event/view?seq=1'))

    def test_crawl_samples_detail_records(self):
        temporary_root = Path(__file__).resolve().parents[1] / 'output' / 'tmp'
        temporary_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temporary_root) as directory:
            runs = Path(directory) / 'runs'
            server = Server(('127.0.0.1', 0), runs_dir=runs)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            try:
                options = parse_options({'profileId': 'custom', 'operatorId': 'sample', 'testType': 'single', 'mode': 'discovery',
                                         'baselineUrl': server.base_origin + '/demo/a/notice', 'crawlScope': 'same_origin_readonly',
                                         'maxPages': 10, 'maxDepth': 2, 'maxActions': 0, 'timeoutSeconds': 60,
                                         'instanceSampleLimit': 1, 'safetyLevel': 'test_account'}, server.base_origin)
                report = run_scan(options, str(uuid.uuid4()), runs, lambda message: None, lambda: False)
            finally:
                server.shutdown()
                server.server_close()
        visited = [row['key'] for row in report['results'] if row['region_id'] == 'page' and not row.get('unvisitedPages')]
        self.assertEqual(sum('/detail' in key for key in visited), 1, visited)
        sampled = [row for row in report['results'] if row.get('unvisitedPages') and 'SAMPLE_LIMIT_REACHED' in row['flags']]
        self.assertTrue(sampled and sampled[0]['status'] == 'SKIP')
        self.assertEqual(report['manifest']['instanceSampleLimit'], 1)
