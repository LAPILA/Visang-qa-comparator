import copy
import unittest

from qa.conditions import run_condition_checks, validate_conditions


class _Locator:
    def __init__(self, data):
        self.data = data

    def count(self):
        if self.data.get('invalid'):
            raise ValueError('Invalid selector')
        return self.data.get('count', 1)

    def is_visible(self, **kwargs):
        return self.data.get('visible', True)

    def inner_text(self, **kwargs):
        return self.data.get('text', '')

    def get_attribute(self, name, **kwargs):
        return self.data.get('attributes', {}).get(name)

    def evaluate(self, code, **kwargs):
        if code != '(el) => ({x:el.scrollWidth>el.clientWidth+1,y:el.scrollHeight>el.clientHeight+1})':
            raise AssertionError('Only the fixed read-only overflow measurement is allowed')
        return self.data.get('overflow', {'x': False, 'y': False})


class _Page:
    url = 'http://127.0.0.1/demo/a/'

    def __init__(self, elements=None):
        self.elements = elements or {}
        self.reads = []

    def locator(self, selector):
        self.reads.append(selector)
        return _Locator(self.elements.get(selector, {'count': 0}))


def condition(**changes):
    return {'id': 'help', 'selector': '#help', 'kind': 'visible', 'expected': True, **changes}


class ConditionUnitTests(unittest.TestCase):
    def run_conditions(self, conditions, elements=None, cancelled=False):
        return run_condition_checks(_Page(elements), conditions, 'a', {}, lambda: cancelled)

    def test_validation_rejects_code_unsafe_attributes_duplicate_ids_and_invalid_bounds(self):
        invalid = [[condition(script='fetch("/save")')], [condition(kind='evaluate')],
                   [condition(kind='attribute', attribute='value', expected='secret')],
                   [condition(kind='attribute', attribute='data-access-token', expected='secret')],
                   [condition(), condition()],
                   [condition(kind='count', expected={'min': 3, 'max': 2})],
                   [condition(kind='count', expected={'equals': True})],
                   [condition(case='long_title')]]
        for values in invalid:
            with self.subTest(values=values), self.assertRaises(ValueError):
                validate_conditions(values)

    def test_validation_copies_input_and_keeps_null_attribute_expectation(self):
        source = [condition(kind='attribute', attribute='aria-expanded', expected=None)]
        original = copy.deepcopy(source)
        normalized = validate_conditions(source)
        self.assertEqual(source, original)
        self.assertIsNone(normalized[0]['expected'])
        result = self.run_conditions(source, {'#help': {'attributes': {}}})[0]
        self.assertEqual((result['status'], result['executed']), ('PASS', True))

    def test_visible_absence_is_fail_but_expected_hidden_can_pass(self):
        self.assertEqual(self.run_conditions([condition()])[0]['status'], 'FAIL')
        self.assertEqual(self.run_conditions([condition(expected=False)])[0]['status'], 'PASS')

    def test_empty_data_contract_passes_only_after_explicit_zero_count_precondition(self):
        empty = condition(id='empty', case='empty', selector='#empty',
                          preconditions=[{'selector': '.item', 'kind': 'count', 'expected': {'equals': 0}}])
        self.assertEqual(self.run_conditions([empty], {'#empty': {}})[0]['status'], 'PASS')
        blocked = self.run_conditions([empty], {'.item': {'count': 2}, '#empty': {}})[0]
        self.assertEqual((blocked['status'], blocked['subtype']), ('BLOCKED', 'INSUFFICIENT_DATA'))

    def test_missing_expectation_is_review_and_selector_errors_are_error(self):
        missing = condition()
        missing.pop('expected')
        self.assertEqual(self.run_conditions([missing])[0]['status'], 'REVIEW')
        invalid = self.run_conditions([condition()], {'#help': {'invalid': True}})[0]
        self.assertEqual(invalid['status'], 'ERROR')
        ambiguous = self.run_conditions([condition()], {'#help': {'count': 2}})[0]
        self.assertEqual(ambiguous['reason_code'], 'CONDITION_TARGET_AMBIGUOUS')

    def test_cancel_and_scope_do_not_read_dom(self):
        page = _Page()
        self.assertEqual(run_condition_checks(page, [condition()], 'a', {}, lambda: True)[0]['status'], 'BLOCKED')
        self.assertEqual(run_condition_checks(page, [condition(url_pattern='/elsewhere/*')], 'a', {}, lambda: False)[0]['status'], 'SKIP')
        self.assertEqual(page.reads, [])

    def test_text_length_explicit_units_and_read_only_overflow(self):
        elements = {'#help': {'text': '😀', 'overflow': {'x': True, 'y': False}}}
        codepoints = condition(kind='text_length', unit='codepoints', expected={'equals': 1})
        utf16 = condition(kind='text_length', unit='utf16', expected={'equals': 2})
        self.assertEqual(self.run_conditions([codepoints], elements)[0]['status'], 'PASS')
        self.assertEqual(self.run_conditions([utf16], elements)[0]['status'], 'PASS')
        overflow = self.run_conditions([condition(kind='overflow', expected=False)], elements)[0]
        self.assertEqual((overflow['status'], overflow['category'], overflow['subtype']), ('FAIL', 'VISUAL', 'TEXT_OVERFLOW'))


class ConditionBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise unittest.SkipTest('Playwright is not installed')
        cls.playwright = sync_playwright().start()
        try:
            cls.browser = cls.playwright.chromium.launch(headless=True, timeout=10000)
        except Exception:
            cls.playwright.stop()
            raise unittest.SkipTest('Chromium is unavailable')

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def test_live_dom_conditions_do_not_change_document(self):
        context = self.browser.new_context()
        context.route('**/*', lambda route: route.abort())
        page = context.new_page()
        try:
            page.set_content('<main><h1 id="title">A very long synthetic fixture title</h1><div id="empty">No records</div>'
                             '<div id="overflow" style="width:10px;white-space:nowrap;overflow:hidden">Long text</div>'
                             '<button id="help" aria-expanded="false">Help</button></main>')
            before = page.content()
            conditions = [
                condition(),
                condition(id='attribute', kind='attribute', attribute='aria-expanded', expected='false'),
                condition(id='title', case='long_title', selector='#title', kind='overflow', expected=False,
                          preconditions=[{'selector': '#title', 'kind': 'text_length', 'expected': {'min': 20}}]),
                condition(id='empty', case='empty', selector='#empty', preconditions=[{'selector': '.row', 'kind': 'count', 'expected': {'equals': 0}}]),
                condition(id='clipped', selector='#overflow', kind='overflow', expected=False),
                condition(id='pagination', case='pagination', selector='#next', preconditions=[{'selector': '.row', 'kind': 'count', 'expected': {'min': 10}}]),
            ]
            results = run_condition_checks(page, conditions, 'a', {}, lambda: False)
            self.assertEqual([item['status'] for item in results], ['PASS', 'PASS', 'PASS', 'PASS', 'FAIL', 'BLOCKED'])
            self.assertEqual(page.content(), before)
        finally:
            context.close()

    def test_invalid_css_is_error_and_absent_expected_attribute_passes(self):
        context = self.browser.new_context()
        page = context.new_page()
        try:
            page.set_content('<button id="help">Help</button>')
            results = run_condition_checks(page, [condition(id='bad', selector='['),
                condition(id='absent', kind='attribute', attribute='aria-expanded', expected=None)], 'a', {}, lambda: False)
            self.assertEqual([item['status'] for item in results], ['ERROR', 'PASS'])
        finally:
            context.close()


if __name__ == '__main__':
    unittest.main()
