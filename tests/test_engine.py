import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from PIL import Image

from qa.comparison import image_diff, visual_check
from qa.engine import Budget, _append_issue, _attach_observers, _network_guard, _result_rows, _single_rows, _visit, run_scan
from qa.matching import match_pages, normalize_url, page_key
from qa.policy import (aggregate_status, check, classify_candidate, dangerous_action,
                       host_allowed, http_observation, route_allowed, sanitize_message, sanitize_url,
                       unexecuted_status)


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
        # The folded route is offered as a reviewable candidate, never forced.
        self.assertEqual(rows[0]['match']['candidates'][0]['method'], 'EQUIVALENT_ROUTE')
        self.assertFalse(rows[0]['match']['candidates'][0]['eligible'])

    def test_extension_and_home_alias_pair_when_heading_corroborates(self):
        rows = match_pages([self.page('https://a.test/subject.do', 'Subjects')],
                           [self.page('https://b.test/subject', 'Subjects')])
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]['match']['method'], rows[0]['match']['approved']), ('EQUIVALENT_ROUTE', True))
        rows = match_pages([self.page('https://e.test/main', 'Main')], [self.page('https://stg-e.test/', 'Main')])
        self.assertEqual((rows[0]['match']['method'], rows[0]['match']['approved']), ('EQUIVALENT_ROUTE', True))
        rows = match_pages([self.page('https://a.test/#/notice?id=1', 'N')], [self.page('https://b.test/notice.do?id=2', 'N')])
        self.assertEqual(len(rows), 2, 'Different instance identifiers are never folded')

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

    def test_selected_start_pair_matches_hash_root_to_new_root_without_same_heading(self):
        a = dict(self.page('https://old.test/#/', ''), finalUrl='https://old.test/#/coverPage', title='Legacy title')
        b = dict(self.page('https://new.test/', ''), title='New title')
        start = {'baseline': a['url'], 'candidate': b['url']}
        pairs = match_pages([a], [b], start_pair=start)
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0]['key'], 'start-page')
        self.assertTrue(pairs[0]['match']['approved'])
        self.assertEqual(pairs[0]['match']['method'], 'SELECTED_START_PAGES')
        self.assertIs(pairs[0]['baseline'], a)
        self.assertIs(pairs[0]['candidate'], b)
        self.assertEqual(len(match_pages([a], [b], route_equivalence=False)), 2, 'Opting out must preserve independent identities')
        folded = match_pages([a], [b])
        self.assertEqual(len(folded), 1, 'A #/ prefix alone is an equivalent application route')
        self.assertEqual(folded[0]['match']['method'], 'EQUIVALENT_ROUTE')
        self.assertTrue(folded[0]['match']['approved'])

    def test_start_pair_never_merges_other_hash_routes_or_query_instances(self):
        a = [self.page('https://old.test/#/', ''), self.page('https://old.test/#/notice?id=1', '')]
        b = [self.page('https://new.test/', ''), self.page('https://new.test/notice?id=2', '')]
        pairs = match_pages(a, b, start_pair={'baseline': a[0]['url'], 'candidate': b[0]['url']})
        self.assertEqual(len(pairs), 3)
        self.assertEqual(sum(pair['match']['approved'] for pair in pairs), 1)
        self.assertTrue(any(pair['baseline'] and '#/notice?id=1' in pair['baseline']['url'] for pair in pairs))

    def test_explicit_alias_takes_precedence_over_selected_start_pair(self):
        a, b = self.page('https://old.test/#/'), self.page('https://new.test/')
        pairs = match_pages([a], [b], [{'baseline': '/#/', 'candidate': '/', 'page_class': 'home'}],
                            start_pair={'baseline': a['url'], 'candidate': b['url']})
        self.assertEqual(pairs[0]['match']['method'], 'EXPLICIT_ALIAS')
        self.assertEqual(pairs[0]['key'], 'home')

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

    def test_seven_state_priority_and_prerequisite_policy_distinction(self):
        ordered = ['FAIL', 'ERROR', 'BLOCKED', 'REVIEW', 'DIFF', 'SKIP', 'PASS']
        for index, status in enumerate(ordered):
            checks = [check(str(i), value, 'EXAMPLE') for i, value in enumerate(ordered[index:])]
            self.assertEqual(aggregate_status(checks), status)
        for reason in ('CANCELLED', 'TIME_LIMIT_REACHED', 'PAGE_LIMIT_REACHED', 'MANUAL_AUTH_REQUIRED',
                       'REGION_PREREQUISITE_FAILED', 'NO_COMPARABLE_PIXELS'):
            self.assertEqual(unexecuted_status(reason), 'BLOCKED')
        for reason in ('UNKNOWN_ACTION', 'MUTATING_ACTION', 'ROUTE_NOT_APPROVED'):
            self.assertEqual(unexecuted_status(reason), 'SKIP')

    def test_external_api_errors_are_reviewable(self):
        self.assertEqual(http_observation(403, 'script', False)['level'], 'REVIEW')
        self.assertEqual(http_observation(400, 'fetch', True)['level'], 'REVIEW')
        self.assertEqual(http_observation(404, 'document', True)['level'], 'FAIL')
        self.assertEqual(http_observation(401, 'document', True)['level'], 'BLOCKED')
        self.assertEqual(http_observation(403, 'document', False)['level'], 'REVIEW')
        self.assertEqual(http_observation(403, 'script', True)['level'], 'REVIEW')
        self.assertEqual(http_observation(400, 'document', True)['level'], 'REVIEW')

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
        self.assertEqual(visual_check(result, 2)['status'], 'DIFF')
        self.assertEqual(visual_check(result, 2, comparable=False)['status'], 'REVIEW')
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
        excluded = image_diff(left, b, self.folder, 'run', 'masked')
        self.assertEqual(excluded['error'], 'NO_COMPARABLE_PIXELS')
        self.assertEqual(visual_check(excluded, 2)['status'], 'BLOCKED')

    def test_visual_difference_requires_mapping_and_capture_conditions(self):
        a_file, b_file = self.folder / 'a.png', self.folder / 'b.png'
        Image.new('RGB', (20, 20), 'white').save(a_file)
        Image.new('RGB', (20, 20), 'black').save(b_file)
        a = {'url': 'https://a.test/', 'finalUrl': 'https://a.test/', 'checks': [], 'regions': [],
             'screenshotFile': str(a_file), 'captureReady': True}
        b = dict(a, url='https://b.test/', finalUrl='https://b.test/', screenshotFile=str(b_file))
        pair = {'key': '/', 'baseline': a, 'candidate': b, 'match': {'method': 'EXPLICIT_ALIAS', 'approved': True}}
        self.assertEqual(_result_rows([pair], {}, self.folder, 'run')[0]['status'], 'DIFF')
        b['captureReady'] = False
        self.assertEqual(_result_rows([pair], {}, self.folder, 'run')[0]['status'], 'REVIEW')
        b['captureReady'] = True
        pair['match']['approved'] = False
        self.assertEqual(_result_rows([pair], {}, self.folder, 'run')[0]['status'], 'REVIEW')

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

    def test_hash_seed_bootstrap_document_is_allowed_without_approving_other_routes(self):
        context = self.Context()
        state = {'blocked_urls': set(), 'blocked': [], 'manual_auth': False, 'record': None}
        options = {'allowed_hosts': ['a.test'], 'allowed_paths': []}
        _network_guard(context, options, ('https://a.test/app/#/home',), 'a', state, Budget({}, lambda: False))
        bootstrap = self.Route(self.Request('https://a.test/app/'))
        context.handler(bootstrap)
        self.assertTrue(bootstrap.continued)
        forbidden = self.Route(self.Request('https://a.test/app/#/admin'))
        context.handler(forbidden)
        self.assertTrue(forbidden.aborted)
        self.assertFalse(route_allowed('https://a.test/app/#/admin', options, ['https://a.test/app/#/home']))

    def test_static_resource_approval_does_not_allow_api_navigation_or_writes(self):
        context = self.Context()
        state = {'blocked_urls': set(), 'blocked': [], 'manual_auth': False, 'record': None}
        options = {'allowed_hosts': ['a.test'], 'resource_hosts': ['cdn.test'], 'allowed_paths': []}
        _network_guard(context, options, ('https://a.test/',), 'a', state, Budget({}, lambda: False))
        for method, resource, navigation, allowed in [('GET', 'script', False, True), ('GET', 'image', False, True),
                ('GET', 'fetch', False, False), ('GET', 'xhr', False, False), ('POST', 'script', False, False),
                ('GET', 'document', True, False)]:
            request = self.Request('https://cdn.test/resource', method, navigation)
            request.resource_type = resource
            route = self.Route(request)
            context.handler(route)
            self.assertEqual(route.continued, allowed, (method, resource))
            self.assertEqual(route.aborted, not allowed, (method, resource))


class SingleEnvironmentTests(unittest.TestCase):
    def test_single_family_never_crawls_or_compares_b(self):
        page = {'url': 'https://a.test/', 'finalUrl': 'https://a.test/', 'checks': [check('a.document', 'PASS', 'DOCUMENT_REACHABLE')],
                'regions': [], 'issues': [], 'actions': [], 'navigated': True}
        for test_type in ('single', 'regression', 'conditional'):
            with patch('qa.engine.sync_playwright') as playwright, patch('qa.engine._crawl') as crawl, \
                    patch('qa.engine.match_pages') as matcher, patch('qa.engine.image_diff') as compare:
                browser = playwright.return_value.__enter__.return_value.chromium.launch.return_value
                browser.version = 'synthetic-version'
                crawl.return_value = ({'page': page}, [], {'blocked': []})
                options = {'baseline_url': 'https://a.test/', 'test_type': test_type, 'candidate_url': None}
                report = run_scan(options, 'unit-run', Path('.'), lambda _: None, lambda: False)
                self.assertEqual(crawl.call_count, 1)
                matcher.assert_not_called()
                compare.assert_not_called()
                self.assertIsNone(report['candidateUrl'])
                self.assertEqual(report['totals']['candidateVisited'], 0)
                self.assertEqual(report['manifest']['testType'], test_type)
                self.assertEqual(report['manifest']['schemaVersion'], '2.0')
                self.assertEqual(report['manifest']['ruleVersion'], 'v2.3')
                self.assertEqual(report['results'][0]['match']['method'], 'SINGLE_ENVIRONMENT')
                self.assertFalse(any('NOT_DISCOVERED' in row['flags'] for row in report['results']))
                self.assertEqual({c['reason_code'] for c in report['results'][0]['checks']}, {'DOCUMENT_REACHABLE'})

    def test_single_has_no_implicit_visual_pass_and_preserves_blocked(self):
        page = {'url': 'https://a.test/', 'finalUrl': 'https://a.test/', 'checks': [], 'regions': []}
        self.assertEqual(_single_rows({'page': page}, {})[0]['status'], 'SKIP')
        page['checks'] = [check('auth', 'BLOCKED', 'LOGIN_REQUIRED')]
        row = _single_rows({'page': page}, {})[0]
        self.assertEqual(row['status'], 'BLOCKED')
        self.assertIsNone(row['visual'])

    def test_auth_document_blocks_protected_ui_instead_of_missing_element_fail(self):
        for status, expected in ((401, 'BLOCKED'), (403, 'BLOCKED'), (400, 'REVIEW')):
            context = MagicMock()
            context.new_page.return_value.goto.return_value.status = status
            context.new_page.return_value.url = 'https://a.test/protected'
            options = {'baseline_url': 'https://a.test/protected', 'candidate_url': None, 'mode': 'visual',
                       'regions': [{'id': 'protected', 'selector': '#protected', 'required': True}]}
            with patch('qa.engine._capture') as capture:
                record = _visit(context, options['baseline_url'], 'a', 0, options, Path('.'), 'unit',
                                Budget({}, lambda: False), {'blocked_urls': set(), 'scenario_done': False})
                capture.assert_not_called()
                document = next(c for c in record['checks'] if c['check_id'] == 'a.document')
                self.assertEqual(document['status'], expected)
                self.assertFalse(any(c['status'] == 'FAIL' for c in record['checks']))
                self.assertEqual(_single_rows({'page': record}, options)[1]['status'], 'BLOCKED')

    def test_public_route_key_does_not_expose_secret_query(self):
        page = {'url': 'https://a.test/path?token=fixture-secret', 'finalUrl': 'https://a.test/path?token=fixture-secret',
                'checks': [], 'regions': []}
        row = _single_rows({'page': page}, {})[0]
        self.assertNotIn('fixture-secret', str(row))


class ObservationTests(unittest.TestCase):
    def test_policy_interference_and_request_aborts_keep_cause_uncertain(self):
        callbacks = {}
        page = MagicMock(url='https://a.test/')
        page.on.side_effect = lambda event, callback: callbacks.__setitem__(event, callback)
        record = {'url': 'https://a.test/', 'runId': 'run', 'environment': 'a', 'pageId': 'page', 'issues': []}
        _attach_observers(page, {'blocked_urls': set(), 'record': record})
        _append_issue(record, 'POLICY_BLOCKED', 'SKIP', 'HOST_NOT_APPROVED', 'https://cdn.test/jquery.js',
                      resourceType='script', method='GET', source='POLICY')
        callbacks['pageerror'](RuntimeError('$ is not defined'))
        callbacks['console'](type('Console', (), {'type': 'error', 'text': 'net::ERR_BLOCKED_BY_CLIENT'})())
        for issue in record['issues'][1:]:
            self.assertEqual(issue['level'], 'REVIEW')
            self.assertTrue(issue['policyInterference'])
            self.assertFalse(issue['causeConfirmed'])
            self.assertEqual(issue['relatedBlockedRequests'][0]['url'], 'https://cdn.test/jquery.js')
        request = RequestGuardTests.Request('https://a.test/prefetch', navigation=False)
        request.resource_type, request.failure = 'fetch', 'net::ERR_ABORTED'
        callbacks['requestfailed'](request)
        self.assertEqual(record['issues'][-1]['category'], 'REQUEST_ABORTED')
        self.assertEqual(record['issues'][-1]['level'], 'REVIEW')
        record['_closing'] = True
        callbacks['requestfailed'](request)
        self.assertEqual(record['issues'][-1]['category'], 'REQUEST_CANCELLED_BY_RUNNER')
        self.assertEqual(record['issues'][-1]['level'], 'SKIP')
        self.assertEqual(record['issues'][-1]['source'], 'RUNNER')

    def test_request_identity_source_and_repetition_preserved(self):
        record = {'url': 'https://a.test/', 'runId': 'run', 'environment': 'a', 'pageId': 'page', 'issues': []}
        first = _append_issue(record, 'HTTP_4XX', 'REVIEW', '404 image', 'https://a.test/a.png',
                              requestId='r1', source='FIRST_PARTY', method='GET', resourceType='image', statusCode=404)
        _append_issue(record, 'HTTP_4XX', 'REVIEW', '404 image', 'https://a.test/a.png',
                      requestId='r1', source='FIRST_PARTY', method='GET', resourceType='image', statusCode=404)
        _append_issue(record, 'HTTP_4XX', 'REVIEW', '404 image', 'https://a.test/a.png', requestId='r2')
        self.assertEqual(len(record['issues']), 2)
        self.assertEqual(first['count'], 2)
        self.assertTrue(first['timestamp'])
        self.assertTrue(first['lastSeenAt'])
        self.assertEqual((first['source'], first['environment'], first['resourceType'], first['method']),
                         ('FIRST_PARTY', 'a', 'image', 'GET'))

    def test_response_callback_keeps_request_metadata(self):
        callbacks = {}
        page = MagicMock()
        page.on.side_effect = lambda event, callback: callbacks.__setitem__(event, callback)
        record = {'url': 'https://a.test/', 'runId': 'run', 'environment': 'a', 'pageId': 'page', 'issues': []}
        _attach_observers(page, {'blocked_urls': set(), 'record': record})
        request = RequestGuardTests.Request('https://external.test/widget.js')
        request.resource_type = 'script'
        response = MagicMock(status=403, url=request.url, request=request)
        callbacks['response'](response)
        callbacks['response'](response)
        self.assertEqual(len(record['issues']), 1)
        issue = record['issues'][0]
        self.assertEqual((issue['count'], issue['source'], issue['statusCode']), (2, 'THIRD_PARTY', 403))
        self.assertTrue(issue['requestId'])


class ManualAuthPreservationTests(unittest.TestCase):
    def test_auth_failure_is_structured_and_keeps_completed_other_side(self):
        cases = ((InterruptedError('cancel'), 'CANCELLED', 'BLOCKED', 'CANCELLED'),
                 (TimeoutError('deadline'), 'AUTH_TIME_LIMIT_REACHED', 'BLOCKED', 'PARTIAL'),
                 (RuntimeError('browser closed'), 'MANUAL_AUTH_ERROR', 'ERROR', 'PARTIAL'))
        for failure_side in ('a', 'b'):
            for exception, reason, status, run_status in cases:
                with self.subTest(side=failure_side, exception=type(exception).__name__), \
                        patch('qa.engine.sync_playwright') as playwright, patch('qa.engine._visit') as visit:
                    browser = playwright.return_value.__enter__.return_value.chromium.launch.return_value
                    browser.version = 'synthetic-version'
                    contexts = [MagicMock(), MagicMock()]
                    browser.new_context.side_effect = contexts
                    def observed(_context, url, side, depth, *_):
                        return {'url': url, 'finalUrl': url, 'title': 'Ready', 'heading': 'Ready', 'structure': 'main',
                                'statusCode': 200, 'issues': [], 'actions': [], 'regions': [], 'navigated': True,
                                'checks': [check(side + '.document', 'PASS', 'DOCUMENT_REACHABLE', expected='HTTP <400', actual=200)]}
                    visit.side_effect = observed
                    def auth_gate(side, _context, _url):
                        if side == failure_side:
                            raise exception
                    options = {'baseline_url': 'https://a.test/', 'candidate_url': 'https://b.test/',
                               'manual_login': True, 'mode': 'discovery', 'max_pages': 1, 'max_depth': 0,
                               'route_aliases': [{'baseline': '/', 'candidate': '/', 'page_class': 'home'}]}
                    report = run_scan(options, 'auth-unit', Path('.'), lambda _: None, lambda: False, auth_gate)
                    self.assertEqual(report['manifest']['status'], run_status)
                    checks = [item for row in report['results'] for item in row['checks']]
                    self.assertTrue(any(c['reason_code'] == reason and c['status'] == status for c in checks))
                    if failure_side == 'b':
                        self.assertEqual(report['totals']['baselineVisited'], 1)
                        self.assertTrue(any(c['check_id'] == 'a.document' and c['status'] == 'PASS' for c in checks))
                        self.assertEqual(report['totals']['candidateVisited'], 0)
                    for context in contexts[:browser.new_context.call_count]:
                        context.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
