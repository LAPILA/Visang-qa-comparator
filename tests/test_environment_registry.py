"""User-supplied environment registrations; validation never contacts the sites."""
import copy
import itertools
import unittest
from urllib.parse import urlsplit

from qa.config import parse_options, profiles, public_options
from qa.environments import PRODUCT_ENVIRONMENTS


# Independent fixture from the approved 16-URL list, not generated from registry.
EXPECTED_URLS = {
    'elementary-pc': {
        'production': 'https://e.vivasam.com/main',
        'staging': 'https://stg-e.vivasam.com/',
        'vibe-dev': 'https://dev2-e.vivasam.com/main',
        'legacy-dev': 'https://e-dev.vivasam.com/',
    },
    'secondary-pc': {
        'production': 'https://v.vivasam.com/main',
        'staging': 'https://stg-v.vivasam.com/',
        'vibe-dev': 'https://dev2-v.vivasam.com/main',
        'legacy-dev': 'https://v-dev.vivasam.com/',
    },
    'elementary-mobile': {
        'production': 'https://me.vivasam.com/',
        'staging': 'https://stg-me.vivasam.com/',
        'vibe-dev': 'https://dev2-me.vivasam.com/',
        'legacy-dev': 'https://me-dev.vivasam.com/#/',
    },
    'secondary-mobile': {
        'production': 'https://mv.vivasam.com/',
        'staging': 'https://stg-mv.vivasam.com/',
        'vibe-dev': 'https://dev2-mv.vivasam.com/',
        'legacy-dev': 'https://mv-dev.vivasam.com/#/',
    },
}
EXPECTED_LABELS = {'production': '운영', 'staging': 'STG',
                   'vibe-dev': '바이브 개발', 'legacy-dev': '레거시 개발'}


class EnvironmentRegistryTests(unittest.TestCase):
    origin = 'http://127.0.0.1:39001'

    def parse(self, product='elementary-pc', **changes):
        return parse_options({'profileId': product, **changes}, self.origin)

    def test_registry_contains_exactly_four_products_and_sixteen_user_supplied_urls(self):
        self.assertEqual(set(PRODUCT_ENVIRONMENTS), set(EXPECTED_URLS))
        self.assertEqual(sum(map(len, PRODUCT_ENVIRONMENTS.values())), 16)
        for product, expected in EXPECTED_URLS.items():
            with self.subTest(product=product):
                entries = PRODUCT_ENVIRONMENTS[product]
                self.assertEqual([entry['id'] for entry in entries], list(EXPECTED_LABELS))
                self.assertEqual({entry['id']: entry['url'] for entry in entries}, expected)
                self.assertEqual({entry['id']: entry['label'] for entry in entries}, EXPECTED_LABELS)

    def test_bootstrap_product_defaults_select_registered_production_and_staging(self):
        available = {profile['id']: profile for profile in profiles(self.origin)}
        for product, urls in EXPECTED_URLS.items():
            with self.subTest(product=product):
                profile = available[product]
                self.assertFalse(profile.get('disabled', False))
                self.assertEqual(profile['environments'], PRODUCT_ENVIRONMENTS[product])
                self.assertEqual((profile['baselineEnvironmentId'], profile['candidateEnvironmentId']),
                                 ('production', 'staging'))
                self.assertEqual((profile['baselineUrl'], profile['candidateUrl']),
                                 (urls['production'], urls['staging']))
                self.assertEqual((profile['defaults']['baselineName'], profile['defaults']['candidateName']),
                                 ('운영', 'STG'))
                parsed = self.parse(product)
                self.assertEqual((parsed['baseline_environment_id'], parsed['candidate_environment_id']),
                                 ('production', 'staging'))

    def test_bootstrap_environment_mutation_cannot_change_registry_or_later_responses(self):
        before = copy.deepcopy(PRODUCT_ENVIRONMENTS)
        first = {profile['id']: profile for profile in profiles(self.origin)}
        for product in EXPECTED_URLS:
            first[product]['environments'][0]['url'] = 'https://unregistered.invalid/'
            first[product]['environments'][0]['label'] = 'changed'
            first[product]['environments'].append({'id': 'other', 'label': 'other', 'url': 'https://other.invalid/'})
            first[product]['defaults']['baselineName'] = 'changed'
        self.assertEqual(PRODUCT_ENVIRONMENTS, before)
        later = {profile['id']: profile for profile in profiles(self.origin)}
        for product in EXPECTED_URLS:
            self.assertEqual(later[product]['environments'], before[product])
            self.assertEqual(later[product]['defaults']['baselineName'], '운영')

    def test_every_product_pair_can_be_selected_by_ids_without_urls(self):
        for product, urls in EXPECTED_URLS.items():
            for baseline, candidate in itertools.product(EXPECTED_LABELS, repeat=2):
                with self.subTest(product=product, baseline=baseline, candidate=candidate):
                    options = self.parse(product, baselineEnvironmentId=baseline, candidateEnvironmentId=candidate)
                    self.assertEqual((options['baseline_url'], options['candidate_url']),
                                     (urls[baseline], urls[candidate]))
                    self.assertEqual((options['baseline_environment_id'], options['candidate_environment_id']),
                                     (baseline, candidate))
                    self.assertEqual((options['baseline_name'], options['candidate_name']),
                                     (EXPECTED_LABELS[baseline], EXPECTED_LABELS[candidate]))
                    expected_hosts = {urlsplit(urls[baseline]).netloc, urlsplit(urls[candidate]).netloc}
                    self.assertEqual(set(options['allowed_hosts']), expected_hosts)
                    self.assertEqual(options['viewport'], {'width': 390, 'height': 844}
                                     if 'mobile' in product else {'width': 1365, 'height': 768})

    def test_explicit_known_id_requires_its_own_product_exact_url(self):
        for side in ('baseline', 'candidate'):
            for wrong_url in (EXPECTED_URLS['elementary-pc']['staging'],
                              EXPECTED_URLS['secondary-pc']['production'],
                              'https://e.vivasam.com/main/',
                              'https://e.vivasam.com/main?qa=1',
                              'https://e.vivasam.com/main#/'):
                with self.subTest(side=side, wrong_url=wrong_url), self.assertRaises(ValueError):
                    self.parse(**{side + 'EnvironmentId': 'production', side + 'Url': wrong_url})
        accepted = self.parse(baselineEnvironmentId='production',
                              baselineUrl=EXPECTED_URLS['elementary-pc']['production'])
        self.assertEqual(accepted['baseline_environment_id'], 'production')

    def test_omitted_ids_infer_exact_registered_urls_without_guessing_other_urls(self):
        for product, urls in EXPECTED_URLS.items():
            for environment_id, url in urls.items():
                with self.subTest(product=product, environment=environment_id):
                    options = self.parse(product, baselineUrl=url, candidateUrl=url)
                    self.assertEqual((options['baseline_environment_id'], options['candidate_environment_id']),
                                     (environment_id, environment_id))
        variants = (EXPECTED_URLS['secondary-pc']['production'],
                    'https://e.vivasam.com/main/', 'https://e.vivasam.com/main?qa=1',
                    'https://unregistered.invalid/#/home')
        for url in variants:
            with self.subTest(unregistered=url):
                options = self.parse(baselineUrl=url, candidateUrl=url)
                self.assertEqual((options['baseline_environment_id'], options['candidate_environment_id']),
                                 ('custom', 'custom'))
                self.assertEqual((options['baseline_url'], options['candidate_url']), (url, url))

    def test_mobile_production_hash_is_not_inferred_from_legacy_hash_route(self):
        for product in ('elementary-mobile', 'secondary-mobile'):
            with self.subTest(product=product):
                production = EXPECTED_URLS[product]['production']
                legacy = EXPECTED_URLS[product]['legacy-dev']
                self.assertNotIn('#', production)
                self.assertTrue(legacy.endswith('/#/'))
                options = self.parse(product, baselineUrl=production + '#/', candidateUrl=legacy)
                self.assertEqual(options['baseline_environment_id'], 'custom')
                self.assertEqual(options['candidate_environment_id'], 'legacy-dev')
                self.assertEqual(options['baseline_url'], production + '#/')

    def test_unknown_ids_are_rejected_and_custom_requires_an_explicit_url(self):
        for side in ('baseline', 'candidate'):
            for unknown in ('dev', 'STG', 'other', '../production'):
                with self.subTest(side=side, unknown=unknown), self.assertRaises(ValueError):
                    self.parse(**{side + 'EnvironmentId': unknown})
            with self.subTest(side=side, missing_custom_url=True), self.assertRaises(ValueError):
                self.parse(**{side + 'EnvironmentId': 'custom'})
        options = self.parse(baselineEnvironmentId='custom', baselineUrl='https://one.invalid/old#/home',
                             candidateEnvironmentId='custom', candidateUrl='https://two.invalid/new.do')
        self.assertEqual((options['baseline_environment_id'], options['candidate_environment_id']), ('custom', 'custom'))
        self.assertEqual((options['baseline_url'], options['candidate_url']),
                         ('https://one.invalid/old#/home', 'https://two.invalid/new.do'))
        explicit_custom = self.parse(baselineEnvironmentId='custom',
                                     baselineUrl=EXPECTED_URLS['elementary-pc']['production'])
        self.assertEqual(explicit_custom['baseline_environment_id'], 'custom')

    def test_single_environment_omits_b_identity_url_name_and_host(self):
        for product, urls in EXPECTED_URLS.items():
            with self.subTest(product=product):
                options = self.parse(product, testType='single', baselineEnvironmentId='legacy-dev',
                                     candidateEnvironmentId='staging')
                self.assertEqual(options['baseline_environment_id'], 'legacy-dev')
                self.assertEqual(options['baseline_url'], urls['legacy-dev'])
                for key in ('candidate_environment_id', 'candidate_url', 'candidate_name'):
                    self.assertIsNone(options[key])
                self.assertEqual(options['allowed_hosts'], [urlsplit(urls['legacy-dev']).netloc])

    def test_explicit_operator_aliases_and_public_environment_identity_survive(self):
        options = self.parse('secondary-mobile', baselineEnvironmentId='legacy-dev',
                             candidateEnvironmentId='vibe-dev', baselineName='QA-A 기준서버',
                             candidateName='QA-B 신규서버')
        self.assertEqual((options['baseline_name'], options['candidate_name']), ('QA-A 기준서버', 'QA-B 신규서버'))
        public = public_options(options)
        self.assertEqual((public['baselineEnvironmentId'], public['candidateEnvironmentId']), ('legacy-dev', 'vibe-dev'))
        self.assertEqual((public['baselineName'], public['candidateName']), ('QA-A 기준서버', 'QA-B 신규서버'))
        self.assertNotIn('baseline_environment_id', public)
        self.assertNotIn('candidate_environment_id', public)


if __name__ == '__main__':
    unittest.main()
