"""Conservative comparison of already-loaded reports; no file or URL access."""
from __future__ import annotations

import copy

from .findings import assertion_key, canonical, enrich_report

CLASSIFICATIONS = ('NEW', 'RECURRING', 'RESOLVED_CANDIDATE', 'NOT_RETESTED', 'NON_COMPARABLE')
_DIMENSIONS = ('ruleVersion', 'rulesHash', 'profileId', 'mode', 'viewport', 'scenarioIds',
               'conditions', 'routeAliases', 'dataPolicy', 'scope', 'capture')


def _major(version):
    try:
        return int(str(version).split('.')[0])
    except (ValueError, TypeError):
        return None


def _target_shape(manifest):
    scope = manifest.get('scope') or {}
    if scope.get('targetShape') in ('single', 'pair'):
        return scope['targetShape']
    return 'pair' if manifest.get('testType') == 'comparison' else 'single' if manifest.get('testType') in ('single', 'conditional', 'regression') else None


def _comparability(previous, current):
    a, b = previous.get('manifest') or {}, current.get('manifest') or {}
    reasons = []
    versions = [a.get('schemaVersion') or a.get('schema_version'), b.get('schemaVersion') or b.get('schema_version')]
    majors = [_major(value) for value in versions]
    if any(value is None for value in majors):
        reasons.append({'code': 'SCHEMA_VERSION_MISSING', 'field': 'schemaVersion'})
    elif majors[0] != majors[1] or any(value < 2 for value in majors):
        reasons.append({'code': 'LEGACY_OR_INCOMPATIBLE_SCHEMA', 'field': 'schemaVersion', 'previous': versions[0], 'current': versions[1]})
    if _target_shape(a) != _target_shape(b) or _target_shape(a) is None:
        reasons.append({'code': 'TARGET_SHAPE_MISMATCH', 'field': 'scope.targetShape'})
    for field in _DIMENSIONS:
        if field not in a or field not in b:
            reasons.append({'code': 'COMPARISON_METADATA_MISSING', 'field': field})
        elif canonical(a[field]) != canonical(b[field]):
            reasons.append({'code': 'COMPARISON_CONDITIONS_CHANGED', 'field': field})
    return reasons, versions


def _checks(report):
    values = {}
    for row in report.get('results', []):
        for item in row.get('checks', []):
            key = assertion_key(row, item)
            values.setdefault(key, []).append((row, item))
    return values


def evaluate_regression(previous_report, current_report):
    """Classify findings, requiring explicit comparable PASS evidence for resolution.

    Schema-v1 reports remain readable and their findings can be shown, but missing
    contract metadata never silently becomes a comparable baseline.
    """
    if not isinstance(previous_report, dict) or not isinstance(current_report, dict):
        raise ValueError('Regression inputs must be loaded report objects, not file paths.')
    previous = enrich_report(previous_report)
    current = enrich_report(current_report)
    reasons, versions = _comparability(previous, current)
    comparable = not reasons
    old = {item['fingerprint']: item for item in previous.get('findings', [])}
    new = {item['fingerprint']: item for item in current.get('findings', [])}
    current_checks = _checks(current)
    previous_checks = _checks(previous)
    entries = []
    for fingerprint in sorted(set(old) | set(new)):
        before, after = old.get(fingerprint), new.get(fingerprint)
        if not comparable:
            classification, reason = 'NON_COMPARABLE', 'RUN_CONTRACTS_NOT_COMPARABLE'
        elif before and after:
            classification, reason = 'RECURRING', 'SAME_FINDING_OBSERVED'
        elif after:
            prior_checks = previous_checks.get(after['assertionKey'], [])
            verified_prior = prior_checks and all(item.get('status') in ('PASS', 'FAIL', 'DIFF') and item.get('executed', True) is not False
                                                  for _, item in prior_checks)
            if verified_prior:
                classification, reason = 'NEW', 'NEW_OBSERVATION_AFTER_VERIFIED_BASELINE_CHECK'
            else:
                classification, reason = 'NON_COMPARABLE', 'BASELINE_ASSERTION_NOT_VERIFIED'
        else:
            candidates = current_checks.get(before['assertionKey'], [])
            # A failure, block, error or ambiguous duplicate with the same assertion
            # prevents a disappearing finding being declared resolved.
            explicit_pass = candidates and all(item.get('status') == 'PASS' and item.get('executed', True) is not False
                                               and (item.get('expected') is not None or item.get('executed') is True) for _, item in candidates)
            if explicit_pass:
                classification, reason = 'RESOLVED_CANDIDATE', 'SAME_ASSERTION_EXECUTED_AND_PASSED'
            else:
                classification, reason = 'NOT_RETESTED', 'NO_COMPARABLE_PASS_EVIDENCE'
        item = after or before
        linked_rows = list((after or {}).get('rowIds', []))
        if not after and comparable:
            linked_rows = list(dict.fromkeys(str(row.get('id')) for row, _ in current_checks.get(before['assertionKey'], [])))
        entries.append({'fingerprint': fingerprint, 'classification': classification, 'reason': reason,
                        'previousFindingId': before['id'] if before else None,
                        'currentFindingId': after['id'] if after else None,
                        'environment': item['environment'], 'pageKey': item['pageKey'], 'checkId': item['checkId'],
                        'category': item['category'], 'subtype': item['subtype'], 'currentRowIds': linked_rows,
                        'previousRowIds': list((before or {}).get('rowIds', [])),
                        'requiresReview': classification == 'RESOLVED_CANDIDATE'})
    row_results = {}
    order = ('NON_COMPARABLE', 'NEW', 'RECURRING', 'NOT_RETESTED', 'RESOLVED_CANDIDATE')
    for row in current.get('results', []):
        row_id = str(row.get('id'))
        related = [item for item in entries if row_id in item['currentRowIds']]
        if related:
            labels = sorted({item['classification'] for item in related}, key=order.index)
            row_results[row_id] = {'classification': labels[0], 'classifications': labels,
                                   'findingFingerprints': [item['fingerprint'] for item in related]}
        elif not comparable:
            row_results[row_id] = {'classification': 'NON_COMPARABLE', 'classifications': ['NON_COMPARABLE'], 'findingFingerprints': []}
    return {
        'comparable': comparable,
        'comparability': {'comparable': comparable, 'reasons': copy.deepcopy(reasons)},
        'reasons': reasons, 'previousSchemaVersion': versions[0], 'currentSchemaVersion': versions[1],
        'previousRunId': (previous.get('manifest') or {}).get('runId'),
        'currentRunId': (current.get('manifest') or {}).get('runId'),
        'summary': {name: sum(item['classification'] == name for item in entries) for name in CLASSIFICATIONS},
        'findings': entries, 'rows': row_results,
        'limitations': ['Resolution is a review candidate, never automatic bug closure.',
                        'Missing observations without a repeated passing assertion are not resolution evidence.'],
    }
