import tempfile
import unittest
from pathlib import Path

from PIL import Image

from qa.comparison import image_diff, visual_check
from qa.engine import Budget, _network_guard, _result_rows
from qa.matching import match_pages, normalize_url, page_key
from qa.policy import (aggregate_status, check, classify_candidate, dangerous_action,
                       host_allowed, http_observation, route_allowed, sanitize_message, sanitize_url)


class MatchingTests(unittest.TestCase):
    def page(self, url, heading='Materials'):
        return {'url': url, 'heading': heading, 'structure': 'nav|main|h1'}

    def test_hash_routes_and_query_order_survive(self):
        self.assertNotEqual(normalize_url('https://a.test/#/one'), normalize_url('https://a.test/#/two'))
        self.assertEqual(page_key('https://a.test/search?tag=b&tag=a#/tab?x=2'), '/search?tag=b&tag=a#/tab?x=2')

    def test_bad_url_credentials_and_schemes_rejected(self):
        for value in ('file:///tmp/data', 'https://name:secret@a.test/', '', 'javascript:alert(1)'):
            with self.assertRaises(ValueError):
                normalize_url(value)

    def test_extension_not_globally_removed(self):
        a = self.page('https://a.test/subject.do', 'Legacy')
        b = self.page('https://b.test/subject', 'New')
        rows = match_pages([a], [b])
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(not row['match']['approved'] for row in rows))

    def test_explicit_alias_with_same_instance_query(self):
        alias = [{'baseline': '/subject.do', 'candidate': '/subject', 'page_class': 'subject'}]
        rows = match_pages([self.page('https://a.test/subject.do?page=2')],
                           [self.page('https://b.test/subject?page=2')], alias)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['match']['method'], 'EXPLICIT_ALIAS')
        self.assertTrue(rows[0]['match']['approved'])

    def test_different_data_instances_not_alias_matched(self):
        alias = [{'baseline': '/subject.do', 'candidate': '/subject'}]
        rows = match_pages([self.page('https://a.test/subject.do?id=1')],
                           [self.page('https://b.test/subject?id=2')], alias)
        self.assertFalse(any(row['match']['approved'] for row in rows))

    def test_arbitrary_roots_not_forced_pair(self):
        rows = match_pages([self.page('https://a.test/home', 'Home')],
                           [self.page('https://b.test/login', 'Login')])
        self.assertEqual(len(rows), 2)

    def test_same_heading_different_route_is_review_candidate(self):
        rows = match_pages([self.page('https://a.test/one')], [self.page('https://b.test/two')])
        self.assertEqual(rows[0]['match']['method'], 'STRUCTURE_CANDIDATE')
        self.assertFalse(rows[0]['match']['approved'])

    def test_ambiguous_explicit_mapping_not_trusted(self):
        rules = [{'baseline': '/one', 'candidate': '/two'}, {'baseline': '/one', 'candidate': '/three'}]
        rows = match_pages([self.page('https://a.test/one')], [self.page('https://b.test/two')], rules)
        self.assertFalse(rows[0]['match']['approved'])


class PolicyTests(unittest.TestCase):
    def test_no_checks_or_only_skips_cannot_pass(self):
        self.assertEqual(aggregate_status([]), 'SKIP')
        self.assertEqual(aggregate_status([check('x', 'SKIP', 'UNKNOWN')]), 'SKIP')
        self.assertEqual(aggregate_status([check('x', 'PASS', 'OK'), check('y', 'SKIP', 'MISSING')]), 'SKIP')

    def test_status_preserves_fail_and_infrastructure_error(self):
        checks = [check('x', 'FAIL', 'DEFECT'), check('y', 'ERROR', 'RUNNER')]
        self.assertEqual(aggregate_status(checks), 'FAIL')
        self.assertEqual(len([c for c in checks if c['status'] == 'ERROR']), 1)

    def test_optional_discovery_skip_does_not_erase_assertion(self):
        self.assertEqual(aggregate_status([check('x', 'PASS', 'OK'), check('y', 'SKIP', 'UNKNOWN', required=False)]), 'PASS')

    def test_external_api_errors_are_reviewable(self):
        self.assertEqual(http_observation(403, 'script', False)['level'], 'REVIEW')
        self.assertEqual(http_observation(400, 'fetch', True)['level'], 'REVIEW')
        self.assertEqual(http_observation(404, 'document', True)['level'], 'FAIL')

    def test_unsafe_labels_override_allowlist_and_unknown_buttons_skip(self):
        options = {'allowed_hosts': ['a.test'], 'safe_actions': [{'selector': '#delete'}]}
        self.assertFalse(classify_candidate({'selector': '#delete', 'label': '삭제', 'visible': True}, options)[0])
        self.assertEqual(classify_candidate({'selector': '#unknown', 'label': 'Open', 'visible': True}, options)[1], 'UNKNOWN_ACTION')
        self.assertEqual(dangerous_action({'type': 'submit'}), 'FORM_SUBMIT_NOT_APPROVED')

    def test_approved_host_does_not_approve_every_route(self):
        options = {'allowed_hosts': ['a.test'], 'allowed_paths': ['/safe']}
        self.assertTrue(classify_candidate({'href': 'https://a.test/safe'}, options)[0])
        self.assertFalse(classify_candidate({'href': 'https://a.test/unknown'}, options)[0])
        self.assertFalse(host_allowed('https://sub.a.test/safe', options['allowed_hosts']))

    def test_seed_does_not_approve_every_hash_route(self):
        self.assertTrue(route_allowed('https://a.test/#/home?q=1', {}, ['https://a.test/#/home']))
        self.assertFalse(route_allowed('https://a.test/#/admin', {}, ['https://a.test/#/home']))
        self.assertFalse(route_allowed('https://a.test/#/admin', {}, ['https://a.test/']))
        self.assertTrue(route_allowed('https://a.test/#/search', {'allowed_paths': ['/#/search']}, ['https://a.test/']))

    def test_credentials_redacted_from_public_evidence(self):
        value = sanitize_url('https://user:secret@a.test/a?token=abc&x=1#/b?password=xyz')
        for forbidden in ('secret', 'abc', 'xyz', 'user:'):
            self.assertNotIn(forbidden, value)
        self.assertNotIn('someone@example.com', sanitize_message('error someone@example.com token=abc'))
        self.assertNotIn('fixture-secret', sanitize_url('https://a.test/#access_token=fixture-secret&state=x'))
        self.assertNotIn('fixture-secret', sanitize_url('https://a.test/?api_key=fixture-secret'))
        self.assertEqual(sanitize_url('https://a.test/#/notice?id=10'), 'https://a.test/#/notice?id=10')

    def test_cancellation_and_zero_action_budget(self):
        self.assertEqual(Budget({}, lambda: True).reason(), 'CANCELLED')
        self.assertFalse(Budget({'max_actions': 0}, lambda: False).action(None))


class ComparisonTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1] / 'output' / 'tmp'
        root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=root)
        self.folder = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_real_pixel_difference_and_missing_evidence(self):
        a, b = self.folder / 'a.png', self.folder / 'b.png'
        Image.new('RGB', (20, 20), 'white').save(a)
        Image.new('RGB', (20, 20), 'black').save(b)
        result = image_diff(a, b, self.folder, 'run', 'page')
        self.assertEqual(result['differencePercent'], 100)
        self.assertEqual(visual_check(result, 2)['status'], 'REVIEW')
        self.assertEqual(visual_check(image_diff(None, b, self.folder, 'run', 'page'), 2)['status'], 'ERROR')

    def test_size_mismatch_and_corrupt_file_are_errors(self):
        a, b = self.folder / 'a.png', self.folder / 'b.png'
        Image.new('RGB', (20, 20), 'white').save(a)
        Image.new('RGB', (10, 20), 'white').save(b)
        self.assertEqual(image_diff(a, b, self.folder, 'run', 'page')['error'], 'IMAGE_SIZE_MISMATCH')
        b.write_text('not an image', encoding='utf-8')
        self.assertEqual(visual_check(image_diff(a, b, self.folder, 'run', 'page'), 2)['status'], 'ERROR')

    def test_masked_pixels_are_excluded_from_comparison_denominator(self):
        a, b = self.folder / 'a.png', self.folder / 'b.png'
        Image.new('RGB', (20, 20), 'white').save(a)
        Image.new('RGB', (20, 20), 'black').save(b)
        left = {'screenshotFile': str(a), 'maskBoxes': [[0, 0, 10, 20]]}
        result = image_diff(left, {'screenshotFile': str(b)}, self.folder, 'run', 'masked')
        self.assertEqual(result['maskedPixels'], 200)
        self.assertEqual(result['comparedPixels'], 200)
        self.assertEqual(result['differencePercent'], 100)
        left['maskBoxes'] = [[0, 0, 20, 20]]
        self.assertEqual(image_diff(left, b, self.folder, 'run', 'masked')['error'], 'NO_COMPARABLE_PIXELS')

    def test_report_does_not_turn_null_comparison_into_pass(self):
        a = {'url': 'https://a.test/', 'finalUrl': 'https://a.test/', 'checks': [check('a.document', 'PASS', 'OK')], 'regions': []}
        b = dict(a, url='https://b.test/', finalUrl='https://b.test/', checks=[check('b.document', 'PASS', 'OK')])
        rows = _result_rows([{'key': '/', 'baseline': a, 'candidate': b,
                              'match': {'method': 'EXPLICIT_ALIAS', 'approved': True}}], {}, self.folder, 'run')
        self.assertEqual(rows[0]['status'], 'ERROR')


class RequestGuardTests(unittest.TestCase):
    class Context:
        def route(self, pattern, handler):
            self.handler = handler

    class Request:
        def __init__(self, url, method='GET', navigation=True):
            self.url, self.method = url, method
            self.resource_type = 'document'
            self.navigation = navigation

        def is_navigation_request(self):
            return self.navigation

    class Route:
        def __init__(self, request):
            self.request, self.aborted, self.continued = request, False, False

        def abort(self, reason):
            self.aborted = True

        def continue_(self):
            self.continued = True

    def test_redirect_host_and_write_requests_block_before_continue(self):
        context = self.Context()
        state = {'blocked_urls': set(), 'blocked': [], 'manual_auth': False, 'record': None}
        options = {'allowed_hosts': ['a.test'], 'allowed_paths': ['/safe']}
        _network_guard(context, options, ('https://a.test/', 'https://a.test/'), 'a', state,
                       Budget({}, lambda: False))
        for request in (self.Request('https://evil.test/safe'), self.Request('https://a.test/safe', 'POST'),
                        self.Request('https://a.test/delete?id=1')):
            route = self.Route(request)
            context.handler(route)
            self.assertTrue(route.aborted)
            self.assertFalse(route.continued)
        good = self.Route(self.Request('https://a.test/safe'))
        context.handler(good)
        self.assertTrue(good.continued)
        self.assertEqual(len(state['blocked']), 3)


if __name__ == '__main__':
    unittest.main()
