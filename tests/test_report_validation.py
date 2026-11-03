import copy
import math
import unittest

from qa.report_validation import validate_report


def report():
    return {'manifest': {}, 'results': [{'id': 'one', 'status': 'PASS',
            'checks': [{'check_id': 'required', 'status': 'PASS'}],
            'visual': {'differencePercent': 0}}]}


class ReportContractTests(unittest.TestCase):
    def test_seven_states_zero_null_and_additional_fields_are_supported_without_mutation(self):
        for status in ('PASS', 'FAIL', 'DIFF', 'SKIP', 'BLOCKED', 'ERROR', 'REVIEW'):
            for difference in (0, 100, None):
                value = report()
                value['results'][0].update(status=status, extraMinorField={'kept': True})
                value['results'][0]['checks'][0]['status'] = status
                value['results'][0]['visual']['differencePercent'] = difference
                original = copy.deepcopy(value)
                self.assertIs(validate_report(value), value)
                self.assertEqual(value, original)

    def test_invalid_numeric_evidence_never_becomes_zero_percent(self):
        for difference in (True, -1, 101, '0', math.nan, math.inf):
            value = report()
            value['results'][0]['visual']['differencePercent'] = difference
            with self.subTest(difference=difference), self.assertRaisesRegex(ValueError, 'differencePercent'):
                validate_report(value)

    def test_duplicate_ids_and_invalid_statuses_are_explicit_contract_errors(self):
        value = report()
        value['results'].append(copy.deepcopy(value['results'][0]))
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            validate_report(value)
        value = report()
        value['results'][0]['checks'][0]['status'] = 'SUCCESS'
        with self.assertRaisesRegex(ValueError, 'identity/status'):
            validate_report(value)
        for value in (None, [], {'manifest': {}, 'results': {}}, {'results': []}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_report(value)
