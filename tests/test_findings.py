import copy
import unittest

from qa.findings import TAXONOMY, classify, enrich_report


def report(rows):
    return {'manifest': {'schemaVersion': '2.0', 'startedAt': '2026-11-03T01:00:00Z', 'finishedAt': '2026-11-03T01:01:00Z'},
            'totals': {'fail': len(rows)}, 'results': rows}


def row(checks, identity='home', identifier='row-1', issues=None, side='a'):
    return {'id': identifier, 'key': identity, 'region_id': 'page', 'status': 'FAIL', 'checks': checks,
            'baseline': {'url': 'http://localhost/site/', 'issues': issues or []} if side == 'a' else None,
            'candidate': {'url': 'http://localhost/site/', 'issues': issues or []} if side == 'b' else None,
            'review': {'status': 'BUG_CONFIRMED', 'revision': 1, 'events': []}}


def observation(identifier='o1', request='r1', **changes):
    return {'observationId': identifier, 'requestId': request, 'category': 'HTTP_4XX', 'level': 'REVIEW',
            'statusCode': 404, 'resourceType': 'image', 'method': 'GET', 'source': 'FIRST_PARTY',
            'environment': 'a', 'url': 'https://site.invalid/assets/missing.png', 'message': '404 image',
            'timestamp': '2026-11-03T01:00:00Z', 'lastSeenAt': '2026-11-03T01:00:01Z', 'count': 1,
            'scenarioId': 'engine', 'stepId': 'observe', **changes}


def observation_check(obs, index=0):
    return {'check_id': f'a.observation.{index}', 'status': obs['level'], 'reason_code': obs['category'],
            'environment': obs['environment'], 'scenario_id': 'engine', 'step_id': 'observe',
            'observation': copy.deepcopy(obs), 'actual': obs['message']}


class FindingsTests(unittest.TestCase):
    def test_taxonomy_has_twelve_distinct_categories(self):
        self.assertEqual(len(TAXONOMY), 12)
        self.assertEqual(set(TAXONOMY), {'HTTP','NETWORK','JAVASCRIPT','API','RESOURCE','NAVIGATION',
                                      'STRUCTURE','FUNCTIONAL','VISUAL','DATA','AUTH','TEST_INFRA'})

    def test_page_and_region_duplicate_check_count_once_and_original_remains_unchanged(self):
        item = {'check_id': 'a.region.notice', 'status': 'FAIL', 'reason_code': 'REQUIRED_REGION_MISSING',
                'expected': 1, 'actual': 0}
        page = row([item])
        region = copy.deepcopy(page)
        region.update(id='row-2', region_id='notice')
        original = report([page, region])
        before = copy.deepcopy(original)
        result = enrich_report(original)
        self.assertEqual(original, before)
        self.assertEqual(result['totals']['uniqueFindings'], 1)
        self.assertEqual(result['findings'][0]['occurrenceCount'], 1)
        self.assertCountEqual(result['findings'][0]['rowIds'], ['row-1', 'row-2'])
        self.assertEqual(result['results'][0]['review'], before['results'][0]['review'])
        self.assertEqual(result['results'][0]['status'], 'FAIL')

    def test_image_404_is_one_resource_finding_with_http_tags(self):
        obs = observation(count=3)
        result = enrich_report(report([row([observation_check(obs)], issues=[obs])]))
        finding = result['findings'][0]
        self.assertEqual((finding['category'], finding['subtype']), ('RESOURCE', 'IMAGE_LOAD_FAILED'))
        self.assertIn('HTTP_404', finding['tags'])
        self.assertIn('HTTP_4XX', finding['tags'])
        self.assertEqual((result['totals']['rawObservations'], result['totals']['uniqueFindings']), (3, 1))
        self.assertEqual(finding['occurrenceCount'], 3)

    def test_image_http_and_dom_failure_share_representative_finding(self):
        http = observation()
        dom = observation('o2', None, category='BROKEN_IMAGE', level='FAIL', resourceType=None,
                          statusCode=None, method=None, source='BROWSER', message='Visible image failed to load')
        result = enrich_report(report([row([observation_check(http), observation_check(dom, 1)], issues=[http, dom])]))
        self.assertEqual(result['totals']['rawObservations'], 2)
        self.assertEqual(result['totals']['uniqueFindings'], 1)
        self.assertEqual(result['findings'][0]['occurrenceCount'], 1)
        self.assertEqual(len(result['findings'][0]['observations']), 2)

    def test_repeated_requests_merge_but_environments_pages_steps_and_rules_do_not(self):
        one, two = observation(), observation('o2', 'r2', timestamp='2026-11-03T01:00:05Z', lastSeenAt='2026-11-03T01:00:06Z')
        result = enrich_report(report([row([observation_check(one), observation_check(two, 1)], issues=[one, two])]))
        self.assertEqual(result['totals']['uniqueFindings'], 1)
        self.assertEqual(result['findings'][0]['occurrenceCount'], 2)
        self.assertEqual(result['findings'][0]['lastSeenAt'], '2026-11-03T01:00:06Z')
        base = {'check_id': 'required', 'status': 'FAIL', 'reason_code': 'REQUIRED_ELEMENT_MISSING', 'environment': 'a', 'step_id': 'open'}
        rows = [row([base]), row([{**base, 'environment': 'b'}], identifier='row-2', side='b'),
                row([base], identity='search', identifier='row-3'),
                row([{**base, 'step_id': 'close'}, {**base, 'check_id': 'another'}], identifier='row-4')]
        self.assertEqual(enrich_report(report(rows))['totals']['uniqueFindings'], 5)

    def test_api_status_without_contract_stays_http(self):
        obs = observation(resourceType='fetch', statusCode=500, category='HTTP_5XX')
        raw = observation_check(obs)
        self.assertEqual(classify(raw), ('HTTP', 'HTTP_5XX'))
        explicit = {**raw, 'category': 'API', 'reason_code': 'API_STATUS_MISMATCH', 'expected': {'status': 200}}
        self.assertEqual(classify(explicit), ('API', 'API_STATUS_MISMATCH'))

    def test_fingerprint_survives_run_ids_request_ids_and_array_indexes(self):
        a = observation(runId='old-run')
        b = observation('different-event', 'different-request', runId='new-run')
        first = enrich_report(report([row([observation_check(a, 0)])]))
        second = enrich_report(report([row([observation_check(b, 99)], identifier='another-row')]))
        self.assertEqual(first['findings'][0]['fingerprint'], second['findings'][0]['fingerprint'])

    def test_generated_observations_preserve_explicit_distinct_rule_ids(self):
        first = observation(resourceType='fetch', statusCode=500, category='HTTP_5XX', ruleId='required-api')
        second = observation('o2', 'r2', resourceType='fetch', statusCode=500, category='HTTP_5XX', ruleId='status-contract')
        checks = [observation_check(first), observation_check(second)]
        checks[0]['check_id'] = 'a.observation.9fbe47c9aa4df0123344'
        checks[1]['check_id'] = 'a.observation.72f4bf35-a7c2-4157-bf63-8dd0f841c8e0'
        result = enrich_report(report([row(checks)]))
        self.assertEqual(result['totals']['uniqueFindings'], 2)
        self.assertEqual({item['checkId'] for item in result['findings']},
                         {'observation.required-api', 'observation.status-contract'})

    def test_engine_observations_keep_three_steps_and_merge_only_same_step_repeats(self):
        from qa.engine import _append_issue
        from qa.policy import check

        record = {'runId': 'same-run', 'environment': 'a', 'pageId': 'same-page',
                  'url': 'https://synthetic.invalid/', 'issues': []}
        stages = [('demo.search', 'button-search'), ('demo.search', 'enter-search'),
                  ('demo.history', 'reload-detail'), ('demo.search', 'button-search')]
        for scenario, step in stages:
            record['_active_scenario'], record['_active_step'] = scenario, step
            _append_issue(record, 'HTTP_5XX', 'REVIEW', '500 fetch',
                          'https://synthetic.invalid/api/list', requestId=scenario + ':' + step,
                          resourceType='fetch', statusCode=500, method='GET', source='FIRST_PARTY')
        checks = []
        for obs in record['issues']:
            # Intentionally model the previous engine wrapper defaults. Enrichment
            # must also correct already-saved reports, not only new engine output.
            item = check('a.observation.' + obs['observationId'], 'REVIEW', 'HTTP_5XX')
            item['observation'] = dict(obs)
            checks.append(item)
        result = enrich_report(report([row(checks, issues=record['issues'])]))
        observed = {(item['scenarioId'], item['stepId']): item['occurrenceCount'] for item in result['findings']}
        self.assertEqual(observed, {('demo.search', 'button-search'): 2,
                                    ('demo.search', 'enter-search'): 1,
                                    ('demo.history', 'reload-detail'): 1})
        self.assertEqual(result['totals']['rawObservations'], 4)
        self.assertEqual(result['totals']['uniqueFindings'], 3)

    def test_explicit_contract_keeps_its_own_scenario_and_step(self):
        obs = observation(resourceType='fetch', statusCode=500, category='HTTP_5XX',
                          scenarioId='raw-event-scenario', stepId='raw-event-step')
        item = observation_check(obs)
        item.update(check_id='contract.response-status', scenario_id='explicit-search', step_id='explicit-submit',
                    category='API', expected={'status': 200})
        result = enrich_report(report([row([item])]))
        finding = result['findings'][0]
        self.assertEqual((finding['scenarioId'], finding['stepId']), ('explicit-search', 'explicit-submit'))
        self.assertEqual(finding['checkId'], 'contract.response-status')

    def test_data_difference_is_not_confirmed_bug_and_skip_is_not_raw_observation(self):
        checks = [{'check_id': 'data', 'status': 'DIFF', 'reason_code': 'CONTENT_DIFF'},
                  {'check_id': 'scope', 'status': 'SKIP', 'reason_code': 'CONDITION_OUT_OF_SCOPE'}]
        result = enrich_report(report([row(checks)]))
        finding = result['findings'][0]
        self.assertEqual((finding['category'], finding['status'], finding['severity']), ('DATA', 'DIFF', 'LOW'))
        self.assertNotIn('bugConfirmed', finding)
        self.assertEqual(result['totals']['rawObservations'], 0)

    def test_active_issue_links_unique_and_old_cleared_link_not_counted(self):
        rows = [row([], identifier=f'row-{index}') for index in range(3)]
        rows[0]['review']['issueRef'] = 'https://tracker.invalid/1'
        rows[1]['review']['issueRef'] = 'https://tracker.invalid/1'
        rows[2]['review']['events'] = [{'issueRef': 'https://tracker.invalid/cleared'}]
        self.assertEqual(enrich_report(report(rows))['totals']['linkedIssues'], 1)

    def test_policy_affected_js_and_console_preserve_review_and_source_evidence(self):
        for reason in ('JS_ERROR_AFTER_POLICY_BLOCK', 'CONSOLE_ERROR_AFTER_POLICY_BLOCK'):
            with self.subTest(reason=reason):
                obs = observation(category=reason, resourceType=None, statusCode=None, method=None,
                    source='BROWSER', message='ReferenceError: sampleLibrary is not defined',
                    policyInterference=True, causeConfirmed=False,
                    relatedBlockedRequests=[{'url': 'https://static.invalid/library.js?token=private',
                                             'reason': 'HOST_NOT_APPROVED', 'resourceType': 'script', 'method': 'GET'}])
                original = report([row([observation_check(obs)], issues=[obs])])
                original['results'][0]['status'] = 'REVIEW'
                before = copy.deepcopy(original)
                result = enrich_report(original)
                finding = result['findings'][0]
                self.assertEqual((finding['category'], finding['subtype'], finding['status']),
                                 ('TEST_INFRA', 'POLICY_INTERFERENCE', 'REVIEW'))
                self.assertTrue(finding['policyInterference'])
                self.assertEqual(finding['policyRelation'], 'laterAfterPolicyBlock')
                self.assertFalse(finding['causeConfirmed'])
                self.assertIn(reason, finding['tags'])
                self.assertIn('JAVASCRIPT', finding['tags'])
                evidence = finding['observations'][0]
                self.assertEqual(evidence['message'], obs['message'])
                self.assertEqual(evidence['source'], 'BROWSER')
                self.assertEqual(evidence['category'], reason)
                blocked = evidence['relatedBlockedRequests'][0]
                self.assertEqual((blocked['method'], blocked['resourceType']), ('GET', 'script'))
                self.assertNotIn('private', blocked['url'])
                self.assertEqual(original, before)
                self.assertEqual(result['results'][0]['checks'], before['results'][0]['checks'])
                self.assertEqual(result['results'][0]['review'], before['results'][0]['review'])

    def test_client_block_console_does_not_claim_policy_causality_or_hide_regular_js(self):
        blocked = observation(category='CONSOLE_ERROR', resourceType=None, statusCode=None,
                              message='Failed to load resource: net::ERR_BLOCKED_BY_CLIENT')
        normal = observation('o2', 'r2', category='JS_ERROR', level='FAIL', resourceType=None,
                             statusCode=None, message='TypeError: Cannot read properties of undefined')
        result = enrich_report(report([row([observation_check(blocked), observation_check(normal, 1)])]))
        by_reason = {finding['reasonCode']: finding for finding in result['findings']}
        finding = by_reason['CONSOLE_ERROR']
        self.assertEqual((finding['category'], finding['subtype'], finding['status']),
                         ('TEST_INFRA', 'CLIENT_BLOCK_OBSERVED', 'REVIEW'))
        self.assertEqual(finding['policyRelation'], 'blockedByClientObserved')
        self.assertNotIn('policyInterference', finding)
        self.assertNotIn('causeConfirmed', finding)
        self.assertEqual((by_reason['JS_ERROR']['category'], by_reason['JS_ERROR']['status']),
                         ('JAVASCRIPT', 'FAIL'))

    def test_policy_js_distinct_messages_do_not_merge_into_one_infra_finding(self):
        observations = [observation(str(index), str(index), category='JS_ERROR_AFTER_POLICY_BLOCK',
                                   resourceType=None, statusCode=None, message=message)
                        for index, message in enumerate(('ReferenceError: library is not defined',
                                                        'TypeError: missing method'))]
        result = enrich_report(report([row([observation_check(obs, index)
                                             for index, obs in enumerate(observations)])]))
        self.assertEqual(result['totals']['uniqueFindings'], 2)
        self.assertEqual({finding['category'] for finding in result['findings']}, {'TEST_INFRA'})

    def test_aborted_request_stays_review_and_runner_cancel_is_raw_only(self):
        aborted = observation(category='REQUEST_ABORTED', resourceType='fetch', statusCode=None,
                              message='net::ERR_ABORTED')
        cancelled = observation('o2', 'r2', category='REQUEST_CANCELLED_BY_RUNNER', level='SKIP',
                                resourceType='image', statusCode=None, message='net::ERR_ABORTED')
        result = enrich_report(report([row([observation_check(aborted), observation_check(cancelled, 1)],
                                           issues=[aborted, cancelled])]))
        self.assertEqual((result['totals']['rawObservations'], result['totals']['uniqueFindings']), (2, 1))
        finding = result['findings'][0]
        self.assertEqual((finding['category'], finding['subtype'], finding['status']),
                         ('NETWORK', 'REQUEST_ABORTED', 'REVIEW'))
        evidence = finding['observations'][0]
        self.assertEqual((evidence['method'], evidence['resourceType'], evidence['message']),
                         ('GET', 'fetch', 'net::ERR_ABORTED'))
        self.assertEqual(result['results'][0]['checks'][1]['status'], 'SKIP')
        self.assertEqual(result['results'][0]['baseline']['issues'][1], cancelled)


if __name__ == '__main__':
    unittest.main()
