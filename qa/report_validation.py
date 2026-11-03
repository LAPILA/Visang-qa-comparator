"""Validate newly produced reports before publishing a successful execution.

Historical reports are read without changing their verdicts. Additional fields
remain compatible; invalid statuses, duplicate row IDs and false numeric evidence
cannot silently enter the current report pipeline.
"""
from __future__ import annotations

import math

from .policy import STATUSES


def validate_report(report):
    if not isinstance(report, dict) or not isinstance(report.get('manifest'), dict):
        raise ValueError('REPORT_CONTRACT_INVALID: report/manifest must be objects')
    rows = report.get('results')
    if not isinstance(rows, list) or len(rows) > 10000:
        raise ValueError('REPORT_CONTRACT_INVALID: results must be an array of at most 10000 rows')
    identifiers = set()
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get('id'), str) or not row['id']:
            raise ValueError('REPORT_CONTRACT_INVALID: each result requires an ID')
        if row['id'] in identifiers:
            raise ValueError('REPORT_CONTRACT_INVALID: duplicate result ID')
        identifiers.add(row['id'])
        if row.get('status') not in STATUSES:
            raise ValueError('REPORT_CONTRACT_INVALID: unknown result status')
        checks = row.get('checks')
        if not isinstance(checks, list):
            raise ValueError('REPORT_CONTRACT_INVALID: checks must be an array')
        for item in checks:
            if not isinstance(item, dict) or not item.get('check_id') or item.get('status') not in STATUSES:
                raise ValueError('REPORT_CONTRACT_INVALID: invalid check identity/status')
        visual = row.get('visual')
        if visual is not None:
            if not isinstance(visual, dict):
                raise ValueError('REPORT_CONTRACT_INVALID: visual must be an object or null')
            difference = visual.get('differencePercent')
            if difference is not None and (isinstance(difference, bool) or not isinstance(difference, (float, int))
                                           or not math.isfinite(difference) or not 0 <= difference <= 100):
                raise ValueError('REPORT_CONTRACT_INVALID: differencePercent must be null or finite 0..100')
    return report
