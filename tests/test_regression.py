import copy
import unittest

from qa.regression import evaluate_regression


def report(status='FAIL', test_type='single'):
    item = {'check_id': 'condition.help', 'environment': 'a', 'scenario_id': 'conditions', 'step_id': 'help',
            'status': status, 'reason_code': 'REQUIRED_ELEMENT_MISSING' if status == 'FAIL' else 'CONDITION_SATISFIED',
            'expected': True, 'actual': status == 'PASS', 'executed': status in ('PASS', 'FAIL')}
    return {'manifest': {'schemaVersion': '2.0', 'runId': 'run', 'ruleVersion': 'v2', 'rulesHash': 'same',
                        'profileId': 'synthetic', 'mode': 'combined', 'viewport': {'width': 1000, 'height': 700},
                        'scenarioIds': [], 'conditions': [], 'routeAliases': [], 'dataPolicy': 'INDEPENDENT',
                        'scope': {'targetShape': 'single', 'maxPages': 5}, 'capture': {'browser': 'fixed'},
                        'testType': test_type, 'status': 'COMPLETED'},
            'results': [{'id': 'row-1', 'key': 'home', 'region_id': 'page', 'status': status,
                         'baseline': {'url': 'http://localhost/demo/a/'}, 'candidate': None,
                         'checks': [item], 'review': {'status': 'UNREVIEWED', 'revision': 0, 'events': []}}]}


class RegressionTests(unittest.TestCase):
    def test_repeated_finding_and_single_to_regression_purpose_are_comparable(self):
        old, new = report(), report(test_type='regression')
        result = evaluate_regression(old, new)
        self.assertTrue(result['comparable'])
        self.assertEqual(result['summary']['RECURRING'], 1)
        self.assertEqual(result['rows']['row-1']['classification'], 'RECURRING')

    def test_explicit_pass_is_resolution_candidate_not_bug_closure(self):
        old, new = report(), report('PASS')
        original = copy.deepcopy(old)
        result = evaluate_regression(old, new)
        self.assertEqual(result['summary']['RESOLVED_CANDIDATE'], 1)
        self.assertTrue(result['findings'][0]['requiresReview'])
        self.assertEqual(old, original)

    def test_executed_null_attribute_contract_can_resolve(self):
        old, new = report(), report('PASS')
        new['results'][0]['checks'][0].update(expected=None, executed=True, actual=None)
        self.assertEqual(evaluate_regression(old, new)['summary']['RESOLVED_CANDIDATE'], 1)

    def test_missing_or_blocked_check_never_resolves(self):
        for state in ('BLOCKED', 'SKIP', 'ERROR', 'REVIEW', None):
            with self.subTest(state=state):
                current = report(state or 'PASS')
                if state is None:
                    current['results'][0]['checks'] = []
                result = evaluate_regression(report(), current)
                self.assertEqual(result['summary']['RESOLVED_CANDIDATE'], 0)
                self.assertGreaterEqual(result['summary']['NOT_RETESTED'], 1)

    def test_new_failure_requires_verified_prior_assertion(self):
        self.assertEqual(evaluate_regression(report('PASS'), report())['summary']['NEW'], 1)
        for state in ('BLOCKED', 'ERROR', 'SKIP', None):
            old = report(state or 'PASS')
            if state is None:
                old['results'][0]['checks'] = []
            result = evaluate_regression(old, report())
            self.assertEqual(result['summary']['NEW'], 0)
            self.assertTrue(any(item['reason'] == 'BASELINE_ASSERTION_NOT_VERIFIED' for item in result['findings']))

    def test_changed_contract_dimensions_prevent_comparison(self):
        for field in ('rulesHash', 'ruleVersion', 'mode', 'profileId', 'viewport', 'scenarioIds',
                      'conditions', 'routeAliases', 'dataPolicy', 'scope', 'capture'):
            with self.subTest(field=field):
                changed = report('PASS')
                changed['manifest'][field] = {'changed': True}
                result = evaluate_regression(report(), changed)
                self.assertFalse(result['comparable'])
                self.assertEqual(result['summary']['RESOLVED_CANDIDATE'], 0)
                self.assertIn(field, [item['field'] for item in result['reasons']])

    def test_legacy_and_missing_metadata_are_reported_without_file_access(self):
        legacy = report()
        legacy['manifest'] = {'schemaVersion': '1.0'}
        result = evaluate_regression(legacy, report('PASS'))
        self.assertEqual(result['previousSchemaVersion'], '1.0')
        self.assertFalse(result['comparability']['comparable'])
        self.assertIn('LEGACY_OR_INCOMPATIBLE_SCHEMA', [reason['code'] for reason in result['reasons']])
        with self.assertRaises(ValueError):
            evaluate_regression('C:/private/report.json', report())

    def test_optional_row_reordering_does_not_change_assertion_identity(self):
        old = report()
        duplicate = copy.deepcopy(old['results'][0])
        duplicate.update(id='row-region', region_id='help')
        old['results'].append(duplicate)
        current = report('PASS')
        result = evaluate_regression(old, current)
        self.assertEqual(result['summary']['RESOLVED_CANDIDATE'], 1)

    def test_engine_request_derived_hash_ids_recur_across_runs(self):
        from qa.engine import _append_issue
        from qa.findings import enrich_report
        from qa.policy import check

        for category, message, resource_type, status_code in (
                ('HTTP_5XX', '500 fetch', 'fetch', 500),
                ('HTTP_5XX', '500 xhr', 'xhr', 500),
                ('NETWORK_ERROR', 'net::ERR_CONNECTION_RESET', 'fetch', None)):
            with self.subTest(category=category, resource_type=resource_type):
                reports = []
                for run_id in ('previous-run', 'current-run'):
                    record = {'runId': run_id, 'environment': 'a', 'pageId': 'stable-page',
                              'url': 'https://synthetic.invalid/', 'issues': []}
                    observation = _append_issue(record, category, 'REVIEW', message,
                        'https://synthetic.invalid/api/list', requestId=run_id + '-request',
                        method='GET', resourceType=resource_type, source='FIRST_PARTY', statusCode=status_code)
                    item = check('a.observation.' + observation['observationId'], observation['level'],
                                 category, expected='Healthy required resources / review optional observations',
                                 actual=message)
                    item.update(environment='a', observation=observation)
                    value = report('REVIEW')
                    value['manifest']['runId'] = run_id
                    value['results'][0]['checks'] = [item]
                    value['results'][0]['baseline']['issues'] = [observation]
                    reports.append(value)
                before, after = [enrich_report(value) for value in reports]
                self.assertNotEqual(before['findings'][0]['observations'][0]['observationId'],
                                    after['findings'][0]['observations'][0]['observationId'])
                self.assertEqual(before['findings'][0]['fingerprint'], after['findings'][0]['fingerprint'])
                result = evaluate_regression(*reports)
                self.assertEqual(result['summary']['RECURRING'], 1)
                self.assertEqual(result['summary']['NOT_RETESTED'], 0)
                self.assertEqual(result['summary']['NON_COMPARABLE'], 0)

    def test_policy_observations_recur_as_infrastructure_without_confirming_product_cause(self):
        from qa.engine import _append_issue
        from qa.findings import enrich_report
        from qa.policy import check

        for category, message in (
                ('JS_ERROR_AFTER_POLICY_BLOCK', 'ReferenceError: sampleLibrary is not defined'),
                ('CONSOLE_ERROR_AFTER_POLICY_BLOCK', 'Failed to load resource: net::ERR_BLOCKED_BY_CLIENT'),
                ('CONSOLE_ERROR', 'Failed to load resource: net::ERR_BLOCKED_BY_CLIENT')):
            with self.subTest(category=category):
                reports = []
                for run_id in ('previous-run', 'current-run'):
                    record = {'runId': run_id, 'environment': 'a', 'pageId': 'stable-page',
                              'url': 'https://synthetic.invalid/', 'issues': []}
                    details = {'source': 'BROWSER'}
                    if category.endswith('_AFTER_POLICY_BLOCK'):
                        details.update(policyInterference=True, causeConfirmed=False,
                            relatedBlockedRequests=[{'url': 'https://static.invalid/' + run_id + '.js',
                                                     'reason': 'HOST_NOT_APPROVED', 'method': 'GET',
                                                     'resourceType': 'script'}])
                    obs = _append_issue(record, category, 'REVIEW', message, record['url'], **details)
                    item = check('a.observation.' + obs['observationId'], 'REVIEW', category, actual=message)
                    item.update(environment='a', observation=obs)
                    value = report('REVIEW')
                    value['manifest']['runId'] = run_id
                    value['results'][0]['checks'] = [item]
                    value['results'][0]['baseline']['issues'] = [obs]
                    reports.append(value)
                result = evaluate_regression(*reports)
                self.assertEqual(result['summary']['RECURRING'], 1)
                self.assertEqual(result['summary']['RESOLVED_CANDIDATE'], 0)
                self.assertEqual(result['findings'][0]['category'], 'TEST_INFRA')
                current = enrich_report(reports[1])['findings'][0]
                self.assertEqual(current['status'], 'REVIEW')
                self.assertNotIn('bugConfirmed', current)
                if category.endswith('_AFTER_POLICY_BLOCK'):
                    self.assertFalse(current['causeConfirmed'])

    def test_policy_affected_js_is_not_recurrence_or_resolution_of_unaffected_js(self):
        from qa.engine import _append_issue
        from qa.policy import check

        reports = []
        for category, status in (('JS_ERROR', 'FAIL'), ('JS_ERROR_AFTER_POLICY_BLOCK', 'REVIEW')):
            record = {'environment': 'a', 'pageId': 'stable-page', 'url': 'https://synthetic.invalid/', 'issues': []}
            obs = _append_issue(record, category, status, 'ReferenceError: sampleLibrary is not defined', record['url'])
            item = check('a.observation.' + obs['observationId'], status, category, actual=obs['message'])
            item.update(environment='a', observation=obs)
            value = report(status)
            value['results'][0]['checks'] = [item]
            reports.append(value)
        result = evaluate_regression(*reports)
        self.assertEqual(result['summary']['RECURRING'], 0)
        self.assertEqual(result['summary']['RESOLVED_CANDIDATE'], 0)
        self.assertEqual(result['summary']['NOT_RETESTED'], 1)
        self.assertEqual(result['summary']['NON_COMPARABLE'], 1)


if __name__ == '__main__':
    unittest.main()
