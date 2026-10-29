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

                    page.locator('#regionFilter').select_option('required-help')
                    page.locator('[data-filter="FAIL"]').click()
                    expect(page.locator('#resultRows .result-row')).to_have_count(3)
                    row = page.locator('#resultRows .result-row').first
                    row.locator('summary.row-main').click()
                    row.get_by_label('최종 검수 상태', exact=True).select_option('BUG_CONFIRMED')
                    row.get_by_label('검수 사유', exact=True).fill('합성 정답: B의 필수 Help 버튼 누락 확인')
                    row.get_by_role('button', name='검수 저장', exact=True).click()
                    expect(page.locator('#successSection')).to_contain_text('검수 이력을 저장했습니다.')
                    persisted = server.service.store.get(run_id)
                    reviewed = [item for item in persisted['report']['results'] if item.get('review', {}).get('revision') == 1]
                    self.assertEqual(len(reviewed), 1)
                    self.assertEqual(reviewed[0]['status'], 'FAIL')
                    self.assertEqual(reviewed[0]['review']['status'], 'BUG_CONFIRMED')

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
