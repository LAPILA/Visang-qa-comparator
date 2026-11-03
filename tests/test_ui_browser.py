"""One real UI-to-worker-to-review workflow, using only the synthetic targets."""
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright

from app import Server
from qa.demo import get_demo_summary, reset_demo_counts


class WorkspaceBrowserTests(unittest.TestCase):
    def test_real_single_regression_and_conditional_purposes(self):
        root = Path(__file__).resolve().parents[1]
        tmp_root = root / 'output' / 'tmp'
        tmp_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=tmp_root) as directory:
            server = Server(('127.0.0.1', 0), runs_dir=Path(directory) / 'runs')
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(timeout=20000)
                    context = browser.new_context(viewport={'width': 1440, 'height': 1000}, locale='ko-KR')
                    external, errors, payloads = [], [], []

                    def guard(route):
                        if urlsplit(route.request.url).netloc != urlsplit(server.base_origin).netloc:
                            external.append(route.request.url)
                            route.abort()
                        else:
                            route.continue_()

                    context.route('**/*', guard)
                    page = context.new_page()
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.on('request', lambda request: payloads.append(request.post_data_json)
                            if request.method == 'POST' and urlsplit(request.url).path == '/api/scans' else None)
                    page.goto(server.base_origin)
                    expect(page.locator('#startBtn')).to_be_enabled()
                    page.locator('#operatorId').fill('QA-purpose-real')
                    page.locator('#testType').select_option('single')
                    page.locator('#maxPages').fill('1')
                    page.locator('#maxDepth').fill('0')
                    page.locator('#maxActions').fill('0')
                    page.locator('#mode').select_option('discovery')
                    page.get_by_text('고급 설정 · 페이지 매핑, 영역, 허용 동작', exact=True).click()
                    page.locator('#scenarioIds').fill('[]')
                    page.locator('#regions').fill('[]')

                    def submit_and_read():
                        page.locator('#startBtn').click()
                        expect(page.locator('#resultSection')).to_be_visible(timeout=60000)
                        expect(page.locator('#startBtn')).to_be_enabled(timeout=5000)
                        run_id = urlsplit(page.locator('#jsonLink').get_attribute('href')).path.rsplit('/', 1)[-1].removesuffix('.json')
                        job = server.service.store.get(run_id)
                        self.assertEqual(job['state'], 'done', job.get('error'))
                        self.assertEqual(job['report']['totals']['error'], 0)
                        self.assertEqual(job['report']['totals']['candidateVisited'], 0)
                        self.assertNotIn('candidateUrl', payloads[-1])
                        self.assertTrue(all(row.get('candidate') is None for row in job['report']['results']))
                        return job

                    single = submit_and_read()
                    self.assertEqual(single['report']['testType'], 'single')
                    page.locator('#testType').select_option('regression')
                    page.locator('#previousRunId').select_option(single['id'])
                    regression = submit_and_read()
                    self.assertEqual(regression['report']['testType'], 'regression')
                    self.assertEqual(regression['report']['regression']['previousRunId'], single['id'])
                    self.assertTrue(regression['report']['regression']['comparable'], regression['report']['regression']['reasons'])
                    page.locator('#regressionSummary summary').click()
                    expect(page.locator('#regressionSummary')).to_contain_text(single['id'])
                    page.get_by_role('button', name='과거 실행 근거 열기', exact=True).click()
                    expect(page.locator('#resultMeta')).to_contain_text(single['id'][:8])

                    page.locator('#testType').select_option('conditional')
                    page.locator('#conditions').fill('''[
                        {"id":"body.visible","selector":"body","kind":"visible","expected":true},
                        {"id":"requires.fixture","selector":"body","kind":"visible","expected":true,
                         "preconditions":[{"selector":"#not-present-test-data","kind":"count","expected":{"min":1}}]}
                    ]''')
                    conditional = submit_and_read()
                    self.assertEqual(conditional['report']['testType'], 'conditional')
                    checks = [check for row in conditional['report']['results'] for check in row['checks']]
                    self.assertTrue(any('body.visible' in check['check_id'] and check['status'] == 'PASS' for check in checks))
                    self.assertTrue(any('requires.fixture' in check['check_id'] and check['status'] == 'BLOCKED' for check in checks))
                    page.locator('[data-filter="BLOCKED"]').click()
                    expect(page.locator('#resultRows .result-row').first).to_be_visible()
                    expect(page.locator('#resultMeta')).to_contain_text('조건 기반 UI QA')
                    self.assertEqual(len(payloads), 3)
                    self.assertEqual(errors, [])
                    self.assertEqual(external, [])
                    context.close()
                    browser.close()
            finally:
                if server.service.active:
                    server.service.cancel(server.service.active)
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)

    def test_real_ui_scan_filter_review_export_and_history(self):
        root = Path(__file__).resolve().parents[1]
        tmp_root = root / 'output' / 'tmp'
        tmp_root.mkdir(parents=True, exist_ok=True)
        captures = root / 'output' / 'playwright'
        captures.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=tmp_root) as directory:
            server = Server(('127.0.0.1', 0), runs_dir=Path(directory) / 'runs')
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            reset_demo_counts()
            try:
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(timeout=20000)
                    context = browser.new_context(viewport={'width': 1440, 'height': 1000}, locale='ko-KR')
                    unexpected = []

                    def guard(route):
                        if urlsplit(route.request.url).netloc != urlsplit(server.base_origin).netloc:
                            unexpected.append(route.request.url)
                            route.abort()
                        else:
                            route.continue_()

                    context.route('**/*', guard)
                    page = context.new_page()
                    errors = []
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.goto(server.base_origin)
                    expect(page.locator('#startBtn')).to_be_enabled()
                    expect(page.locator('#profileId')).to_have_value('synthetic-demo')
                    page.locator('#operatorId').fill('QA-UI')
                    page.locator('#maxPages').fill('3')
                    page.locator('#startBtn').click()
                    expect(page.locator('#resultSection')).to_be_visible(timeout=60000)
                    expect(page.locator('#startBtn')).to_be_enabled(timeout=5000)
                    summaries = server.service.store.list()
                    self.assertEqual(len(summaries), 1)
                    run_id = summaries[0]['id']
                    job = server.service.store.get(run_id)
                    self.assertEqual(job['state'], 'done')
                    self.assertEqual(job['report']['totals']['error'], 0)
                    self.assertGreater(job['report']['totals']['fail'], 0)

                    # The real runner's catalogue is visible and exported through the app API.
                    inventory = job['report']['inventory']
                    page.locator('#inventoryPanel > summary').click()
                    expect(page.locator('.environment-inventory')).to_have_count(2)
                    expect(page.locator('.inventory-page')).to_have_count(sum(len(env['pages']) for env in inventory['environments']))
                    expect(page.locator('#matchInventory')).to_contain_text('EXPLICIT_ALIAS')
                    with page.expect_download() as pages_download_info:
                        page.locator('#inventoryCsvLink').click()
                    pages_export = Path(directory) / 'pages.csv'
                    pages_download_info.value.save_as(pages_export)
                    self.assertIn('synthetic-demo', pages_export.read_text(encoding='utf-8-sig'))
                    self.assertIn('/demo/a/', pages_export.read_text(encoding='utf-8-sig'))
                    page.locator('#inventoryPanel > summary').click()

                    page.locator('#regionFilter').select_option('required-help')
                    page.locator('[data-filter="FAIL"]').click()
                    expect(page.locator('#resultRows .result-row')).to_have_count(3)
                    row = page.locator('#resultRows .result-row').first
                    row.locator('summary.row-main').click()
                    row.get_by_label('최종 검수 상태', exact=True).select_option('BUG_CONFIRMED')
                    row.get_by_label('검수 사유', exact=True).fill('합성 정답: B의 필수 Help 버튼 누락 확인')
                    row.get_by_label('기존 이슈 URL', exact=True).fill('https://issues.example.test/QA-UI-1')
                    row.get_by_role('button', name='검수 저장', exact=True).click()
                    expect(page.locator('#successSection')).to_contain_text('검수 이력을 저장했습니다.')
                    persisted = server.service.store.get(run_id)
                    reviewed = [item for item in persisted['report']['results'] if item.get('review', {}).get('revision') == 1]
                    self.assertEqual(len(reviewed), 1)
                    self.assertEqual(reviewed[0]['status'], 'FAIL')
                    self.assertEqual(reviewed[0]['review']['status'], 'BUG_CONFIRMED')
                    self.assertEqual(reviewed[0]['review']['issueRef'], 'https://issues.example.test/QA-UI-1')
                    self.assertEqual(persisted['report']['totals']['linkedIssues'], 1)

                    # A null-only failure remains in the independent attention summary.
                    page.locator('#includeNull').uncheck()
                    expect(page.locator('#emptyMessage')).to_be_visible()
                    expect(page.locator('#attentionPanel')).to_be_visible()
                    page.locator('#includeNull').check()
                    page.locator('[data-filter="ALL"]').click()
                    page.locator('#regionFilter').select_option('ALL')
                    page.locator('#resultSection').scroll_into_view_if_needed()
                    page.screenshot(path=str(captures / 'app-demo-desktop.png'), full_page=True)

                    with page.expect_download() as download_info:
                        page.locator('#csvLink').click()
                    download = download_info.value
                    export = Path(directory) / 'results.csv'
                    download.save_as(export)
                    self.assertIn('BUG_CONFIRMED', export.read_text(encoding='utf-8-sig'))
                    self.assertIn('https://issues.example.test/QA-UI-1', export.read_text(encoding='utf-8-sig'))
                    self.assertEqual(get_demo_summary()['mutation_counts'],
                                     {'a': {'save': 0, 'delete': 0}, 'b': {'save': 0, 'delete': 0}})

                    page.reload()
                    expect(page.locator('.history-item')).to_have_count(1)
                    page.locator('.history-item').click()
                    expect(page.locator('#resultSection')).to_be_visible()
                    page.set_viewport_size({'width': 390, 'height': 844})
                    page.screenshot(path=str(captures / 'app-demo-mobile.png'), full_page=True)
                    self.assertTrue(page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
                    self.assertEqual(errors, [])
                    self.assertEqual(unexpected, [])
                    context.close()
                    browser.close()
            finally:
                if server.service.active:
                    server.service.cancel(server.service.active)
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)


if __name__ == '__main__':
    unittest.main()
