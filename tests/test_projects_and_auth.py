"""Project settings storage (1105_mia) + 인증 상태(로그인/비로그인) 분할 검사."""
import http.client
import json
import os
import tempfile
import threading
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from app import Server
from qa import projects_db, rules_db
from qa.config import parse_options
from qa.engine import is_login_url, run_scan
from qa.policy import login_action
from qa.secrets import load_credentials
from qa.triage import triage_row

PG_KEYS = ('PGHOST', 'PGPORT', 'PGDATABASE', 'PGUSER', 'PGPASSWORD', 'QA_CREDENTIAL_KEY')
LOGIN_KEYS = ('QA_LOGIN_ID', 'QA_LOGIN_PW', 'QA_LOGIN_A_ID', 'QA_LOGIN_A_PW', 'QA_LOGIN_B_ID', 'QA_LOGIN_B_PW', 'QA_SECRETS_FILE')


class IsolatedStore:
    """File backend in a temp folder: no PostgreSQL, no real .env, no real secrets file."""

    def __enter__(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.env = patch.dict(os.environ, {'QA_PROJECTS_FILE': str(root / 'projects.json'), 'QA_ENV_FILE': str(root / '.env'),
                                           'QA_RULES_FILE': str(root / 'rules.json'),
                                           'QA_SECRETS_FILE': str(root / 'missing-accounts.json')})
        self.env.start()
        for key in (*PG_KEYS, *LOGIN_KEYS[:-1]):
            os.environ.pop(key, None)
        self.root = root
        return self

    def __exit__(self, *exc):
        self.env.stop()
        self.temp.cleanup()


def project(password='', login_url='', clear=False, env_id=None):
    env_id = env_id or str(uuid.uuid4())
    return {'id': PROJECT_ID, 'name': '초등 PC',
            'environments': [{'id': env_id, 'name': '운영', 'url': 'https://e.example.test/', 'loginUrl': login_url,
                              'loginId': 'qa-tester', 'password': password, 'clearPassword': clear}]}


PROJECT_ID = str(uuid.uuid4())


class ProjectStoreTests(unittest.TestCase):
    def test_file_backend_round_trip_never_exposes_password(self):
        with IsolatedStore() as store:
            self.assertEqual(projects_db.backend(), 'file')
            env_id = str(uuid.uuid4())
            saved = projects_db.save_project(project('s3cret!', 'https://e.example.test/login', env_id=env_id))
            self.assertTrue(saved['environments'][0]['hasPassword'])
            listed = json.dumps(projects_db.list_projects(), ensure_ascii=False)
            self.assertNotIn('s3cret!', listed)
            self.assertNotIn('Ciphertext', listed)
            on_disk = (store.root / 'projects.json').read_text(encoding='utf-8')
            self.assertNotIn('s3cret!', on_disk)  # encrypted at rest
            self.assertIn('QA_CREDENTIAL_KEY=', (store.root / '.env').read_text(encoding='utf-8'))
            self.assertEqual(projects_db.environment_credentials(PROJECT_ID, env_id),
                             ('qa-tester', 's3cret!', 'https://e.example.test/login'))
            # Empty password keeps the stored one; clearPassword removes it.
            projects_db.save_project(project('', env_id=env_id))
            self.assertEqual(projects_db.environment_credentials(PROJECT_ID, env_id)[1], 's3cret!')
            projects_db.save_project(project('', clear=True, env_id=env_id))
            self.assertIsNone(projects_db.environment_credentials(PROJECT_ID, env_id)[1])
            self.assertTrue(projects_db.delete_project(PROJECT_ID))
            self.assertEqual(projects_db.list_projects(), [])

    def test_validation_rejects_credentialed_urls(self):
        with IsolatedStore():
            bad = project()
            bad['environments'][0]['url'] = 'https://user:pw@e.example.test/'
            with self.assertRaises(ValueError):
                projects_db.save_project(bad)
            with self.assertRaises(ValueError):
                projects_db.save_project({'id': 'not-a-uuid', 'name': 'x', 'environments': []})

    def test_project_credentials_rank_between_side_and_shared_env(self):
        with IsolatedStore():
            env_id = str(uuid.uuid4())
            projects_db.save_project(project('env-pass', env_id=env_id))
            ref = {'projectId': PROJECT_ID, 'environmentId': env_id}
            found = load_credentials('a', project_ref=ref, environ={'QA_LOGIN_ID': 'shared', 'QA_LOGIN_PW': 'shared-pw'})
            self.assertEqual((found.password, found.source), ('env-pass', 'project:environment'))
            self.assertNotIn('env-pass', repr(found))
            side = load_credentials('a', project_ref=ref, environ={'QA_LOGIN_A_ID': 'side', 'QA_LOGIN_A_PW': 'side-pw'})
            self.assertEqual(side.password, 'side-pw')
            self.assertIsNone(load_credentials('a', project_ref={'projectId': PROJECT_ID, 'environmentId': str(uuid.uuid4())},
                                               environ={}))


def rule(rule_id=None, key='notice.empty', ready=True, project_id=None):
    condition = {'id': key, 'case': 'custom', 'selector': '#empty', 'kind': 'visible', 'expected': True, 'preconditions': []} \
        if ready else {'id': key}
    return {'id': rule_id or str(uuid.uuid4()), 'projectId': project_id or PROJECT_ID, 'name': '빈 목록 안내',
            'condition': condition, 'caseData': {'steps': '목록 열기'}, 'automationReady': ready, 'enabled': True,
            'source': {'fileName': 'qa.xlsx', 'sheet': 'TC', 'row': 3, 'caseId': 'TC-01'}}


class RuleStoreTests(unittest.TestCase):
    def test_file_backend_rules_follow_project_lifecycle(self):
        with IsolatedStore():
            projects_db.save_project(project())
            first = rule()
            self.assertEqual(rules_db.save_rules([first, rule(key='manual.case', ready=False)]), 2)
            listed = {item['condition']['id']: item for item in rules_db.list_rules()}
            self.assertTrue(listed['notice.empty']['enabled'])
            self.assertFalse(listed['manual.case']['enabled'])  # 매핑 필요 케이스는 활성화되지 않음
            self.assertEqual(listed['notice.empty']['source']['caseId'], 'TC-01')
            with self.assertRaises(rules_db.RuleConflict):
                rules_db.save_rules([rule(key='notice.empty')])
            with self.assertRaises(ValueError):
                rules_db.save_rules([rule(project_id=str(uuid.uuid4()))])
            self.assertTrue(rules_db.delete_rule(first['id']))
            projects_db.delete_project(PROJECT_ID)
            self.assertEqual(rules_db.list_rules(), [])


class AuthModeOptionTests(unittest.TestCase):
    origin = 'http://127.0.0.1:1'

    def parse(self, **data):
        return parse_options({'profileId': 'synthetic-demo', **data}, self.origin)

    def test_one_authoritative_mode(self):
        self.assertEqual(self.parse()['auth_mode'], 'anonymous')
        login = self.parse(authMode='login')
        self.assertEqual(login['auth_mode'], 'login')
        self.assertTrue(login['login']['auto'])
        anonymous = self.parse(authMode='anonymous', login={'accountKey': 'default'}, manualLogin=True)
        self.assertEqual((anonymous['login'], anonymous['manual_login']), (None, False))
        manual = self.parse(authMode='manual', login={'accountKey': 'default'})
        self.assertEqual((manual['login'], manual['manual_login']), (None, True))
        self.assertEqual(self.parse(manualLogin=True)['auth_mode'], 'manual')  # legacy payloads keep working
        with self.assertRaises(ValueError):
            self.parse(authMode='guest')

    def test_credential_refs_are_ids_only(self):
        ref = {'projectId': str(uuid.uuid4()), 'environmentId': str(uuid.uuid4())}
        self.assertEqual(self.parse(authMode='login', credentialRefs={'a': ref})['credential_refs'], {'a': ref})
        self.assertEqual(self.parse(authMode='anonymous', credentialRefs={'a': ref})['credential_refs'], {})
        with self.assertRaises(ValueError):
            self.parse(authMode='login', credentialRefs={'a': {**ref, 'password': 'x'}})
        with self.assertRaises(ValueError):
            self.parse(authMode='login', credentialRefs={'a': {'projectId': 'x', 'environmentId': 'y'}})

    def test_login_heuristics(self):
        for url in ('https://v.test/login', 'https://v.test/member/login.do', 'https://mv.test/#/login', 'https://v.test/signin?next=/'):
            self.assertTrue(is_login_url(url), url)
        for url in ('https://v.test/', 'https://v.test/loginfo', 'https://mv.test/#/notice/1', 'https://v.test/blog/logins-guide'):
            self.assertFalse(is_login_url(url), url)
        self.assertTrue(login_action({'label': '로그인'}))
        self.assertFalse(login_action({'label': '로그인 없이 둘러보기'}))


class AuthModeBrowserTests(unittest.TestCase):
    def crawl(self, environ, **extra):
        temporary_root = Path(__file__).resolve().parents[1] / 'output' / 'tmp'
        temporary_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temporary_root) as directory, IsolatedStore():
            runs = Path(directory) / 'runs'
            server = Server(('127.0.0.1', 0), runs_dir=runs)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            try:
                setup = extra.pop('setup', None)
                if setup:
                    extra.update(setup(server.base_origin))
                options = parse_options({'profileId': 'custom', 'operatorId': 'auth-mode', 'testType': 'single', 'mode': 'visual',
                                         'baselineUrl': server.base_origin + '/demo/a/?members=1',
                                         'allowedPaths': ['/demo/a/', '/demo/a/mypage', '/demo/a/login'],
                                         'maxPages': 4, 'maxDepth': 1, 'maxActions': 0, 'timeoutSeconds': 90,
                                         'instanceSampleLimit': 1, **extra}, server.base_origin)
                with patch.dict(os.environ, environ):
                    return run_scan(options, str(uuid.uuid4()), runs, lambda message: None, lambda: False)
            finally:
                server.shutdown()
                server.server_close()

    def mypage(self, report):
        return next(row for row in report['results'] if row['region_id'] == 'page' and 'mypage' in row['key'])

    def test_anonymous_mode_returns_from_login_redirect_and_never_passes(self):
        report = self.crawl({})
        row = self.mypage(report)
        auth = next(c for c in row['checks'] if c['check_id'] == 'a.auth')
        self.assertEqual((auth['status'], auth['reason_code']), ('SKIP', 'LOGIN_REQUIRED_ANONYMOUS'))
        self.assertEqual(row['status'], 'SKIP')
        self.assertEqual(triage_row(row)['bucket'], 'NOT_RUN')
        self.assertTrue(auth['actual']['returnTo'].endswith('/demo/a/?members=1'), auth['actual'])  # the page that linked here
        self.assertTrue(auth['actual']['landedUrl'].endswith('/demo/a/login'))
        self.assertEqual(report['manifest']['auth']['mode'], 'anonymous')
        self.assertEqual(report['manifest']['auth']['events']['a'][0]['result'], 'RETURNED_TO_PREVIOUS')
        self.assertTrue(row['baseline'].get('screenshot'), 'login redirect keeps screenshot evidence')

    def test_login_mode_with_project_environment_credentials(self):
        env_id = str(uuid.uuid4())

        def setup(origin):
            projects_db.save_project({'id': PROJECT_ID, 'name': 'demo', 'environments': [
                {'id': env_id, 'name': 'A', 'url': origin + '/demo/a/', 'loginUrl': origin + '/demo/a/login',
                 'loginId': 'qa-project', 'password': 'demo-pass'}]})
            return {}

        report = self.crawl({}, setup=setup, authMode='login',
                            credentialRefs={'a': {'projectId': PROJECT_ID, 'environmentId': env_id}})
        start = next(row for row in report['results'] if row['region_id'] == 'page')
        login = next(c for c in start['checks'] if c['check_id'] == 'a.login')
        self.assertEqual((login['status'], login['reason_code']), ('PASS', 'TEST_ACCOUNT_LOGIN_OK'), login)
        self.assertEqual(login['actual']['credentials'], 'project')
        row = self.mypage(report)
        self.assertEqual(row['baseline']['title'], 'My page | Synthetic QA demo')
        self.assertFalse(any(c['check_id'] == 'a.auth' for c in row['checks']))
        self.assertEqual(report['manifest']['auth']['credentialSource'], {'a': 'PROJECT_ENVIRONMENT'})
        serialized = json.dumps(report, ensure_ascii=False)
        self.assertNotIn('demo-pass', serialized)
        self.assertNotIn('qa-project', serialized)


class ProjectApiTests(unittest.TestCase):
    def setUp(self):
        self.store = IsolatedStore().__enter__()
        self.temp = tempfile.TemporaryDirectory()
        self.server = Server(('127.0.0.1', 0), runs_dir=Path(self.temp.name) / 'runs')
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]
        self.token = self.request('GET', '/api/bootstrap')[1]['sessionToken']

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.temp.cleanup()
        self.store.__exit__()

    def request(self, method, path, body=None):
        headers = {'Host': f'127.0.0.1:{self.port}'}
        data = None
        if method == 'POST':
            headers.update({'Content-Type': 'application/json', 'X-QA-Token': self.token, 'Origin': f'http://127.0.0.1:{self.port}'})
            data = json.dumps(body or {}).encode('utf-8')
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)
        try:
            connection.request(method, path, body=data, headers=headers)
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def test_projects_api_save_list_delete(self):
        status, saved = self.request('POST', '/api/projects/save', project('api-secret'))
        self.assertEqual(status, 200, saved)
        status, listed = self.request('GET', '/api/projects')
        self.assertEqual((status, listed['storage']['backend']), (200, 'file'))
        self.assertTrue(listed['projects'][0]['environments'][0]['hasPassword'])
        self.assertNotIn('api-secret', json.dumps(listed))
        self.assertEqual(self.request('POST', '/api/projects/delete', {'id': PROJECT_ID}), (200, {'deleted': True}))

    def test_rules_api_and_excel_import(self):
        self.assertEqual(self.request('POST', '/api/projects/save', project())[0], 200)
        self.assertEqual(self.request('POST', '/api/rules/batch', {'rules': [rule()]}), (200, {'saved': 1}))
        status, body = self.request('POST', '/api/rules/save', rule(key='notice.empty'))
        self.assertEqual(status, 409, body)
        status, listed = self.request('GET', '/api/rules')
        self.assertEqual((status, len(listed['rules'])), (200, 1))
        from openpyxl import Workbook
        import io
        workbook = Workbook(); sheet = workbook.active
        sheet.append(['TC ID', '제목', '판정기준']); sheet.append(['TC-9', '로그인 안내', '안내가 보인다'])
        stream = io.BytesIO(); workbook.save(stream)
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)
        connection.request('POST', '/api/rules/import', body=stream.getvalue(), headers={
            'Host': f'127.0.0.1:{self.port}', 'X-QA-Token': self.token, 'Origin': f'http://127.0.0.1:{self.port}',
            'Content-Type': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'})
        response = connection.getresponse(); imported = json.loads(response.read()); connection.close()
        self.assertEqual((response.status, imported['cases'][0]['caseId']), (200, 'TC-9'))

    def test_login_mode_without_account_is_refused_before_start(self):
        status, body = self.request('POST', '/api/scans', {'profileId': 'synthetic-demo', 'operatorId': 'QA-A', 'authMode': 'login'})
        self.assertEqual(status, 400)
        self.assertIn('로그인 검사에 쓸 계정이 없습니다', body['error'])
        self.assertIsNone(self.server.service.active)


if __name__ == '__main__':
    unittest.main()
