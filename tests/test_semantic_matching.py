"""Deterministic mapping evidence tests; no browser, credentials or live network."""
import unittest

from qa.matching import match_pages, page_key


class SemanticMatchingTests(unittest.TestCase):
    def page(self, url, *, trail=None, heading='', fields=None, actions=None, nav=None, values=None):
        fields = fields if fields is not None else [{'type': 'search', 'name': 'keyword', 'label': '자료 검색'}]
        return dict(url=url, heading=heading, structure='nav|main|form',
                    navigationTrail=trail if trail is not None else ['start-page', '교과자료 검색'],
                    pageSignature=dict(landmarks={'main': 1, 'nav': 1, 'form': 1},
                                       headings=[{'tag': 'h1', 'text': heading}] if heading else [],
                                       formFields=[dict(field, value=values) for field in fields],
                                       actionLabels=actions if actions is not None else ['검색'],
                                       navLabels=nav if nav is not None else ['홈', '교과자료', '고객지원']))

    def paired(self, rows):
        return [row for row in rows if row['baseline'] is not None and row['candidate'] is not None]

    def test_mobile_without_h1_uses_menu_trail_and_form_evidence_as_review(self):
        a = self.page('https://me-dev.test/#/material/find')
        b = self.page('https://dev2-me.test/catalog/search.do')
        rows = match_pages([a], [b])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['match']['method'], 'SEMANTIC_CANDIDATE')
        self.assertFalse(rows[0]['match']['approved'])
        self.assertEqual(rows[0]['match']['confidence'], 'LOW')
        self.assertEqual(rows[0]['match']['baselineKey'], '/#/material/find')
        self.assertIn('NAVIGATION_TRAIL', {item['kind'] for item in rows[0]['match']['evidence']})
        self.assertIn('FORM_FIELDS', {item['kind'] for item in rows[0]['match']['evidence']})

    def test_title_and_shared_template_do_not_override_different_functions(self):
        a = self.page('https://a.test/one', heading='자료실', trail=['start-page', '교과서'],
                      fields=[{'type': 'search', 'name': 'textbook', 'label': '교과서'}])
        b = self.page('https://b.test/two', heading='자료실', trail=['start-page', '공지사항'],
                      fields=[{'type': 'search', 'name': 'notice', 'label': '공지사항'}])
        rows = match_pages([a], [b])
        self.assertEqual(len(rows), 2)
        self.assertEqual(self.paired(rows), [])
        for row in rows:
            self.assertEqual(row['match']['method'], 'AMBIGUOUS')
            self.assertEqual(len(row['match']['candidates']), 1)
            self.assertFalse(row['match']['candidates'][0]['eligible'])
            self.assertIn('NAVIGATION_CONFLICT', {e['kind'] for e in row['match']['candidates'][0]['evidence']})

    def test_global_navigation_and_landmarks_alone_are_not_function_identity(self):
        a = self.page('https://a.test/one', trail=[], fields=[], actions=[])
        b = self.page('https://b.test/two', trail=[], fields=[], actions=[])
        rows = match_pages([a], [b])
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row['match']['method'] == 'UNMATCHED' for row in rows))

    def test_different_primary_function_headings_do_not_pair_on_generic_search_form(self):
        a = self.page('https://a.test/one', heading='교과서 검색', trail=['start-page', '검색'])
        b = self.page('https://b.test/two', heading='공지사항 검색', trail=['start-page', '검색'])
        rows = match_pages([a], [b])
        self.assertEqual(self.paired(rows), [])
        self.assertEqual(rows[0]['match']['candidates'][0]['reason'], 'FUNCTION_HEADING_CONFLICT')

    def test_unknown_paths_in_trail_are_not_menu_evidence(self):
        a = self.page('https://a.test/one', trail=['start-page', '/shared'])
        b = self.page('https://b.test/two', trail=['start-page', '/shared'])
        rows = match_pages([a], [b])
        self.assertEqual(self.paired(rows), [])

    def test_global_duplicate_candidates_are_not_greedily_paired(self):
        a = [self.page('https://a.test/search-one'), self.page('https://a.test/search-two')]
        b = [self.page('https://b.test/find-one'), self.page('https://b.test/find-two')]
        rows = match_pages(a, b)
        self.assertEqual(len(rows), 4)
        self.assertEqual(self.paired(rows), [])
        self.assertTrue(all(len(row['match']['candidates']) == 2 for row in rows))
        reverse = match_pages(list(reversed(a)), list(reversed(b)))
        self.assertEqual(self.paired(reverse), [])

    def test_duplicate_baseline_cannot_take_the_only_candidate_first(self):
        rows = match_pages([self.page('https://a.test/one'), self.page('https://a.test/two')],
                           [self.page('https://b.test/find')])
        self.assertEqual(len(rows), 3)
        self.assertEqual(self.paired(rows), [])

    def test_semantic_candidate_does_not_steal_later_exact_route(self):
        a = [self.page('https://a.test/early'), self.page('https://a.test/exact', heading='자료 검색')]
        b = [self.page('https://b.test/exact', heading='자료 검색')]
        rows = match_pages(a, b)
        self.assertEqual(len(self.paired(rows)), 1)
        self.assertEqual(self.paired(rows)[0]['baseline']['url'], a[1]['url'])
        self.assertEqual(self.paired(rows)[0]['match']['method'], 'EXACT_ROUTE')
        unpaired = next(row for row in rows if row['baseline'] is a[0])
        self.assertFalse(unpaired['match']['candidates'][0]['available'])

    def test_semantic_candidate_does_not_steal_later_explicit_alias(self):
        a = [self.page('https://a.test/early'), self.page('https://a.test/manual')]
        b = [self.page('https://b.test/new')]
        rows = match_pages(a, b, [{'baseline': '/manual', 'candidate': '/new', 'page_class': 'manual-search'}])
        pair = self.paired(rows)[0]
        self.assertEqual(pair['baseline']['url'], a[1]['url'])
        self.assertEqual(pair['match']['method'], 'EXPLICIT_ALIAS')
        self.assertEqual(pair['key'], 'manual-search')
        self.assertTrue(pair['match']['approved'])

    def test_alias_overrides_semantic_conflict_because_it_is_explicit(self):
        a = self.page('https://a.test/one', trail=['A'], fields=[])
        b = self.page('https://b.test/two', trail=['B'], fields=[])
        rows = match_pages([a], [b], [{'baseline': '/one', 'candidate': '/two', 'page_class': 'chosen'}],
                           start_pair={'baseline': a['url'], 'candidate': b['url']})
        self.assertEqual(rows[0]['match']['method'], 'EXPLICIT_ALIAS')
        self.assertTrue(rows[0]['match']['approved'])

    def test_default_alias_class_remains_unique_per_rule(self):
        a = [self.page('https://a.test/one'), self.page('https://a.test/two')]
        b = [self.page('https://b.test/new-one'), self.page('https://b.test/new-two')]
        rows = match_pages(a, b, [{'baseline': '/one', 'candidate': '/new-one'},
                                 {'baseline': '/two', 'candidate': '/new-two'}])
        self.assertEqual([row['key'] for row in rows], ['alias-0', 'alias-1'])

    def test_conflicting_aliases_leave_all_targets_unpaired(self):
        a = [self.page('https://a.test/one')]
        b = [self.page('https://b.test/two'), self.page('https://b.test/three')]
        aliases = [{'baseline': '/one', 'candidate': '/two'}, {'baseline': '/one', 'candidate': '/three'}]
        rows = match_pages(a, b, aliases)
        self.assertEqual(self.paired(rows), [])
        self.assertEqual(len(rows[0]['match']['candidates']), 2)
        self.assertEqual(rows[0]['match']['method'], 'AMBIGUOUS_ALIAS')

    def test_repeated_identical_alias_is_not_a_false_collision(self):
        rule = {'baseline': '/one', 'candidate': '/two', 'page_class': 'same'}
        rows = match_pages([self.page('https://a.test/one')], [self.page('https://b.test/two')], [rule, rule])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['match']['method'], 'EXPLICIT_ALIAS')
        self.assertTrue(rows[0]['match']['approved'])

    def test_different_detail_ids_keep_candidate_evidence_without_merging(self):
        samples = [('https://a.test/detail?id=10', 'https://b.test/view?contentId=20'),
                   ('https://a.test/#/detail?seq=10', 'https://b.test/view?seq=20'),
                   ('https://a.test/detail/10', 'https://b.test/view/20')]
        for left, right in samples:
            with self.subTest(left=left):
                rows = match_pages([self.page(left)], [self.page(right)])
                self.assertEqual(self.paired(rows), [])
                self.assertIn('DIFFERENT_INSTANCE_ID', [c['reason'] for c in rows[0]['match']['candidates']])
                self.assertEqual(rows[0]['match']['baselineKey'], page_key(left))

    def test_hash_query_order_and_alias_suggestion_preserve_exact_identity(self):
        a = self.page('https://a.test/#/search?tag=b&tag=a')
        b = self.page('https://b.test/find?tag=b&tag=a')
        rows = match_pages([a], [b])
        suggestion = rows[0]['match']['candidates'][0]['alias']
        self.assertEqual(suggestion['baseline'], '/#/search?tag=b&tag=a')
        self.assertEqual(suggestion['candidate'], '/find?tag=b&tag=a')
        self.assertTrue(suggestion['page_class'].startswith('mapped-'))

    def test_input_values_do_not_affect_match_or_leak_into_evidence(self):
        a = self.page('https://a.test/one', values='private-baseline-input')
        b = self.page('https://b.test/two', values='private-candidate-input')
        rows = match_pages([a], [b])
        self.assertEqual(len(rows), 1)
        self.assertNotIn('private-', str(rows[0]['match']))

    def test_secret_url_redacts_public_candidates_and_disables_alias_suggestion(self):
        a = self.page('https://a.test/search?token=fixture-secret')
        b = self.page('https://b.test/find?token=fixture-secret')
        rows = match_pages([a], [b])
        self.assertNotIn('fixture-secret', str(rows[0]['match']))
        self.assertIsNone(rows[0]['match']['candidates'][0]['alias'])

    def test_selected_start_pages_do_not_approve_descendant_hash_routes(self):
        a = [self.page('https://a.test/#/', trail=[]), self.page('https://a.test/#/search')]
        b = [self.page('https://b.test/', trail=[]), self.page('https://b.test/find')]
        rows = match_pages(a, b, start_pair={'baseline': a[0]['url'], 'candidate': b[0]['url']})
        self.assertEqual(sum(row['match']['approved'] for row in rows), 1)
        pair = next(row for row in rows if row['baseline'] is a[1])
        self.assertEqual(pair['match']['method'], 'SEMANTIC_CANDIDATE')
        self.assertFalse(pair['match']['approved'])


if __name__ == '__main__':
    unittest.main()
