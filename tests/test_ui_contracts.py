"""Browser contracts for purposes, evidence filters and legacy report display.

The application serves its real UI/bootstrap. Scan/review responses are synthetic
fixtures so these tests do not claim to validate the browser worker itself.
"""
import copy
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright

from app import Server


STATES = ['PASS', 'FAIL', 'DIFF', 'SKIP', 'BLOCKED', 'ERROR', 'REVIEW']
CURRENT = '11111111-1111-4111-8111-111111111111'
LEGACY = '22222222-2222-4222-8222-222222222222'
CONDITION = {'id': 'notice.empty', 'case': 'empty', 'url_pattern': '/demo/*',
             'selector': '#empty-state', 'kind': 'visible', 'expected': True,
             'preconditions': [{'selector': '#notice-list li', 'kind': 'count', 'expected': {'equals': 0}}]}
ENVIRONMENT_IDS = ['production', 'staging', 'vibe-dev', 'legacy-dev']
ENVIRONMENT_LABELS = ['운영', 'STG', '바이브 개발', '레거시 개발']
REGISTERED_URLS = {
    'elementary-pc': ['https://e.vivasam.com/main', 'https://stg-e.vivasam.com/',
                      'https://dev2-e.vivasam.com/main', 'https://e-dev.vivasam.com/'],
    'secondary-pc': ['https://v.vivasam.com/main', 'https://stg-v.vivasam.com/',
                     'https://dev2-v.vivasam.com/main', 'https://v-dev.vivasam.com/'],
    'elementary-mobile': ['https://me.vivasam.com/', 'https://stg-me.vivasam.com/',
                          'https://dev2-me.vivasam.com/', 'https://me-dev.vivasam.com/#/'],
    'secondary-mobile': ['https://mv.vivasam.com/', 'https://stg-mv.vivasam.com/',
                         'https://dev2-mv.vivasam.com/', 'https://mv-dev.vivasam.com/#/'],
}


def report_fixture():
    rows, findings = [], []
    categories = ['STRUCTURE', 'RESOURCE', 'VISUAL', 'TEST_INFRA', 'AUTH', 'TEST_INFRA', 'DATA']
    for index, status in enumerate(STATES):
        environment = 'b' if index == 1 else 'a'
        subtype = f'{categories[index]}_SAMPLE'
        finding_id = f'f-{index}'
        finding = {'id': finding_id, 'fingerprint': f'fingerprint-{index}', 'category': categories[index],
                   'subtype': subtype, 'severity': 'HIGH' if status == 'FAIL' else 'LOW', 'status': status,
                   'summary': f'{status} 합성 관찰 <script>non-executable</script>', 'environment': environment,
                   'pageKey': f'/page-{index}', 'checkId': f'check-{index}', 'occurrenceCount': 3,
                   'firstSeenAt': '2026-11-03T09:00:00+09:00', 'lastSeenAt': '2026-11-03T09:00:01+09:00',
                   'evidence': [], 'tags': ['HTTP_404'] if status == 'FAIL' else []}
        findings.append(finding)
        site = {'url': 'http://127.0.0.1/demo/', 'finalUrl': 'http://127.0.0.1/demo/', 'title': '합성 페이지',
                'statusCode': 200, 'issues': [], 'actions': []}
        rows.append({'id': f'r-{index}', 'key': f'/page-{index}', 'status': status, 'flags': [],
                     'baseline': site, 'candidate': copy.deepcopy(site), 'region_id': 'notice' if index < 3 else 'other',
                     'visual': {'differencePercent': [0, None, 4, None, None, None, 1][index]},
                     'checks': [{'check_id': f'check-{index}', 'status': status, 'reason_code': 'SYNTHETIC',
                                 'expected': True, 'actual': status == 'PASS', 'preconditions': []}],
                     'findingIds': [finding_id], 'categories': [categories[index]], 'subtypes': [subtype],
                     'severity': finding['severity'], 'regression': {'classification': 'NEW' if index == 1 else 'RECURRING', 'classifications': ['NEW', 'RECURRING'] if index == 1 else ['RECURRING']},
                     'review': {'status': 'UNREVIEWED', 'revision': 0, 'events': []}})
    totals = {status.lower(): 1 for status in STATES}
    totals.update(resultRows=7, pages=7, baselineVisited=1, candidateVisited=1, assertions=2,
                  rawObservations=21, uniqueFindings=7, linkedIssues=0, discoveredActions=3,
                  executedActions=0, blockedActions=3, checkStatusCounts={status: 1 for status in STATES})
    return {'schemaVersion': '2.0', 'testType': 'comparison', 'totals': totals, 'results': rows, 'findings': findings}


class WorkspaceContractBrowserTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parents[1]
        temporary_root = self.root / 'output' / 'tmp'
        temporary_root.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=temporary_root)
        self.server = Server(('127.0.0.1', 0), runs_dir=Path(self.temporary.name) / 'runs')
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch(timeout=20000)
        self.context = self.browser.new_context(viewport={'width': 1440, 'height': 1000}, locale='ko-KR')
        self.page = self.context.new_page()
        self.page_errors, self.external_requests, self.posts, self.reviews = [], [], [], []
        self.bootstrap_profile_overrides = {}
        self.page.on('pageerror', lambda error: self.page_errors.append(str(error)))
        self.jobs = {CURRENT: {'id': CURRENT, 'state': 'done', 'testType': 'comparison', 'profileId': 'synthetic-demo',
                               'operatorId': 'QA-fixture', 'startedAt': '2026-11-03T09:00:00+09:00', 'report': report_fixture()}}
        legacy_report = {'totals': {'pages': 2, 'review': 1, 'skip': 1}, 'results': [
            {'id': 'legacy-review', 'key': '/legacy', 'status': 'REVIEW', 'flags': ['VISUAL_DIFF'],
             'visual': {'differencePercent': 6}, 'checks': [], 'review': {'status': 'UNREVIEWED', 'revision': 0, 'events': []}},
            {'id': 'legacy-skip', 'key': '/legacy-auth', 'status': 'SKIP', 'flags': ['LOGIN_REQUIRED'],
             'checks': [], 'review': {'status': 'UNREVIEWED', 'revision': 0, 'events': []}}]}
        self.jobs[LEGACY] = {'id': LEGACY, 'state': 'done', 'profileId': 'custom', 'operatorId': 'QA-legacy',
                             'startedAt': '2026-10-30T09:00:00+09:00', 'report': legacy_report}
        self.context.route('**/*', self.route)

    def tearDown(self):
        self.context.close()
        self.browser.close()
        self.playwright.stop()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        self.temporary.cleanup()

    def route(self, route):
        request = route.request
        parts = urlsplit(request.url)
        if parts.netloc != urlsplit(self.server.base_origin).netloc:
            self.external_requests.append(request.url)
            route.abort()
            return
        if parts.path == '/api/bootstrap' and self.bootstrap_profile_overrides:
            response = route.fetch()
            data = response.json()
            for profile in data['profiles']:
                profile.update(copy.deepcopy(self.bootstrap_profile_overrides.get(profile['id'], {})))
            route.fulfill(status=200, content_type='application/json', body=json.dumps(data, ensure_ascii=False))
            return
        if not parts.path.startswith('/api/scans'):
            route.continue_()
            return
        if request.method == 'POST':
            self.assertEqual(request.headers.get('x-qa-token'), self.server.session_token)
        if parts.path == '/api/scans' and request.method == 'GET':
            data = {'scans': [{key: value for key, value in job.items() if key != 'report'} for job in self.jobs.values()]}
        elif parts.path == '/api/scans' and request.method == 'POST':
            payload = request.post_data_json
            self.posts.append(payload)
            job = self.jobs[CURRENT]
            job['testType'] = payload['testType']
            job['report']['testType'] = payload['testType']
            if payload['testType'] != 'comparison':
                for row in job['report']['results']:
                    row['candidate'] = None
            data = {'id': CURRENT}
        elif parts.path.endswith('/reviews'):
            payload = request.post_data_json
            self.reviews.append(payload)
            row = next(row for row in self.jobs[CURRENT]['report']['results'] if row['id'] == payload['resultId'])
            row['review'] = {'status': payload['status'], 'revision': payload['expectedRevision'] + 1,
                             'issueRef': payload.get('issueRef', ''), 'events': [dict(payload, timestamp='2026-11-03T09:05:00+09:00')]}
            self.jobs[CURRENT]['report']['totals']['linkedIssues'] = int(bool(payload.get('issueRef')))
            data = {'review': row['review']}
        else:
            data = self.jobs.get(parts.path.rsplit('/', 1)[-1])
            if data is None:
                route.fulfill(status=404, content_type='application/json', body='{}')
                return
        route.fulfill(status=200, content_type='application/json', body=json.dumps(data, ensure_ascii=False))

    def open(self):
        self.page.goto(self.server.base_origin)
        expect(self.page.locator('#startBtn')).to_be_enabled()
        self.page.locator('#operatorId').fill('QA-purpose')

    def submit(self, expected_count):
        self.page.locator('#startBtn').click()
        expect(self.page.locator('#resultSection')).to_be_visible()
        expect(self.page.locator('#startBtn')).to_be_enabled()
        self.assertEqual(len(self.posts), expected_count)

    def reset_filters(self):
        self.page.locator('[data-filter="ALL"]').click()
        for field in ['regionFilter', 'testTypeFilter', 'environmentFilter', 'categoryFilter', 'subtypeFilter',
                      'severityFilter', 'reviewStatusFilter', 'regressionFilter']:
            self.page.locator('#' + field).select_option('ALL')
        self.page.locator('#searchFilter').fill('')

    def test_four_purpose_payloads_exclude_unneeded_b_and_require_inputs(self):
        self.open()
        expect(self.page.locator('#crawlScope')).to_have_value('approved_paths')
        self.page.get_by_text('고급 설정 · 페이지 매핑, 영역, 허용 동작', exact=True).click()
        self.page.locator('#profileId').select_option('elementary-mobile')
        expect(self.page.locator('#pairStartPages')).to_be_checked()
        self.assertIn('code.jquery.com', self.page.locator('#resourceHosts').input_value().splitlines())
        self.page.locator('#profileId').select_option('synthetic-demo')
        original_urls = [self.page.locator('#' + field).input_value() for field in ['baselineUrl', 'candidateUrl']]
        self.page.locator('#baselineName').fill('운영')
        self.page.locator('#candidateName').fill('DEV2')
        self.assertEqual([self.page.locator('#' + field).input_value() for field in ['baselineUrl', 'candidateUrl']], original_urls)
        self.page.locator('#crawlScope').select_option('same_origin_readonly')
        expect(self.page.locator('#crawlScopeHint')).to_contain_text('환경 내부 읽기 전용 링크 탐색')
        expect(self.page.locator('#pairStartPages')).to_be_checked()
        self.page.locator('#allowedHosts').fill('api.example.test')
        self.page.locator('#resourceHosts').fill('static.example.test\ncdn.example.test')
        self.page.locator('#privateMaskSelectors').fill('[".account-name"]')
        self.submit(1)
        self.assertEqual(self.posts[-1]['testType'], 'comparison')
        self.assertTrue(self.posts[-1]['candidateUrl'])
        self.assertTrue(self.posts[-1]['pairStartPages'])
        self.assertEqual(self.posts[-1]['baselineName'], '운영')
        self.assertEqual(self.posts[-1]['candidateName'], 'DEV2')
        self.assertEqual(self.posts[-1]['crawlScope'], 'same_origin_readonly')
        self.assertEqual(self.posts[-1]['allowedHosts'], ['api.example.test'])
        self.assertEqual(self.posts[-1]['resourceHosts'], ['static.example.test', 'cdn.example.test'])
        self.assertEqual(self.posts[-1]['privateMaskSelectors'], ['.account-name'])
        self.page.locator('#pairStartPages').uncheck()
        self.submit(2)
        self.assertFalse(self.posts[-1]['pairStartPages'])
        self.page.locator('#candidateUrl').fill('not-a-valid-url')
        self.page.locator('#testType').select_option('single')
        expect(self.page.locator('#candidateUrl')).to_be_disabled()
        expect(self.page.locator('#candidateField')).to_be_hidden()
        expect(self.page.locator('#candidateNameField')).to_be_hidden()
        expect(self.page.locator('#candidateName')).to_be_disabled()
        expect(self.page.locator('#candidateEnvironmentField')).to_be_hidden()
        expect(self.page.locator('#candidateEnvironmentId')).to_be_disabled()
        expect(self.page.locator('#pairStartPagesField')).to_be_hidden()
        self.submit(3)
        self.assertNotIn('candidateUrl', self.posts[-1])
        self.assertNotIn('candidateName', self.posts[-1])
        self.assertNotIn('candidateEnvironmentId', self.posts[-1])
        self.assertNotIn('pairStartPages', self.posts[-1])
        self.assertEqual(self.posts[-1]['testType'], 'single')
        self.page.locator('#testType').select_option('regression')
        expect(self.page.locator('#previousRunId')).to_be_visible()
        self.page.locator('#startBtn').click()
        expect(self.page.locator('#previousRunId')).to_be_focused()
        self.assertEqual(len(self.posts), 3)
        self.page.locator('#previousRunId').select_option(LEGACY)
        self.submit(4)
        self.assertEqual(self.posts[-1]['previousRunId'], LEGACY)
        self.assertNotIn('candidateUrl', self.posts[-1])
        self.page.locator('#testType').select_option('conditional')
        expect(self.page.locator('#conditionsPanel')).to_be_visible()
        self.page.locator('#conditions').fill('[]')
        self.page.locator('#startBtn').click()
        expect(self.page.locator('#errorSection')).to_contain_text('conditions')
        self.assertEqual(len(self.posts), 4)
        self.page.locator('#conditions').fill(json.dumps([CONDITION]))
        self.submit(5)
        self.assertEqual(self.posts[-1]['conditions'], [CONDITION])
        self.assertNotIn('candidateUrl', self.posts[-1])
        self.assertNotIn('previousRunId', self.posts[-1])
        self.assertEqual(self.page_errors, [])
        self.assertEqual(self.external_requests, [])

    def test_start_pair_discovery_explanations_and_restore_settings_preserve_evidence(self):
        report = self.jobs[CURRENT]['report']
        report['manifest'] = {'mode': 'discovery'}
        for row in report['results']:
            row['visual']['differencePercent'] = None
        first = report['results'][0]
        first['key'] = 'start-page'
        first['baseline']['title'] = '운영 홈'
        first['candidate']['title'] = '개발 메인'
        first['match'] = {'method': 'SELECTED_START_PAGES', 'reason': 'START_URLS_DECLARED_EQUIVALENT',
                          'confidence': 'EXPLICIT', 'approved': True}
        first['baseline']['issues'] = [
            {'category': category, 'level': 'REVIEW', 'message': '합성 관찰 메시지', 'source': 'BROWSER',
             'policyInterference': True, 'causeConfirmed': False,
             'relatedBlockedRequests': [{'url': 'https://cdn.example.test/script.js', 'method': 'GET',
                                         'resourceType': 'script', 'reason': 'HOST_NOT_ALLOWED'}]}
            for category in ['JS_ERROR_AFTER_POLICY_BLOCK', 'CONSOLE_ERROR_AFTER_POLICY_BLOCK']]
        report['findings'][0].update(category='TEST_INFRA', subtype='POLICY_INTERFERENCE',
                                     observations=copy.deepcopy(first['baseline']['issues']))
        # Old settings deliberately omit the two newly introduced options.
        self.jobs[CURRENT]['options'] = {
            'profile_id': 'elementary-mobile', 'operator_id': 'QA-restored',
            'baseline_url': 'https://dev-a.example.test/#/', 'candidate_url': 'https://dev-b.example.test/',
            'test_type': 'comparison', 'mode': 'discovery', 'max_pages': 2, 'max_depth': 1,
            'max_actions': 3, 'timeout_seconds': 180, 'visual_threshold': 3,
            'manual_login': True, 'route_aliases': [], 'regions': [], 'safe_actions': [],
            'scenario_ids': [], 'allowed_hosts': ['auth.example.test'], 'allowed_paths': ['/notice'],
            'private_mask_selectors': ['.account-name'], 'conditions': []}
        original_report = copy.deepcopy(report)
        self.open()
        self.page.locator('.history-item').filter(has_text='QA-fixture').click()
        expect(self.page.locator('#discoveryNotice')).to_be_visible()
        expect(self.page.locator('#resultMeta')).to_contain_text('탐색만 · 화면 비교 안 함')
        row = self.page.locator('#result-row-0')
        expect(row.locator('.diff-value')).to_have_text('미계산 · 탐색만')
        expect(row.locator('summary.row-main')).to_contain_text('A: 운영 홈 / B: 개발 메인')
        expect(row.locator('summary.row-main')).to_contain_text('A/B 대응 페이지 · 관찰: 환경 A')
        row.locator('summary.row-main').click()
        row.locator('.match-details summary').click()
        expect(row.locator('.match-details')).to_contain_text('START_URLS_DECLARED_EQUIVALENT')
        expect(row.locator('.match-details')).to_contain_text('그 밖의 탐색 페이지에는 이 규칙을 적용하지 않습니다')
        expect(row.locator('.detail-grid')).to_contain_text('차단 후 JS 오류')
        expect(row.locator('.detail-grid')).to_contain_text('차단 후 콘솔 오류')
        expect(row.locator('.detail-grid')).to_contain_text('정책 영향 가능성 / 원인 미확정')
        expect(row.locator('.detail-grid')).to_contain_text('HOST_NOT_ALLOWED')
        row.locator('.finding-card summary').click()
        expect(row.locator('.finding-card')).to_contain_text('관련 차단 요청')
        self.page.locator('#loadRunSettings').click()
        expect(self.page.locator('#baselineUrl')).to_have_value('https://dev-a.example.test/#/')
        expect(self.page.locator('#candidateUrl')).to_have_value('https://dev-b.example.test/')
        expect(self.page.locator('#operatorId')).to_have_value('QA-restored')
        expect(self.page.locator('#mode')).to_have_value('discovery')
        expect(self.page.locator('#pairStartPages')).to_be_checked()
        self.assertIn('code.jquery.com', self.page.locator('#resourceHosts').input_value().splitlines())
        expect(self.page.locator('#manualLogin')).to_be_checked()
        expect(self.page.locator('#privateMaskSelectors')).to_have_value('[\n  ".account-name"\n]')
        self.page.locator('#baselineUrl').fill('https://unrelated.example.test/')
        self.page.locator('#configureVisualMode').click()
        expect(self.page.locator('#baselineUrl')).to_have_value('https://dev-a.example.test/#/')
        expect(self.page.locator('#mode')).to_have_value('visual')
        expect(self.page.locator('#discoveryNotice')).to_be_visible()
        expect(self.page.locator('#resultMeta')).to_contain_text('탐색만 · 화면 비교 안 함')
        expect(self.page.locator('#successSection')).to_contain_text('자동으로 실행하지 않았으며 저장된 결과는 유지')
        self.assertEqual(self.posts, [])
        self.assertEqual(self.jobs[CURRENT]['report'], original_report)
        self.assertEqual(self.jobs[CURRENT]['options']['mode'], 'discovery')
        self.jobs[CURRENT]['options'].update(pair_start_pages=False, resource_hosts=['assets.example.test'])
        self.page.locator('.history-item').filter(has_text='QA-fixture').click()
        self.page.locator('#loadRunSettings').click()
        expect(self.page.locator('#pairStartPages')).not_to_be_checked()
        expect(self.page.locator('#resourceHosts')).to_have_value('assets.example.test')
        captures = self.root / 'output' / 'playwright'
        captures.mkdir(parents=True, exist_ok=True)
        self.page.screenshot(path=str(captures / 'app-start-pair-desktop.png'), full_page=True)
        self.page.set_viewport_size({'width': 390, 'height': 844})
        self.assertTrue(self.page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
        self.page.screenshot(path=str(captures / 'app-start-pair-mobile.png'), full_page=True)
        self.page.locator('.history-item').filter(has_text='QA-legacy').click()
        expect(self.page.locator('#discoveryNotice')).to_be_hidden()
        expect(self.page.locator('#resultMeta')).to_contain_text('모드 기록 없음')
        expect(self.page.locator('#loadRunSettings')).to_be_disabled()
        expect(self.page.locator('#resultRows .row-main > .status')).to_have_text(['REVIEW', 'SKIP'])
        self.assertEqual(self.page_errors, [])
        self.assertEqual(self.external_requests, [])

    def test_real_registry_all_products_and_environments_only_updates_inputs(self):
        self.open()
        expect(self.page.locator('#baselineEnvironmentId')).to_have_value('custom')
        expect(self.page.locator('#baselineEnvironmentId option')).to_have_count(1)
        for profile_id, urls in REGISTERED_URLS.items():
            with self.subTest(profile=profile_id):
                self.page.locator('#profileId').select_option(profile_id)
                expect(self.page.locator('#baselineEnvironmentId')).to_have_value('production')
                expect(self.page.locator('#candidateEnvironmentId')).to_have_value('staging')
                expect(self.page.locator('#baselineUrl')).to_have_value(urls[0])
                expect(self.page.locator('#candidateUrl')).to_have_value(urls[1])
                for side in ['baseline', 'candidate']:
                    expect(self.page.locator(f'#{side}EnvironmentId option')).to_have_count(5)
                    for environment_id, label, url in zip(ENVIRONMENT_IDS, ENVIRONMENT_LABELS, urls):
                        self.page.locator(f'#{side}EnvironmentId').select_option(environment_id)
                        expect(self.page.locator(f'#{side}Url')).to_have_value(url)
                        expect(self.page.locator(f'#{side}Name')).to_have_value(label)
                self.assertEqual(self.posts, [])
        self.page.locator('#baselineEnvironmentId').select_option('vibe-dev')
        self.page.locator('#candidateEnvironmentId').select_option('legacy-dev')
        self.submit(1)
        self.assertEqual(self.posts[-1]['baselineEnvironmentId'], 'vibe-dev')
        self.assertEqual(self.posts[-1]['candidateEnvironmentId'], 'legacy-dev')
        self.assertEqual(self.posts[-1]['baselineUrl'], REGISTERED_URLS['secondary-mobile'][2])
        self.assertEqual(self.posts[-1]['candidateUrl'], REGISTERED_URLS['secondary-mobile'][3])
        self.page.locator('#baselineName').fill('사용자 이름')
        self.page.locator('#baselineUrl').fill('https://custom.example.test/other#/page')
        expect(self.page.locator('#baselineEnvironmentId')).to_have_value('custom')
        expect(self.page.locator('#baselineName')).to_have_value('사용자 이름')
        self.page.locator('#baselineUrl').fill(REGISTERED_URLS['secondary-mobile'][0])
        expect(self.page.locator('#baselineEnvironmentId')).to_have_value('production')
        expect(self.page.locator('#baselineName')).to_have_value('사용자 이름')
        self.page.locator('#profileId').select_option('custom')
        expect(self.page.locator('#baselineEnvironmentId option')).to_have_count(1)
        expect(self.page.locator('#baselineEnvironmentId')).to_have_value('custom')
        expect(self.page.locator('#baselineUrl')).to_have_value('')
        self.assertEqual(self.page_errors, [])
        self.assertEqual(self.external_requests, [])

    def test_registry_mock_selection_and_old_settings_restore_leave_ids_untouched(self):
        urls = ['https://fixture.example.test/home', 'https://stage.example.test/start',
                'https://new.example.test/custom-main', 'https://old.example.test/#/']
        self.bootstrap_profile_overrides['elementary-pc'] = {
            'environments': [{'id': environment_id, 'label': label, 'url': url}
                             for environment_id, label, url in zip(ENVIRONMENT_IDS, ENVIRONMENT_LABELS, urls)],
            'baselineEnvironmentId': 'production', 'candidateEnvironmentId': 'staging'}
        self.jobs[CURRENT]['options'] = {
            'profile_id': 'elementary-pc', 'operator_id': 'QA-old', 'test_type': 'comparison',
            'baseline_url': 'https://previous.example.test/#/home?view=legacy',
            'candidate_url': urls[3], 'baseline_name': '직접 운영', 'candidate_name': '예전 개발',
            'baseline_environment_id': 'production', 'candidate_environment_id': 'staging', 'mode': 'visual'}
        original_options = copy.deepcopy(self.jobs[CURRENT]['options'])
        self.open()
        self.page.locator('#profileId').select_option('elementary-pc')
        expect(self.page.locator('#baselineUrl')).to_have_value(urls[0])
        expect(self.page.locator('#candidateUrl')).to_have_value(urls[1])
        self.page.locator('#baselineEnvironmentId').select_option('vibe-dev')
        expect(self.page.locator('#baselineUrl')).to_have_value(urls[2])
        self.page.get_by_text('수동 로그인과 아이디 기억', exact=True).click()
        self.page.locator('#rememberIds').check()
        self.page.locator('#rememberedIdA').fill('synthetic-id-a')
        self.page.locator('#rememberedIdB').fill('synthetic-id-b')
        self.page.locator('#rememberedIdB').blur()
        storage_before = self.page.evaluate('JSON.stringify(localStorage)')
        self.page.locator('.history-item').filter(has_text='QA-fixture').click()
        self.page.locator('#loadRunSettings').click()
        expect(self.page.locator('#baselineUrl')).to_have_value(original_options['baseline_url'])
        expect(self.page.locator('#candidateUrl')).to_have_value(urls[3])
        expect(self.page.locator('#baselineEnvironmentId')).to_have_value('custom')
        expect(self.page.locator('#candidateEnvironmentId')).to_have_value('legacy-dev')
        expect(self.page.locator('#baselineName')).to_have_value('직접 운영')
        expect(self.page.locator('#candidateName')).to_have_value('예전 개발')
        expect(self.page.locator('#rememberIds')).to_be_checked()
        expect(self.page.locator('#rememberedIdA')).to_have_value('synthetic-id-a')
        expect(self.page.locator('#rememberedIdB')).to_have_value('synthetic-id-b')
        self.assertEqual(self.page.evaluate('JSON.stringify(localStorage)'), storage_before)
        self.assertEqual(self.jobs[CURRENT]['options'], original_options)
        self.assertEqual(self.posts, [])
        self.page.locator('#candidateUrl').fill('https://stage.example.test/start#old')
        expect(self.page.locator('#candidateEnvironmentId')).to_have_value('custom')
        expect(self.page.locator('#candidateName')).to_have_value('예전 개발')
        # Historical options without environment IDs must behave identically.
        del self.jobs[CURRENT]['options']['baseline_environment_id']
        del self.jobs[CURRENT]['options']['candidate_environment_id']
        self.page.locator('.history-item').filter(has_text='QA-fixture').click()
        self.page.locator('#loadRunSettings').click()
        expect(self.page.locator('#baselineEnvironmentId')).to_have_value('custom')
        expect(self.page.locator('#candidateEnvironmentId')).to_have_value('legacy-dev')
        expect(self.page.locator('#baselineUrl')).to_have_value(original_options['baseline_url'])
        self.assertEqual(self.page.evaluate('JSON.stringify(localStorage)'), storage_before)
        self.submit(1)
        self.assertEqual(self.posts[-1]['baselineEnvironmentId'], 'custom')
        self.assertEqual(self.posts[-1]['candidateEnvironmentId'], 'legacy-dev')
        self.assertNotIn('synthetic-id-a', json.dumps(self.posts[-1]))
        self.assertNotIn('synthetic-id-b', json.dumps(self.posts[-1]))
        captures = self.root / 'output' / 'playwright'
        captures.mkdir(parents=True, exist_ok=True)
        self.page.locator('.settings').screenshot(path=str(captures / 'app-environments-desktop.png'))
        self.page.set_viewport_size({'width': 390, 'height': 844})
        self.assertTrue(self.page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
        self.page.locator('.settings').screenshot(path=str(captures / 'app-environments-mobile.png'))
        self.assertEqual(self.page_errors, [])
        self.assertEqual(self.external_requests, [])

    def test_inventory_candidate_drafts_preserve_keys_and_do_not_approve_or_run(self):
        seed_a, seed_b = 'https://prod.example.test/home', 'https://dev2.example.test/#/'
        key_a, key_b = '/notice.do?category=edu&sort=latest', '/#/board?category=edu'
        alias = {'baseline': key_a, 'candidate': key_b, 'page_class': 'inventory-page'}
        pages = [{'id': 'a-page', 'pageKey': key_a, 'url': 'https://prod.example.test' + key_a,
                  'finalUrl': 'https://prod.example.test' + key_a, 'title': '공지사항 <script>safe</script>',
                  'navigationTrail': ['홈', '공지사항'], 'signature': {'heading': '공지사항', 'forms': 0},
                  'actionCount': 3, 'statusCode': 200, 'captureReady': True}]
        candidate = {'url': 'https://dev2.example.test' + key_b, 'key': key_b,
                     'method': 'SEMANTIC_CANDIDATE', 'reason': 'SEMANTIC_EVIDENCE_REQUIRES_REVIEW',
                     'evidence': [{'kind': 'heading', 'baseline': '공지사항', 'candidate': '공지사항',
                                   'detail': '같은 제목은 동일 기능 확정 근거가 아님'}],
                     'available': True, 'alias': alias}
        used_candidate = dict(copy.deepcopy(candidate), available=False, key='/already-used')
        report = self.jobs[CURRENT]['report']
        report['inventory'] = {
            'environments': [
                {'id': 'a', 'name': '운영', 'seedUrl': seed_a, 'pages': pages,
                 'discoveredCount': 5, 'visitedCount': 1, 'deferredCount': 4},
                {'id': 'b', 'name': 'DEV2', 'seedUrl': seed_b,
                 'pages': [dict(copy.deepcopy(pages[0]), id='b-page', pageKey=key_b,
                                url=candidate['url'], finalUrl=candidate['url'], title='개발 공지')],
                 'discoveredCount': 3, 'visitedCount': 1, 'deferredCount': 2}],
            'matches': [
                {'id': 'start', 'key': 'start-page', 'baselineUrl': seed_a, 'candidateUrl': seed_b,
                 'baselineKey': '/home', 'candidateKey': '/#/', 'method': 'SELECTED_START_PAGES',
                 'approved': True, 'reason': 'START_URLS_DECLARED_EQUIVALENT', 'evidence': [], 'candidates': []},
                {'id': 'unmatched', 'key': key_a, 'baselineUrl': pages[0]['url'], 'candidateUrl': None,
                 'baselineKey': key_a, 'candidateKey': None, 'method': 'UNMATCHED', 'approved': False,
                 'reason': 'MANUAL_MAPPING_REQUIRED', 'evidence': [], 'candidates': [candidate, used_candidate]},
                {'id': 'paired-candidate', 'key': 'search-function', 'baselineUrl': 'https://prod.example.test/search',
                 'candidateUrl': 'https://dev2.example.test/find', 'baselineKey': '/search', 'candidateKey': '/find',
                 'method': 'SEMANTIC_CANDIDATE', 'approved': False, 'reason': 'MANUAL_MAPPING_REQUIRED',
                 'evidence': [{'kind': 'form', 'detail': '읽기 검색 폼 후보'}], 'candidates': []}]}
        initial_aliases = [{'baseline': '/already-a', 'candidate': '/already-b', 'page_class': 'inventory-page'}]
        self.jobs[CURRENT]['options'] = {
            'profile_id': 'custom', 'operator_id': 'QA-inventory', 'test_type': 'comparison',
            'baseline_url': seed_a, 'candidate_url': seed_b, 'baseline_name': '운영', 'candidate_name': 'DEV2',
            'crawl_scope': 'same_origin_readonly', 'mode': 'discovery', 'route_aliases': initial_aliases}
        original_report, original_options = copy.deepcopy(report), copy.deepcopy(self.jobs[CURRENT]['options'])
        self.open()
        self.page.locator('.history-item').filter(has_text='QA-fixture').click()
        self.page.locator('#inventoryPanel > summary').click()
        expect(self.page.locator('#inventoryCsvLink')).to_have_attribute('href', f'/api/scans/{CURRENT}/inventory.csv')
        expect(self.page.locator('#pageInventory .environment-inventory')).to_have_count(2)
        expect(self.page.locator('[data-environment="a"]')).to_contain_text('A · 운영')
        expect(self.page.locator('[data-environment="a"]')).to_contain_text('발견 5 · 방문 1 · 보류 4')
        expect(self.page.locator('[data-environment="b"]')).to_contain_text('B · DEV2')
        self.page.locator('[data-environment="a"] .inventory-page > summary').click()
        expect(self.page.locator('[data-environment="a"]')).to_contain_text(key_a)
        expect(self.page.locator('[data-environment="a"]')).to_contain_text('<script>safe</script>')
        self.assertEqual(self.page.locator('#pageInventory script').count(), 0)
        expect(self.page.locator('#resultMeta')).to_contain_text('A: 운영 / B: DEV2')
        matches = self.page.locator('#matchInventory .inventory-match')
        self.assertEqual(matches.nth(0).get_by_role('button', name='매핑 JSON에 추가', exact=True).count(), 0)
        proposed = matches.nth(1).locator('.inventory-candidate').nth(0)
        expect(proposed).to_contain_text('REVIEW · 매칭 후보')
        proposed.locator('summary').click()
        expect(proposed).to_contain_text('같은 제목은 동일 기능 확정 근거가 아님')
        expect(matches.nth(1).locator('.inventory-candidate').nth(1).get_by_role('button')).to_be_disabled()
        proposed.get_by_role('button').click()
        expect(self.page.locator('#errorSection')).to_contain_text('현재 검사 설정이 다릅니다')
        self.page.locator('#loadRunSettings').click()
        expect(self.page.locator('#baselineName')).to_have_value('운영')
        expect(self.page.locator('#candidateName')).to_have_value('DEV2')
        expect(self.page.locator('#crawlScope')).to_have_value('same_origin_readonly')
        proposed.get_by_role('button').click()
        updated_aliases = json.loads(self.page.locator('#aliases').input_value())
        self.assertEqual(updated_aliases[-1], dict(alias, page_class='inventory-page-2'))
        expect(self.page.locator('#successSection')).to_contain_text('새 검사를 시작해야 적용')
        proposed.get_by_role('button').click()
        expect(self.page.locator('#errorSection')).to_contain_text('기존 매핑에 있습니다')
        self.assertEqual(json.loads(self.page.locator('#aliases').input_value()), updated_aliases)
        matches.nth(2).get_by_role('button', name='매핑 JSON에 추가', exact=True).click()
        self.assertEqual(json.loads(self.page.locator('#aliases').input_value())[-1],
                         {'baseline': '/search', 'candidate': '/find', 'page_class': 'search-function'})
        self.assertEqual(self.posts, [])
        self.assertEqual(self.reviews, [])
        self.assertEqual(self.jobs[CURRENT]['report'], original_report)
        self.assertEqual(self.jobs[CURRENT]['options'], original_options)
        captures = self.root / 'output' / 'playwright'
        captures.mkdir(parents=True, exist_ok=True)
        self.page.screenshot(path=str(captures / 'app-page-inventory-desktop.png'), full_page=True)
        self.page.set_viewport_size({'width': 390, 'height': 844})
        self.assertTrue(self.page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
        self.page.screenshot(path=str(captures / 'app-page-inventory-mobile.png'), full_page=True)
        self.page.locator('.history-item').filter(has_text='QA-legacy').click()
        expect(self.page.locator('#inventoryCsvLink')).to_be_hidden()
        expect(self.page.locator('#pageInventory')).to_contain_text('페이지 목록이 기록되지 않았습니다')
        expect(self.page.locator('#matchInventory .inventory-match')).to_have_count(0)
        self.assertEqual(self.page_errors, [])
        self.assertEqual(self.external_requests, [])

    def test_seven_states_facets_issue_review_and_legacy_preservation(self):
        self.open()
        self.page.locator('.history-item').first.click()
        expect(self.page.locator('#resultRows .result-row')).to_have_count(7)
        for status in STATES:
            self.page.locator(f'[data-filter="{status}"]').click()
            expect(self.page.locator('#resultRows .result-row')).to_have_count(1)
            expect(self.page.locator('#resultRows .row-main > .status')).to_have_text(status)
        self.reset_filters()
        for field, value in [('environmentFilter', 'b'), ('categoryFilter', 'RESOURCE'),
                             ('subtypeFilter', 'RESOURCE_SAMPLE'), ('severityFilter', 'HIGH'),
                             ('regressionFilter', 'NEW')]:
            self.page.locator('#' + field).select_option(value)
            expect(self.page.locator('#resultRows .result-row')).to_have_count(1)
        self.page.locator('#regressionFilter').select_option('RECURRING')
        expect(self.page.locator('#resultRows .result-row')).to_have_count(1)
        row = self.page.locator('#resultRows .result-row')
        row.locator('summary.row-main').click()
        expect(row.locator('.finding-card')).to_contain_text('관찰 3회')
        expect(row.locator('.finding-card')).to_contain_text('<script>non-executable</script>')
        row.get_by_label('최종 검수 상태', exact=True).select_option('BUG_CONFIRMED')
        row.get_by_label('검수 사유', exact=True).fill('이미 등록된 합성 결함과 연결')
        row.get_by_label('기존 이슈 URL', exact=True).fill('https://issues.example.test/QA-17')
        row.get_by_role('button', name='검수 저장', exact=True).click()
        expect(self.page.locator('#successSection')).to_contain_text('검수 이력을 저장')
        self.assertEqual(self.reviews[-1]['issueRef'], 'https://issues.example.test/QA-17')
        self.assertEqual(self.reviews[-1]['expectedRevision'], 0)
        self.assertEqual(self.jobs[CURRENT]['report']['results'][1]['status'], 'FAIL')
        expect(self.page.locator('#coverageSummary')).to_contain_text('고유 발견 사항7')
        expect(self.page.locator('#coverageSummary')).to_contain_text('연결된 이슈1')
        self.page.locator('#reviewStatusFilter').select_option('BUG_CONFIRMED')
        expect(self.page.locator('#resultRows .result-row')).to_have_count(1)
        self.page.locator('#includeNull').uncheck()
        expect(self.page.locator('#emptyMessage')).to_be_visible()
        expect(self.page.locator('#attentionPanel')).to_be_visible()
        self.page.locator('#includeNull').check()
        self.reset_filters()
        self.page.locator('[data-filter="PASS"]').click()
        row = self.page.locator('#resultRows .result-row')
        row.locator('summary.row-main').click()
        row.get_by_label('최종 검수 상태', exact=True).select_option('VERIFIED_OK')
        row.get_by_label('검수 사유', exact=True).fill('정상 표본 확인')
        row.get_by_role('button', name='검수 저장', exact=True).click()
        expect(row.locator('.review-tag')).to_contain_text('정상 확인')
        self.assertEqual(self.jobs[CURRENT]['report']['results'][0]['status'], 'PASS')
        self.reset_filters()
        self.page.locator('#categoryFilter').select_option('VISUAL')
        expect(self.page.locator('#resultRows .result-row')).to_have_count(1)
        expect(self.page.locator('#resultRows .row-main > .status')).to_have_text('DIFF')
        self.reset_filters()
        captures = self.root / 'output' / 'playwright'
        captures.mkdir(parents=True, exist_ok=True)
        self.page.screenshot(path=str(captures / 'app-seven-states-desktop.png'), full_page=True)
        self.page.set_viewport_size({'width': 390, 'height': 844})
        self.assertTrue(self.page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
        self.page.screenshot(path=str(captures / 'app-seven-states-mobile.png'), full_page=True)
        self.page.locator('.history-item').filter(has_text='QA-legacy').click()
        expect(self.page.locator('#legacyNotice')).to_be_visible()
        expect(self.page.locator('#resultRows .row-main > .status')).to_have_text(['REVIEW', 'SKIP'])
        expect(self.page.locator('#regressionSummary')).to_contain_text('회귀 미평가')
        self.assertEqual(self.page.locator('#resultRows .status.DIFF, #resultRows .status.BLOCKED').count(), 0)

        # A past finding with no current result row must remain reachable. A
        # current-run search/status filter must not hide its historical evidence.
        self.jobs[CURRENT]['testType'] = 'regression'
        self.jobs[CURRENT]['report'] = {
            'testType': 'regression', 'previousRunId': LEGACY, 'results': [], 'findings': [],
            'totals': {'resultRows': 0, 'uniqueFindings': 0},
            'regression': {'comparable': True, 'previousRunId': LEGACY,
                           'summary': {'NOT_RETESTED': 1},
                           'findings': [{'classification': 'NOT_RETESTED', 'currentFindingId': None,
                                         'previousFindingId': 'old-finding', 'previousRowIds': ['legacy-review'],
                                         'pageKey': '/legacy', 'checkId': 'old.visual',
                                         'reason': 'NO_COMPARABLE_PASS_EVIDENCE'}]}}
        self.page.locator('#searchFilter').fill('hide-historical-evidence')
        self.page.locator('[data-filter="FAIL"]').click()
        self.page.locator('.history-item').filter(has_text='QA-fixture').click()
        expect(self.page.locator('#resultRows .result-row')).to_have_count(0)
        self.page.locator('#regressionSummary summary').click()
        entry = self.page.locator('.regression-finding')
        expect(entry).to_contain_text('재검되지 않음')
        expect(entry).to_contain_text('/legacy')
        expect(entry).to_contain_text('old.visual')
        expect(entry).to_contain_text('NO_COMPARABLE_PASS_EVIDENCE')
        entry.get_by_role('button', name='이전 증거 보기', exact=True).click()
        expect(self.page.locator('#resultRows .result-row')).to_have_count(2)
        expect(self.page.locator('#result-row-0')).to_have_attribute('open', '')
        expect(self.page.locator('#searchFilter')).to_have_value('')
        expect(self.page.locator('#successSection')).to_contain_text('과거 실행 22222222')
        expect(self.page.locator('#resultRows .row-main > .status')).to_have_text(['REVIEW', 'SKIP'])
        self.assertEqual(self.page_errors, [])
        self.assertEqual(self.external_requests, [])


if __name__ == '__main__':
    unittest.main()
