import math
import unittest
import uuid

from qa.config import parse_options, profiles, public_options, validate_url
from qa.policy import classify_candidate, readonly_navigation_reason, resource_allowed, route_allowed


class ConfigValidationTests(unittest.TestCase):
    origin = "http://127.0.0.1:39001"

    def custom(self, **changes):
        return {"profileId": "custom", "baselineUrl": "https://baseline.invalid/start",
                "candidateUrl": "https://candidate.invalid/start", **changes}

    def test_demo_roundtrip_retains_routes_scenarios_and_budget(self):
        demo = next(item for item in profiles(self.origin) if item["id"] == "synthetic-demo")
        options = parse_options({"profileId": "synthetic-demo", **demo["defaults"]}, self.origin)
        self.assertEqual(options["baseline_url"], self.origin + "/demo/a/")
        self.assertEqual(options["candidate_url"], self.origin + "/demo/b/")
        self.assertEqual(len(options["scenario_ids"]), 3)
        self.assertEqual(len(options["route_aliases"]), 5)
        self.assertFalse(any("unsafe" in path for path in options["allowed_paths"]))
        self.assertEqual(options["max_actions"], 80)

    def test_demo_addresses_cannot_be_replaced(self):
        for key in ("baselineUrl", "candidateUrl"):
            with self.subTest(key=key), self.assertRaises(ValueError):
                parse_options({"profileId": "synthetic-demo", key: "https://other.invalid/"}, self.origin)

    def test_unknown_profile_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_options({"profileId": "does-not-exist"}, self.origin)

    def test_secondary_mobile_uses_user_registered_staging_url(self):
        profile = next(item for item in profiles(self.origin) if item['id'] == 'secondary-mobile')
        self.assertFalse(profile['disabled'])
        self.assertEqual(profile['candidateUrl'], 'https://stg-mv.vivasam.com/')
        self.assertEqual(profile['baselineUrl'], 'https://mv.vivasam.com/')
        self.assertEqual(profile['label'], '중고등 모바일')

    def test_secondary_mobile_custom_still_requires_candidate_url(self):
        for payload in ({'profileId': 'secondary-mobile', 'candidateEnvironmentId': 'custom'},
                        {'profileId': 'secondary-mobile', 'candidateEnvironmentId': 'custom', 'candidateUrl': ''}):
            with self.subTest(payload=payload), self.assertRaisesRegex(ValueError, 'URL'):
                parse_options(payload, self.origin)

    def test_secondary_mobile_custom_environments_preserve_product_and_mobile_viewport(self):
        payload = {'profileId': 'secondary-mobile', 'baselineUrl': 'https://stage.example.invalid/#/home',
                   'candidateUrl': 'https://dev2.example.invalid/', 'baselineName': 'STG', 'candidateName': 'DEV2'}
        options = parse_options(payload, self.origin)
        self.assertEqual(options['profile_id'], 'secondary-mobile')
        self.assertEqual(options['viewport'], {'width': 390, 'height': 844})
        self.assertEqual((options['baseline_url'], options['candidate_url']),
                         (payload['baselineUrl'], payload['candidateUrl']))

    def test_secondary_mobile_single_uses_known_production_a_only(self):
        options = parse_options({'profileId': 'secondary-mobile', 'testType': 'single'}, self.origin)
        self.assertEqual(options['baseline_url'], 'https://mv.vivasam.com/')
        self.assertIsNone(options['candidate_url'])
        self.assertIsNone(options['candidate_name'])
        self.assertEqual(options['allowed_hosts'], ['mv.vivasam.com'])
        self.assertEqual(options['viewport'], {'width': 390, 'height': 844})

    def test_numeric_limits_reject_nonfinite_boolean_fraction_and_range(self):
        for value in (math.nan, math.inf, -math.inf, "NaN", "1e309", True, 1.5, 0, 201, None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_options(self.custom(maxPages=value), self.origin)
        for key, value in (("maxActions", 1001), ("timeoutSeconds", 14), ("timeoutSeconds", 3601), ("maxDepth", 9),
                           ("actionInterval", 0), ("visualThreshold", float("nan"))):
            with self.subTest(key=key), self.assertRaises(ValueError):
                parse_options(self.custom(**{key: value}), self.origin)

    def test_numeric_boundaries_and_mobile_viewport(self):
        options = parse_options(self.custom(maxPages=30, maxDepth=0, maxActions=0,
                                            timeoutSeconds=15, visualThreshold=100), self.origin)
        self.assertEqual((options["max_pages"], options["max_depth"], options["max_actions"]), (30, 0, 0))
        mobile = parse_options({"profileId": "elementary-mobile"}, self.origin)
        self.assertEqual(mobile["viewport"], {"width": 390, "height": 844})

    def test_credentials_and_unsafe_url_forms_are_rejected(self):
        for value in ("file:///tmp/test", "javascript:alert(1)", "https://user:secret@example.invalid/",
                      "https://example.invalid:99999/", "https://example.invalid/a\nb", "//example.invalid/"):
            with self.subTest(url=value), self.assertRaises(ValueError):
                validate_url(value)
        for key in ("password", "PW", "cookie", "token", "storage_state"):
            with self.subTest(key=key), self.assertRaises(ValueError):
                parse_options(self.custom(**{key: "synthetic-secret"}), self.origin)

    def test_malformed_and_ambiguous_mapping_region_inputs_fail(self):
        bad_inputs = [
            {"aliases": "{invalid"}, {"aliases": {}},
            {"aliases": [{"baseline": "//outside.invalid", "candidate": "/new", "page_class": "home"}]},
            {"aliases": [{"baseline": "/a", "candidate": "/b", "page_class": "same"},
                         {"baseline": "/c", "candidate": "/d", "page_class": "same"}]},
            {"regions": [{"id": "x", "selector": "#x"}, {"id": "x", "selector": "#y"}]},
            {"regions": [{"id": "x", "selector": "#x", "mask_selectors": [None]}]},
            {"safeActions": [{"id": "x", "selector": "#x", "kind": "evaluate"}]},
            {"scenarioIds": [None]},
        ]
        for change in bad_inputs:
            with self.subTest(change=change), self.assertRaises(ValueError):
                parse_options(self.custom(**change), self.origin)

    def test_host_and_path_allowlists_are_exact_and_bounded(self):
        for change in ({"allowedHosts": ["*.example.invalid"]}, {"allowedHosts": ["example.invalid/path"]},
                       {"allowedHosts": ["example.invalid:bad"]}, {"allowedPaths": ["/*"]},
                       {"allowedPaths": ["//outside.invalid/path"]}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                parse_options(self.custom(**change), self.origin)
        options = parse_options(self.custom(allowedHosts="cdn.invalid\ncdn.invalid", allowedPaths="/search\n/notice/*"), self.origin)
        self.assertEqual(options["allowed_hosts"], ["baseline.invalid", "candidate.invalid", "cdn.invalid"])
        self.assertEqual(options["allowed_paths"], ["/search", "/notice/*"])

    def test_single_target_does_not_require_or_approve_a_second_environment(self):
        for purpose in ('single', 'regression', 'conditional'):
            change = {'testType': purpose, 'candidateUrl': 'https://unapproved.invalid/'}
            if purpose == 'regression':
                change['previousRunId'] = str(uuid.uuid4())
            if purpose == 'conditional':
                change['conditions'] = [{'id': 'empty', 'selector': '#empty', 'kind': 'visible', 'expected': True}]
            options = parse_options(self.custom(**change), self.origin)
            self.assertIsNone(options['candidate_url'])
            self.assertNotIn('unapproved.invalid', options['allowed_hosts'])
            self.assertEqual(options['test_type'], purpose)
        options = parse_options({'testType': 'single', 'profileId': 'custom',
                                 'baselineUrl': 'https://only.invalid/'}, self.origin)
        self.assertIsNone(options['candidate_url'])

    def test_purpose_prerequisites_and_regression_ids_are_validated(self):
        for changes in ({'testType': 'unknown'}, {'testType': 'conditional'},
                        {'testType': 'regression'}, {'testType': 'regression', 'previousRunId': '../report'},
                        {'testType': 'conditional', 'conditions': [{'id': 'x', 'kind': 'evaluate', 'selector': 'body'}]}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                parse_options(self.custom(**changes), self.origin)

    def test_configuration_parsing_does_not_mutate_callers_contracts(self):
        region = {'id': 'main', 'selector': 'main'}
        payload = self.custom(regions=[region], testType='single')
        options = parse_options(payload, self.origin)
        self.assertNotIn('required', region)
        options['regions'][0]['selector'] = '#other'
        self.assertEqual(region['selector'], 'main')

    def test_private_evidence_mask_selectors_roundtrip_and_reject_invalid_arrays(self):
        options = parse_options(self.custom(privateMaskSelectors=['.account-name', '#private-id']), self.origin)
        self.assertEqual(options['private_mask_selectors'], ['.account-name', '#private-id'])
        self.assertEqual(public_options(options)['privateMaskSelectors'], ['.account-name', '#private-id'])
        for value in ([None], [True], [''], ['#a'] * 31, {'selector': '#private'}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_options(self.custom(privateMaskSelectors=value), self.origin)

    def test_start_pair_defaults_and_roundtrip_are_comparison_only(self):
        options = parse_options(self.custom(), self.origin)
        self.assertTrue(options['pair_start_pages'])
        self.assertTrue(public_options(options)['pairStartPages'])
        self.assertFalse(parse_options(self.custom(pairStartPages=False), self.origin)['pair_start_pages'])
        self.assertFalse(parse_options(self.custom(pairStartPages='false'), self.origin)['pair_start_pages'])
        for purpose in ('single', 'regression', 'conditional'):
            payload = self.custom(testType=purpose, pairStartPages=True)
            if purpose == 'regression':
                payload['previousRunId'] = str(uuid.uuid4())
            if purpose == 'conditional':
                payload['conditions'] = [{'id': 'x', 'selector': '#x', 'kind': 'visible', 'expected': True}]
            self.assertFalse(parse_options(payload, self.origin)['pair_start_pages'])
        for value in ('yes-please', [], {}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_options(self.custom(pairStartPages=value), self.origin)

    def test_resource_hosts_are_validated_but_never_added_to_navigation_hosts(self):
        options = parse_options(self.custom(resourceHosts='cdn.invalid\ncdn.invalid\nmedia.invalid:8443'), self.origin)
        self.assertEqual(options['resource_hosts'], ['cdn.invalid', 'media.invalid:8443'])
        self.assertEqual(public_options(options)['resourceHosts'], options['resource_hosts'])
        self.assertEqual(options['allowed_hosts'], ['baseline.invalid', 'candidate.invalid'])
        for value in (['*.cdn.invalid'], ['https://cdn.invalid'], ['cdn.invalid/path'],
                      ['cdn.invalid?x=1'], ['user:password@cdn.invalid'], ['cdn.invalid:99999'],
                      ['cdn.invalid:bad'], ['cdn.invalid another.invalid'], [None]):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_options(self.custom(resourceHosts=value), self.origin)

    def test_static_resource_grants_do_not_allow_navigation_api_or_writes(self):
        url = 'https://code.jquery.com/jquery.js'
        hosts = ['code.jquery.com']
        for kind in ('script', 'stylesheet', 'image', 'font', 'media'):
            self.assertTrue(resource_allowed(url, kind, 'GET', False, hosts))
            self.assertTrue(resource_allowed(url, kind, 'HEAD', False, hosts))
        for kind in ('document', 'xhr', 'fetch', 'websocket', 'other'):
            self.assertFalse(resource_allowed(url, kind, 'GET', False, hosts))
        self.assertFalse(resource_allowed(url, 'script', 'GET', True, hosts))
        for method in ('POST', 'PUT', 'DELETE', 'OPTIONS'):
            self.assertFalse(resource_allowed(url, 'script', method, False, hosts))
        for other in ('https://child.code.jquery.com/jquery.js', 'https://code.jquery.com.evil.invalid/jquery.js',
                      'https://other.invalid/jquery.js', 'https://user:secret@code.jquery.com/jquery.js',
                      'file:///jquery.js', 'https://code.jquery.com:8443/jquery.js', 'https://code.jquery.com:0/jquery.js'):
            self.assertFalse(resource_allowed(other, 'script', 'GET', False, hosts))
        self.assertTrue(resource_allowed('https://code.jquery.com:443/jquery.js', 'script', 'GET', False, hosts))
        self.assertTrue(resource_allowed('https://cdn.invalid:8443/a.js', 'script', 'GET', False, ['cdn.invalid:8443']))
        self.assertFalse(resource_allowed('https://cdn.invalid/a.js', 'script', 'GET', False, ['cdn.invalid:8443']))

    def test_profile_resource_defaults_are_narrow_and_can_be_disabled(self):
        from qa.config import _SHARED_ASSET_HOSTS
        available = {item['id']: item for item in profiles(self.origin)}
        mobile = available['elementary-mobile']['defaults']['resourceHosts']
        # Observed static asset/SDK hosts only (2026-11-04 real runs); trackers stay out.
        self.assertEqual(set(mobile), set(_SHARED_ASSET_HOSTS))
        for tracker in ('www.googletagmanager.com', 'cdn-aitg.widerplanet.com', 'dj.vsaidt.com', 'cdn.channel.io'):
            self.assertNotIn(tracker, _SHARED_ASSET_HOSTS)
        for profile in ('custom', 'synthetic-demo'):
            self.assertEqual(available[profile]['defaults']['resourceHosts'], [])
        for profile in ('elementary-pc', 'secondary-pc', 'secondary-mobile'):
            self.assertEqual(set(available[profile]['defaults']['resourceHosts']), set(_SHARED_ASSET_HOSTS))
        options = parse_options({'profileId': 'elementary-mobile'}, self.origin)
        self.assertNotIn('code.jquery.com', options['allowed_hosts'])
        self.assertEqual(parse_options({'profileId': 'elementary-mobile', 'resourceHosts': []}, self.origin)['resource_hosts'], [])
        # A caller changing a bootstrap payload cannot mutate future profile defaults.
        mobile.append('not-approved.invalid')
        self.assertNotIn('not-approved.invalid', profiles(self.origin)[3]['defaults']['resourceHosts'])

    def test_environment_names_and_crawl_scope_are_explicit_and_roundtrip(self):
        default = parse_options(self.custom(), self.origin)
        self.assertEqual((default['baseline_name'], default['candidate_name'], default['crawl_scope']),
                         ('A', 'B', 'approved_paths'))
        payload = self.custom(baselineName='운영', candidateName='DEV2',
                              crawlScope='same_origin_readonly', mode='discovery')
        options = parse_options(payload, self.origin)
        self.assertEqual((options['baseline_name'], options['candidate_name'], options['crawl_scope']),
                         ('운영', 'DEV2', 'same_origin_readonly'))
        public = public_options(options)
        self.assertEqual((public['baselineName'], public['candidateName'], public['crawlScope']),
                         ('운영', 'DEV2', 'same_origin_readonly'))
        self.assertEqual((options['baseline_url'], options['candidate_url']),
                         (payload['baselineUrl'], payload['candidateUrl']))
        for profile in profiles(self.origin):
            self.assertEqual(profile['defaults']['crawlScope'], 'approved_paths')

    def test_environment_names_scope_and_single_candidate_are_bounded(self):
        for key in ('baselineName', 'candidateName'):
            for value in ('', '  ', None, 123, 'x' * 51, 'bad\nname'):
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    parse_options(self.custom(**{key: value}), self.origin)
        for value in ('anywhere', '', None, True, [], {}):
            with self.subTest(scope=value), self.assertRaises(ValueError):
                parse_options(self.custom(crawlScope=value), self.origin)
        single = parse_options(self.custom(testType='single', candidateUrl='', candidateName=''), self.origin)
        self.assertIsNone(single['candidate_url'])
        self.assertIsNone(single['candidate_name'])

    def test_same_origin_expands_pages_and_hash_routes_without_rewriting_queries(self):
        options = parse_options(self.custom(crawlScope='same_origin_readonly'), self.origin)
        seeds = (options['baseline_url'], options['candidate_url'])
        for target in ('https://baseline.invalid/new/path.do?class=3&class=1',
                       'https://baseline.invalid/#/coverPage',
                       'https://baseline.invalid/#/search?keyword=math&page=2',
                       'https://baseline.invalid:443/notice?action=view&id=1'):
            action = {'href': target, 'pageUrl': seeds[0], 'tag': 'a', 'visible': True}
            before = dict(action)
            self.assertEqual(classify_candidate(action, options, seeds), (True, 'APPROVED_NAVIGATION'))
            self.assertTrue(route_allowed(target, options, seeds, origin_url=seeds[0]))
            self.assertEqual(action, before)
        legacy = {**options, 'crawl_scope': 'approved_paths'}
        self.assertFalse(route_allowed('https://baseline.invalid/new/path.do', legacy, seeds))
        legacy['allowed_paths'] = ['/new/*']
        self.assertTrue(route_allowed('https://baseline.invalid/new/path.do', legacy, seeds))

    def test_same_origin_does_not_expand_other_environment_ports_schemes_or_static_hosts(self):
        options = parse_options(self.custom(crawlScope='same_origin_readonly',
                                            allowedHosts=['extra.invalid'], resourceHosts=['cdn.invalid'],
                                            allowedPaths=['/allowed']), self.origin)
        seeds = (options['baseline_url'], options['candidate_url'])
        for target in ('https://candidate.invalid/allowed', 'http://baseline.invalid/allowed',
                       'https://baseline.invalid:8443/allowed', 'https://child.baseline.invalid/allowed',
                       'https://extra.invalid/allowed', 'https://cdn.invalid/allowed',
                       'https://user:secret@baseline.invalid/allowed', 'javascript:alert(1)',
                       'mailto:qa@example.invalid'):
            action = {'href': target, 'pageUrl': seeds[0], 'tag': 'a'}
            with self.subTest(target=target):
                self.assertFalse(classify_candidate(action, options, seeds)[0])
                self.assertFalse(route_allowed(target, options, seeds, origin_url=seeds[0]))
        target = 'https://baseline.invalid/notice'
        self.assertFalse(route_allowed(target, options, seeds))
        self.assertFalse(route_allowed(target, options, seeds, origin_url='https://unselected.invalid/'))
        self.assertTrue(route_allowed(target, options, seeds[:1]))
        self.assertTrue(route_allowed('https://candidate.invalid/notice', options, seeds, origin_url=seeds[1]))

    def test_same_origin_readonly_excludes_sensitive_mutating_data_and_download_routes(self):
        options = parse_options(self.custom(crawlScope='same_origin_readonly'), self.origin)
        seed = options['baseline_url']
        paths = ('/logout', '/delete?id=1', '/%2564elete?id=1', '/member/info.do', '/#/myPage',
                 '/myInfo.do', '/login.do', '/sign-in', '/account/settings', '/profile', '/update.do',
                 '/notice?mode=write', '/notice?action=unknown', '/notice?edit=1', '/notice?toggle=1',
                 '/api/notices', '/apiList.do', '/graphql', '/notices.json', '/data.xml',
                 '/book.pdf', '/archive.tar.gz', '/report.csv', '/photo.png', '/files/download.do')
        for path in paths:
            url = 'https://baseline.invalid' + path
            action = {'href': url, 'pageUrl': seed, 'tag': 'a'}
            with self.subTest(path=path):
                self.assertIsNotNone(readonly_navigation_reason(action))
                self.assertFalse(classify_candidate(action, options, (seed,))[0])
                self.assertFalse(route_allowed(url, options, (seed,)))

    def test_same_origin_keeps_action_visibility_form_download_and_explicit_button_rules(self):
        options = parse_options(self.custom(crawlScope='same_origin_readonly',
            safeActions=[{'id': 'safe-tab', 'selector': '#tab', 'kind': 'click'}]), self.origin)
        seed = options['baseline_url']
        action = {'href': 'https://baseline.invalid/notice', 'pageUrl': seed, 'tag': 'a'}
        for change in ({'visible': False}, {'disabled': True}, {'download': True}, {'type': 'submit'},
                       {'formAction': 'https://baseline.invalid/notice'}, {'tag': 'button'},
                       {'method': 'POST'}, {'label': '회원정보'}, {'label': '삭제'}, {'label': 'Edit'},
                       {'label': 'Update account details'}, {'label': 'Disable'}):
            with self.subTest(change=change):
                self.assertFalse(classify_candidate({**action, **change}, options, (seed,))[0])
        self.assertEqual(classify_candidate({'selector': '#tab', 'pageUrl': seed}, options, (seed,)),
                         (True, 'APPROVED_UI_ACTION'))
        self.assertEqual(classify_candidate({'selector': '#unknown', 'pageUrl': seed}, options, (seed,)),
                         (False, 'UNKNOWN_ACTION'))

    def test_same_origin_rejects_query_control_aliases_and_encoded_nested_commands(self):
        options = parse_options(self.custom(crawlScope='same_origin_readonly'), self.origin)
        seed = options['baseline_url']
        paths = ('/tasks?op=reset', '/tasks?actionType=update', '/tasks?ACTION_TYPE=reset',
                 '/tasks?operationName=archive', '/tasks?cmd=toggle', '/tasks?dispatch=updateNotice',
                 '/tasks?%256F%2570=%2572eset', '/tasks?op=view&op=reset',
                 '/#/tasks?action-type=update',
                 '/tasks?next=%2Ftasks%3Fop%3Dreset',
                 '/tasks?redirectUrl=%252Ftasks%253FactionType%253Dupdate',
                 '/tasks?params=op%3Dreset', '/tasks?next=%2Freset',
                 '/tasks?request=params%3DactionType%253Dupdate')
        for path in paths:
            target = 'https://baseline.invalid' + path
            action = {'href': target, 'pageUrl': seed, 'tag': 'a'}
            before = dict(action)
            with self.subTest(path=path):
                self.assertFalse(classify_candidate(action, options, (seed,))[0])
                self.assertFalse(route_allowed(target, options, (seed,)))
                self.assertEqual(action, before)

    def test_same_origin_keeps_search_content_and_read_controls_unmodified(self):
        options = parse_options(self.custom(crawlScope='same_origin_readonly'), self.origin)
        seed = options['baseline_url']
        for path in ('/search?q=reset', '/search?keyword=update&keyword=reset',
                     '/search?query=op%3Dreset', '/tasks?op=view', '/tasks?actionType=list',
                     '/tasks?next=%2Fnotice%3Fop%3Dview', '/#/search?text=reset&page=2'):
            target = 'https://baseline.invalid' + path
            action = {'href': target, 'pageUrl': seed, 'tag': 'a'}
            before = dict(action)
            with self.subTest(path=path):
                self.assertTrue(classify_candidate(action, options, (seed,))[0])
                self.assertTrue(route_allowed(target, options, (seed,)))
                self.assertEqual(action, before)


if __name__ == "__main__":
    unittest.main()
