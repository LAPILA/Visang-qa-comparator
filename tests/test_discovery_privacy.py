"""Privacy applies before DOM metadata is collected; only synthetic HTML is used."""
import json
import tempfile
import unittest
from pathlib import Path

from playwright.sync_api import sync_playwright

from app import csv_inventory
from qa.engine import DISCOVER_JS, Budget, _discover, _visit
from qa.inventory import build_inventory
from qa.store import redact


HTML = '''<!doctype html><html><head><title>Public portal PRIVATE_CHILD_MARKER</title></head><body>
<nav><a id="public-link" href="/public">Public search <span data-qa-private>PRIVATE_CHILD_MARKER</span></a></nav>
<nav data-qa-private><a id="private-link" href="/private">PRIVATE_NAV_MARKER</a></nav>
<main><h1>Public catalogue <span data-qa-private>PRIVATE_HEADING_MARKER</span>
<span style="display:none"><em>HIDDEN_CHILD_MARKER</em></span></h1>
<section class="confidential"><h2>MASK_HEADING_MARKER</h2><form>
<input name="private-field" aria-label="MASK_FIELD_MARKER" value="MASK_VALUE_MARKER">
<button id="private-button">MASK_ACTION_MARKER</button></form><a href="/masked">MASK_LINK_MARKER</a></section>
<form><input type="search" name="keyword" aria-label="Public keyword" value="UNEXPORTED_INPUT_MARKER">
<input id="password" type="password" tabindex="0" value="PASSWORD_VALUE_MARKER">
<button id="public-button" type="button">Public find <span data-qa-private>PRIVATE_ACTION_MARKER</span>
<script type="application/json">SCRIPT_DATA_MARKER</script><style>/*STYLE_DATA_MARKER*/</style>
<template>TEMPLATE_DATA_MARKER</template><noscript>NOSCRIPT_DATA_MARKER</noscript></button></form>
</main></body></html>'''


class DiscoveryPrivacyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(headless=True, timeout=10000)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self):
        self.context = self.browser.new_context()
        # Fulfil every request in memory: privacy.invalid is never contacted.
        self.context.route('**/*', lambda route: route.fulfill(status=200, content_type='text/html', body=HTML))

    def tearDown(self):
        self.context.close()

    def test_private_subtrees_and_descendant_text_are_excluded_without_dom_mutation(self):
        page = self.context.new_page()
        page.goto('https://privacy.invalid/')
        before = page.content()
        info = page.evaluate(DISCOVER_JS, {'rules': [{'selector': '#public-button'}],
                                          'privateSelectors': ['.confidential']})
        after = page.content()
        self.assertEqual(before, after)
        serialized = json.dumps(info)
        self.assertNotIn('_MARKER', serialized)
        self.assertIn('Public search', info['signature']['navLabels'])
        self.assertIn('Public find', info['signature']['actionLabels'])
        self.assertEqual(info['heading'], 'Public catalogue')
        self.assertEqual(info['signature']['formFields'], [{'type': 'search', 'name': 'keyword', 'label': 'Public keyword'}])
        self.assertTrue(any(item['selector'] == '#public-link' and item['href'] == 'https://privacy.invalid/public'
                            for item in info['candidates']))
        self.assertTrue(any(item['selector'] == '#public-button' for item in info['candidates']))
        self.assertGreaterEqual(info['privacy']['excludedCandidates'], 4)
        self.assertGreater(info['privacy']['excludedElements'], 4)
        self.assertEqual(page.locator('#password').input_value(), 'PASSWORD_VALUE_MARKER')
        self.assertEqual(page.locator('[name=keyword]').input_value(), 'UNEXPORTED_INPUT_MARKER')

    def test_legacy_rules_argument_still_excludes_default_private_nodes(self):
        page = self.context.new_page()
        page.set_content('<nav data-qa-private><a href="/p">PRIVATE_MARKER</a></nav>'
                         '<h1>Public <span data-qa-private>CHILD_MARKER</span></h1>'
                         '<input type="password" tabindex="0" value="PASSWORD_MARKER">'
                         '<button id="public">Visible</button>')
        info = page.evaluate(DISCOVER_JS, [{'selector': '#public'}])
        self.assertNotIn('_MARKER', json.dumps(info))
        self.assertEqual(info['heading'], 'Public')
        self.assertEqual([item['selector'] for item in info['candidates']], ['#public'])

    def test_collection_never_reads_input_value_properties(self):
        page = self.context.new_page()
        page.set_content(HTML + '<textarea data-qa-private>TEXTAREA_MARKER</textarea>'
                         '<textarea tabindex="0">PUBLIC_TEXTAREA_MARKER</textarea>'
                         '<select tabindex="0"><option>PUBLIC_SELECT_MARKER</option></select>')
        page.evaluate('''() => {
          for (const el of document.querySelectorAll('input,textarea,select')) {
            Object.defineProperty(el,'value',{get(){throw new Error('INPUT_VALUE_MUST_NOT_BE_READ');}});
          }
        }''')
        info = page.evaluate(DISCOVER_JS, {'rules': [], 'privateSelectors': ['.confidential']})
        self.assertNotIn('_MARKER', json.dumps(info))
        self.assertIn('Public search', info['signature']['navLabels'])

    def test_invalid_private_selector_fails_closed_with_structured_error(self):
        page = self.context.new_page()
        page.set_content(HTML)
        before = page.content()
        record = {'coverage': {}, 'checks': [], 'captureReady': True, 'readiness': {}}
        info = _discover(page, {'private_mask_selectors': ['??INVALID_PRIVATE_MARKER']}, record, 'a')
        self.assertIsNone(info)
        self.assertFalse(record['captureReady'])
        self.assertFalse(record['readiness']['privacy'])
        self.assertEqual(record['checks'][0]['status'], 'ERROR')
        self.assertEqual(record['checks'][0]['reason_code'], 'INVALID_PRIVATE_SELECTOR')
        self.assertNotIn('_MARKER', json.dumps(record))
        self.assertEqual(page.content(), before)

    def test_real_visit_json_inventory_and_csv_do_not_export_private_markers(self):
        temp_root = Path(__file__).resolve().parents[1] / 'output' / 'tmp'
        temp_root.mkdir(parents=True, exist_ok=True)
        url = 'https://privacy.invalid/'
        options = {'baseline_url': url, 'allowed_hosts': ['privacy.invalid'], 'mode': 'discovery',
                   'private_mask_selectors': ['.confidential'], 'max_actions': 0, 'action_interval': 0,
                   'timeout_seconds': 30, 'safe_actions': [], 'regions': []}
        with tempfile.TemporaryDirectory(dir=temp_root) as folder:
            state = {'record': None, 'blocked_urls': set(), 'blocked': [], 'scenario_done': False}
            record = _visit(self.context, url, 'a', 0, options, Path(folder), 'privacy-fixture',
                            Budget(options, lambda: False), state)
            self.assertTrue(record['screenshot'])
            self.assertFalse(any(item['status'] == 'ERROR' for item in record['checks']), record['checks'])
            self.assertGreaterEqual(record['coverage']['privateExcludedCandidates'], 4)
            public_link = next(action for action in record['actions'] if action['selector'] == '#public-link')
            record['navigationTrail'] = ['start-page', public_link['label']]
            inventory = build_inventory(options, {url: record}, {}, [], [], [])
            report = {'inventory': inventory, 'results': [{'baseline': record}]}
            job = {'id': 'privacy-fixture', 'report': report}
            self.assertNotIn('_MARKER', json.dumps(redact(job)))
            csv_data = csv_inventory(job).decode('utf-8-sig')
            self.assertNotIn('_MARKER', csv_data)
            self.assertIn('Public search', csv_data)

    def test_invalid_selector_aborts_real_visit_before_capture_or_action_collection(self):
        temp_root = Path(__file__).resolve().parents[1] / 'output' / 'tmp'
        temp_root.mkdir(parents=True, exist_ok=True)
        url = 'https://privacy.invalid/'
        options = {'baseline_url': url, 'allowed_hosts': ['privacy.invalid'], 'mode': 'discovery',
                   'private_mask_selectors': ['??INVALID_PRIVATE_MARKER'], 'timeout_seconds': 30}
        with tempfile.TemporaryDirectory(dir=temp_root) as folder:
            state = {'record': None, 'blocked_urls': set(), 'blocked': [], 'scenario_done': False}
            record = _visit(self.context, url, 'a', 0, options, Path(folder), 'invalid-privacy',
                            Budget(options, lambda: False), state)
            self.assertTrue(any(item['status'] == 'ERROR' and item['reason_code'] == 'INVALID_PRIVATE_SELECTOR'
                                for item in record['checks']))
            self.assertFalse(record['screenshot'])
            self.assertEqual(record['actions'], [])
            self.assertEqual(record['title'], '')
            self.assertNotIn('_MARKER', json.dumps(record))
            self.assertEqual(list(Path(folder).rglob('*.png')), [])


if __name__ == '__main__':
    unittest.main()
