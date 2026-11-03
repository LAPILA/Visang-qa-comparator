import copy
import csv
import io
import unittest

from app import csv_inventory
from qa.inventory import build_inventory
from qa.matching import match_pages, page_key


class InventoryTests(unittest.TestCase):
    def test_environment_catalogue_separates_product_aliases_and_coverage(self):
        options = {'profile_id': 'elementary-mobile', 'baseline_name': 'DEV1', 'candidate_name': 'STG',
                   'baseline_url': 'https://a.test/#/', 'candidate_url': 'https://b.test/',
                   'crawl_scope': 'same_origin_readonly'}
        a = {'url': options['baseline_url'], 'finalUrl': 'https://a.test/#/home', 'title': 'Home',
             'navigated': True, 'statusCode': 200, 'captureReady': True,
             'navigationTrail': ['start-page'], 'pageSignature': {'landmarks': {'main': 1}},
             'actions': [{'allowed': True}, {'allowed': False}], 'checks': []}
        deferred = {'url': 'https://a.test/#/notice', 'checks': [{'status': 'BLOCKED', 'reason_code': 'PAGE_LIMIT_REACHED'}]}
        pair = {'key': 'start-page', 'baseline': a, 'candidate': None,
                'match': {'method': 'UNMATCHED', 'approved': False, 'reason': 'NOT_DISCOVERED',
                          'candidates': [{'url': 'https://b.test/notices', 'key': '/notices', 'available': True}]}}
        original = copy.deepcopy(a)
        catalogue = build_inventory(options, {'a': a}, {}, [deferred], [], [pair])
        self.assertEqual(catalogue['productId'], 'elementary-mobile')
        self.assertEqual([env['name'] for env in catalogue['environments']], ['DEV1', 'STG'])
        env = catalogue['environments'][0]
        self.assertEqual((env['discoveredCount'], env['visitedCount'], env['deferredCount']), (2, 1, 1))
        self.assertEqual(env['pages'][0]['pageKey'], '/#/')
        self.assertEqual(env['pages'][0]['blockedActionCount'], 1)
        self.assertEqual(catalogue['matches'][0]['baselineKey'], '/#/')
        self.assertTrue(catalogue['requiresReview'])
        self.assertEqual(a, original)

    def test_catalogue_never_exports_token_values_or_internal_fields(self):
        options = {'baseline_url': 'https://a.test/?token=fixture-secret', 'candidate_url': None}
        page = {'url': options['baseline_url'], 'finalUrl': options['baseline_url'], 'navigated': True,
                'pageSignature': {'_private': 'hidden', 'navLabels': ['token=fixture-secret']}}
        catalogue = build_inventory(options, {'a': page}, {}, [], [], [])
        self.assertNotIn('fixture-secret', str(catalogue))
        self.assertNotIn('_private', str(catalogue))
        self.assertEqual(len(catalogue['environments']), 1)

    def test_redacted_paired_keys_cannot_be_used_as_an_alias(self):
        a = {'url': 'https://a.test/search?token=fixture-secret', 'heading': 'Search', 'structure': 'main'}
        b = {'url': 'https://b.test/find?token=fixture-secret', 'heading': 'Search', 'structure': 'main'}
        inventory = build_inventory({'baseline_url': a['url'], 'candidate_url': b['url']},
                                    {'a': a}, {'b': b}, [], [], match_pages([a], [b]))
        self.assertFalse(inventory['matches'][0]['aliasSafe'])
        self.assertNotIn('fixture-secret', str(inventory))

    def test_inventory_csv_preserves_zero_and_escapes_formula_cells(self):
        job = {'id': 'synthetic', 'report': {'inventory': {'productId': 'custom', 'environments': [
            {'id': 'a', 'name': '=1+1', 'pages': [{'pageKey': '/home', 'url': 'https://a.test/home',
             'navigationTrail': ['Home', 'Notice'], 'visited': True, 'statusCode': 200,
             'actionCount': 0, 'blockedActionCount': 0}]}]}}}
        rows = list(csv.reader(io.StringIO(csv_inventory(job).decode('utf-8-sig'))))
        self.assertEqual(rows[1][3], "'=1+1")
        self.assertEqual(rows[1][8], 'Home > Notice')
        self.assertEqual(rows[1][11:13], ['0', '0'])

    def test_alias_roundtrip_preserves_percent_encoding_query_order_and_hash(self):
        a = {'url': 'https://a.test/search?q=hello%20world&tag=b&tag=a#/tab?filter=REDACTED%20label',
             'heading': 'Search', 'structure': 'nav|main|form', 'navigated': True}
        b = dict(a, url='https://b.test/find?q=hello%20world&tag=b&tag=a#/tab?filter=REDACTED%20label')
        pairs = match_pages([a], [b])
        options = {'baseline_url': a['url'], 'candidate_url': b['url']}
        inventory = build_inventory(options, {'a': a}, {'b': b}, [], [], pairs)
        self.assertEqual(inventory['environments'][0]['pages'][0]['pageKey'], page_key(a['url']))
        match = inventory['matches'][0]
        self.assertEqual(match['baselineKey'], page_key(a['url']))
        alias = match['candidates'][0]['alias']
        self.assertEqual(alias['baseline'], page_key(a['url']))
        self.assertEqual(alias['candidate'], page_key(b['url']))
        mapped = match_pages([a], [b], [alias])
        self.assertEqual(mapped[0]['match']['method'], 'EXPLICIT_ALIAS')
        self.assertTrue(mapped[0]['match']['approved'])


if __name__ == '__main__':
    unittest.main()
