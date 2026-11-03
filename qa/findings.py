"""Deterministic finding taxonomy and deduplication, independent of verdicts."""
from __future__ import annotations

import copy
import hashlib
import json
import re
from urllib.parse import urlsplit, urlunsplit

from .policy import sanitize_message, sanitize_url

TAXONOMY = {
    'HTTP': 'HTTP responses', 'NETWORK': 'Connections and transport',
    'JAVASCRIPT': 'Client execution', 'API': 'Explicit API contracts',
    'RESOURCE': 'Images and static resources', 'NAVIGATION': 'Links and navigation',
    'STRUCTURE': 'DOM and components', 'FUNCTIONAL': 'Functional contracts',
    'VISUAL': 'Visual and layout', 'DATA': 'Data and display conditions',
    'AUTH': 'Authentication and authorization', 'TEST_INFRA': 'Test infrastructure',
}
SEVERITIES = ('NONE', 'LOW', 'MEDIUM', 'HIGH', 'CRITICAL')
_STATUS_RANK = {'PASS': 0, 'SKIP': 1, 'DIFF': 2, 'REVIEW': 3, 'BLOCKED': 4, 'ERROR': 5, 'FAIL': 6}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode('utf-8')).hexdigest()


def environment(value, row=None, item=None):
    value = {'baseline': 'a', 'candidate': 'b', 'both': 'comparison'}.get(value, value)
    if value in ('a', 'b', 'comparison'):
        return value
    cid = (item or {}).get('check_id', '')
    if cid.startswith(('a.', 'b.')):
        return cid[0]
    if row:
        if row.get('baseline') and not row.get('candidate'):
            return 'a'
        if row.get('candidate') and not row.get('baseline'):
            return 'b'
        if row.get('baseline') and row.get('candidate'):
            return 'comparison'
    return 'unknown'


def _route(value, external=False):
    value = str(value or '')
    if not value.startswith(('http://', 'https://')):
        return value
    p = urlsplit(sanitize_url(value))
    return urlunsplit(('', p.netloc if external else '', p.path or '/', p.query, p.fragment))


def page_identity(row):
    return str(row.get('page_class') or row.get('pageClass') or row.get('key') or
               _route((row.get('baseline') or row.get('candidate') or {}).get('url')) or 'unknown-page')


def assertion_identity(row, item):
    obs = item.get('observation') or {}
    env = environment(item.get('environment') or obs.get('environment'), row, item)
    check_id = str(item.get('check_id') or item.get('checkId') or '')
    generated_observation = bool(obs) and _is_observation_check(check_id)
    # The engine reserves observation.* for generated checks. Its suffix may be
    # an old array index, UUID, or request-derived hash: none is a rule identity.
    if generated_observation:
        check_id = 'observation.' + str(obs.get('ruleId') or item.get('rule_id') or
                                       obs.get('category') or item.get('reason_code'))
    if obs and _resource_observation(item, obs):
        check_id = 'resource.' + classify(item, obs)[1]
    # Older saved generated checks inherited engine/observe from check(), even
    # when their source event belonged to a scenario step. Explicit contracts
    # still own their scenario and step; only generated wrappers defer to events.
    scenario = (obs.get('scenarioId') or item.get('scenario_id')) if generated_observation else (item.get('scenario_id') or obs.get('scenarioId'))
    step = (obs.get('stepId') or item.get('step_id')) if generated_observation else (item.get('step_id') or obs.get('stepId'))
    return {'environment': env, 'pageKey': page_identity(row), 'checkId': check_id,
            'scenarioId': str(scenario or 'engine'), 'stepId': str(step or 'observe'),
            'target': _route(obs.get('url'), obs.get('source') == 'THIRD_PARTY') if obs else ''}


def assertion_key(row, item):
    return digest(assertion_identity(row, item))


def _is_observation_check(check_id):
    return re.match(r'^(?:[ab]\.)?observation\.', check_id) is not None


def _resource_observation(item, obs):
    cid = str(item.get('check_id') or '')
    return bool(obs and not obs.get('ruleId') and
                _is_observation_check(cid) and classify(item, obs)[0] == 'RESOURCE')


def _policy_context(item, obs):
    reasons = {str(item.get('reason_code') or '').upper(), str(obs.get('category') or '').upper()}
    if reasons & {'JS_ERROR_AFTER_POLICY_BLOCK', 'CONSOLE_ERROR_AFTER_POLICY_BLOCK'}:
        return {'policyInterference': True, 'policyRelation': 'laterAfterPolicyBlock'}
    message = str(obs.get('message') or item.get('actual') or '').upper()
    if 'CONSOLE_ERROR' in reasons and 'NET::ERR_BLOCKED_BY_CLIENT' in message:
        context = {'policyRelation': 'blockedByClientObserved'}
        if obs.get('policyInterference') is True:
            context['policyInterference'] = True
        return context
    return {}


def classify(item, observation=None):
    obs = observation or item.get('observation') or {}
    reason = str(item.get('reason_code') or obs.get('category') or '').upper()
    category = item.get('category')
    subtype = item.get('subtype')
    resource = str(obs.get('resourceType') or obs.get('resource_type') or '').lower()
    http_status = obs.get('statusCode', obs.get('status'))
    has_api_contract = bool(item.get('api_contract') or item.get('apiContract') or
                            (category == 'API' and item.get('expected') is not None) or
                            (reason.startswith('API_') and item.get('expected') is not None))
    if has_api_contract:
        return 'API', subtype or ('API_SCHEMA_MISMATCH' if 'SCHEMA' in reason else 'API_BUSINESS_FAILURE' if 'BUSINESS' in reason else 'API_STATUS_MISMATCH')
    policy_context = _policy_context(item, obs)
    if policy_context:
        return 'TEST_INFRA', ('POLICY_INTERFERENCE' if policy_context.get('policyInterference')
                              else 'CLIENT_BLOCK_OBSERVED')
    if reason == 'REQUEST_ABORTED':
        return 'NETWORK', 'REQUEST_ABORTED'
    if resource in ('image', 'script', 'stylesheet', 'font') and (isinstance(http_status, int) and http_status >= 400 or 'FAILED' in reason or 'NETWORK' in reason):
        return 'RESOURCE', {'image': 'IMAGE_LOAD_FAILED', 'script': 'SCRIPT_LOAD_FAILED',
                            'stylesheet': 'STYLESHEET_LOAD_FAILED', 'font': 'FONT_LOAD_FAILED'}[resource]
    if category in TAXONOMY and category != 'API':
        return category, subtype or reason or 'UNSPECIFIED'
    if 'BROKEN_IMAGE' in reason:
        return 'RESOURCE', 'IMAGE_LOAD_FAILED'
    if reason.startswith('HTTP') or isinstance(http_status, int) and http_status >= 400:
        return 'HTTP', 'HTTP_5XX' if isinstance(http_status, int) and http_status >= 500 or '5XX' in reason else 'HTTP_4XX'
    if any(token in reason for token in ('NETWORK', 'DNS', 'TLS', 'CONNECTION', 'REQUEST_TIMEOUT')):
        subtype = next((name for name in ('DNS_FAILED', 'TLS_FAILED', 'REQUEST_TIMEOUT') if name.split('_')[0] in reason), 'CONNECTION_FAILED')
        return 'NETWORK', subtype
    if any(token in reason for token in ('JS_ERROR', 'JAVASCRIPT', 'UNCAUGHT', 'UNHANDLED', 'CONSOLE')):
        return 'JAVASCRIPT', 'CONSOLE_ERROR' if 'CONSOLE' in reason else 'UNHANDLED_REJECTION' if 'REJECTION' in reason else 'UNCAUGHT_EXCEPTION'
    if any(token in reason for token in ('AUTH', 'LOGIN', 'SESSION', 'ACCESS_DENIED', 'ROLE_UNAVAILABLE')):
        return 'AUTH', 'SESSION_EXPIRED' if 'EXPIRED' in reason else 'ACCESS_DENIED' if 'DENIED' in reason else 'LOGIN_REQUIRED'
    if any(token in reason for token in ('DATA', 'CONTENT_DIFF', 'PRECONDITION')):
        return 'DATA', 'CONTENT_DIFF' if 'DIFF' in reason else 'INSUFFICIENT_DATA'
    if any(token in reason for token in ('VISUAL_DIFFERENCE', 'REGION_DIFF', 'OVERFLOW', 'OVERLAP', 'LAYOUT')):
        return 'VISUAL', 'TEXT_OVERFLOW' if 'OVERFLOW' in reason else 'ELEMENT_OVERLAP' if 'OVERLAP' in reason else 'REGION_DIFF'
    if any(token in reason for token in ('REQUIRED_REGION', 'REQUIRED_ELEMENT', 'REGION_NOT_VISIBLE', 'ELEMENT_COUNT')):
        return 'STRUCTURE', 'VISIBILITY_MISMATCH' if 'VISIBLE' in reason else 'ELEMENT_COUNT_MISMATCH' if 'COUNT' in reason else 'REQUIRED_ELEMENT_MISSING'
    if any(token in reason for token in ('HISTORY', 'WRONG_DESTINATION', 'BROKEN_LINK', 'REDIRECT')):
        return 'NAVIGATION', 'HISTORY_MISMATCH' if 'HISTORY' in reason else 'REDIRECT_LOOP' if 'REDIRECT' in reason else 'BROKEN_LINK'
    if item.get('scenario_id') not in (None, '', 'engine') and item.get('status') == 'FAIL':
        return 'FUNCTIONAL', 'SEARCH_RESULT_MISMATCH' if 'search' in item['scenario_id'] else 'VALIDATION_MISMATCH' if 'input' in item['scenario_id'] else 'INTERACTION_MISMATCH'
    return 'TEST_INFRA', 'MAPPING_UNRESOLVED' if any(token in reason for token in ('MATCH', 'DISCOVERED')) else 'CAPTURE_FAILED' if 'CAPTURE' in reason or 'SCREENSHOT' in reason else 'COMPARE_FAILED' if 'IMAGE' in reason or 'COMPAR' in reason else reason or 'OBSERVATION_UNCLASSIFIED'


def _severity(item, category):
    if item.get('severity') in SEVERITIES:
        return item['severity']
    status = item.get('status', item.get('level', 'REVIEW'))
    if category == 'DATA' and status in ('DIFF', 'REVIEW'):
        return 'LOW'
    if status == 'FAIL':
        return 'HIGH' if category in ('STRUCTURE', 'FUNCTIONAL', 'API', 'NAVIGATION', 'AUTH') else 'MEDIUM'
    return 'MEDIUM' if status in ('ERROR', 'BLOCKED') else 'LOW' if status in ('DIFF', 'REVIEW') else 'NONE'


def _event_key(row, obs, side):
    env = environment(obs.get('environment') or side, row)
    semantic = (obs.get('observationId') or
                [obs.get('requestId'), obs.get('category'), obs.get('url'), obs.get('message'), obs.get('scenarioId'), obs.get('stepId')])
    return digest([env, page_identity(row), semantic])


def _evidence(values):
    result = []
    for value in values:
        if not isinstance(value, str):
            continue
        # References only; never read paths and never export absolute local paths.
        if value.startswith('/artifacts/') or value.startswith(('http://', 'https://')):
            safe = sanitize_url(value) if value.startswith('http') else value
            if safe not in result:
                result.append(safe)
    return result


def _observation_evidence(obs):
    result = {key: copy.deepcopy(obs[key]) for key in
              ('observationId', 'requestId', 'category', 'level', 'statusCode', 'method', 'resourceType',
               'source', 'environment', 'pageId', 'scenarioId', 'stepId', 'timestamp', 'lastSeenAt',
               'count', 'policyInterference') if key in obs}
    if 'message' in obs:
        result['message'] = sanitize_message(str(obs['message']))
    if 'url' in obs:
        result['url'] = sanitize_url(str(obs['url']))
    if 'causeConfirmed' in obs:
        # Timing and client-block messages do not establish product causality.
        result['causeConfirmed'] = False
    if isinstance(obs.get('relatedBlockedRequests'), list):
        result['relatedBlockedRequests'] = [
            {key: sanitize_url(str(value)) if key == 'url' else sanitize_message(str(value))
             for key, value in request.items() if key in ('url', 'reason', 'resourceType', 'method')}
            for request in obs['relatedBlockedRequests'] if isinstance(request, dict)]
    return result


def enrich_report(report):
    """Return an enriched copy while preserving automatic status and review data."""
    enriched = copy.deepcopy(report)
    rows = enriched.get('results') or []
    manifest = enriched.get('manifest') or {}
    first_default, last_default = manifest.get('startedAt'), manifest.get('finishedAt')
    raw_events, linked_events, candidates = {}, set(), []
    for row in rows:
        for item in row.get('checks', []):
            obs = item.get('observation')
            if isinstance(obs, dict):
                event_id = _event_key(row, obs, item.get('environment'))
                raw_events[event_id] = obs
                linked_events.add(event_id)
            else:
                event_id = None
            if item.get('status') not in ('PASS', 'SKIP'):
                candidates.append((row, item, obs or {}, event_id))
        for field, side in (('baseline', 'a'), ('candidate', 'b')):
            for obs in (row.get(field) or {}).get('issues', []):
                if not isinstance(obs, dict):
                    continue
                event_id = _event_key(row, obs, side)
                raw_events[event_id] = obs
    # Unlinked observations are represented once per source row, then fingerprinted.
    for row in rows:
        for field, side in (('baseline', 'a'), ('candidate', 'b')):
            for obs in (row.get(field) or {}).get('issues', []):
                event_id = _event_key(row, obs, side)
                if event_id in linked_events or obs.get('level') in ('PASS', 'SKIP'):
                    continue
                item = {'check_id': 'observation.' + str(obs.get('ruleId') or obs.get('category') or 'unknown'),
                        'scenario_id': obs.get('scenarioId', 'engine'), 'step_id': obs.get('stepId', 'observe'),
                        'environment': environment(obs.get('environment') or side), 'status': obs.get('level', 'REVIEW'),
                        'reason_code': obs.get('category'), 'actual': obs.get('message'), 'observation': obs}
                candidates.append((row, item, obs, event_id))
    grouped = {}
    row_findings = {str(row.get('id', index)): set() for index, row in enumerate(rows)}
    linked_issues = set()
    for row, item, obs, event_id in candidates:
        category, subtype = classify(item, obs)
        policy_context = _policy_context(item, obs) if category == 'TEST_INFRA' else {}
        identity = assertion_identity(row, item)
        semantic = {'assertion': identity, 'category': category, 'subtype': subtype}
        resource_observation = _resource_observation(item, obs)
        if obs and not resource_observation:
            semantic['observation'] = {'method': obs.get('method'), 'resourceType': obs.get('resourceType'),
                'httpStatus': obs.get('statusCode'), 'source': obs.get('source'),
                'message': sanitize_message(obs.get('message', '')) if category in ('JAVASCRIPT', 'NETWORK') or policy_context else None}
        fingerprint = digest(semantic)
        fid = 'finding-' + fingerprint[:24]
        severity = _severity(item, category)
        row_id = str(row.get('id', rows.index(row)))
        tags = {category, str(obs.get('category') or item.get('reason_code') or '')} - {''}
        if policy_context:
            tags.update(('JAVASCRIPT', subtype))
            tags.add('CONSOLE_ERROR' if 'CONSOLE' in str(obs.get('category') or item.get('reason_code')) else 'JS_ERROR')
        if obs.get('statusCode') is not None:
            tags.add('HTTP_' + str(obs['statusCode']))
        evidence = _evidence([*item.get('evidence', []), obs.get('url'),
                              (row.get('baseline') or {}).get('screenshot'), (row.get('candidate') or {}).get('screenshot'),
                              (row.get('visual') or {}).get('url')])
        first = obs.get('timestamp') or obs.get('firstSeenAt') or first_default
        last = obs.get('lastSeenAt') or obs.get('timestamp') or last_default or first
        finding = grouped.setdefault(fingerprint, {
            'id': fid, 'fingerprint': fingerprint, 'assertionKey': assertion_key(row, item),
            **identity, 'category': category, 'subtype': subtype, 'severity': severity,
            'status': item.get('status', 'REVIEW'), 'summary': sanitize_message(str(item.get('reason_code') or subtype)),
            'reasonCode': item.get('reason_code'), 'expected': copy.deepcopy(item.get('expected')),
            'actual': copy.deepcopy(item.get('actual')), 'occurrenceCount': 0,
            'firstSeenAt': first, 'lastSeenAt': last, 'evidence': [], 'rowIds': [], 'tags': [],
            'observations': [], '_events': set(), '_assertions': set(),
            '_resourceCounts': {'network': 0, 'dom': 0},
        })
        finding.update(policy_context)
        if policy_context and 'causeConfirmed' in obs:
            finding['causeConfirmed'] = False
        if event_id and event_id not in finding['_events']:
            finding['_events'].add(event_id)
            count = max(1, int(obs.get('count') or obs.get('occurrenceCount') or 1))
            if resource_observation:
                source_kind = 'dom' if obs.get('category') == 'BROKEN_IMAGE' else 'network'
                finding['_resourceCounts'][source_kind] += count
                finding['occurrenceCount'] = max(finding['_resourceCounts'].values())
            else:
                finding['occurrenceCount'] += count
            finding['observations'].append(_observation_evidence(obs))
        elif not event_id and finding['assertionKey'] not in finding['_assertions']:
            finding['_assertions'].add(finding['assertionKey'])
            finding['occurrenceCount'] += 1
        if _STATUS_RANK.get(item.get('status'), 3) > _STATUS_RANK.get(finding['status'], 3):
            finding['status'] = item['status']
        if SEVERITIES.index(severity) > SEVERITIES.index(finding['severity']):
            finding['severity'] = severity
        for source, target in ((evidence, 'evidence'), (sorted(tags), 'tags'), ([row_id], 'rowIds')):
            finding[target] = list(dict.fromkeys([*finding[target], *source]))
        if first and (not finding['firstSeenAt'] or first < finding['firstSeenAt']):
            finding['firstSeenAt'] = first
        if last and (not finding['lastSeenAt'] or last > finding['lastSeenAt']):
            finding['lastSeenAt'] = last
        row_findings.setdefault(row_id, set()).add(fid)
    findings = list(grouped.values())
    for finding in findings:
        finding.pop('_events')
        finding.pop('_assertions')
        finding.pop('_resourceCounts')
    by_id = {finding['id']: finding for finding in findings}
    for index, row in enumerate(rows):
        ids = sorted(row_findings.get(str(row.get('id', index)), []))
        row['findingIds'] = ids
        row['categories'] = sorted({by_id[fid]['category'] for fid in ids})
        row['subtypes'] = sorted({by_id[fid]['subtype'] for fid in ids})
        row['severity'] = max((by_id[fid]['severity'] for fid in ids), key=SEVERITIES.index, default='NONE')
        if (row.get('review') or {}).get('issueRef'):
            linked_issues.add(canonical(row['review']['issueRef']))
    enriched['findings'] = sorted(findings, key=lambda item: item['fingerprint'])
    enriched.setdefault('totals', {}).update(
        rawObservations=sum(max(1, int(obs.get('count') or obs.get('occurrenceCount') or 1)) for obs in raw_events.values()),
        resultRows=len(rows), uniqueFindings=len(findings), linkedIssues=len(linked_issues))
    enriched['findingSchemaVersion'] = '1.0'
    return enriched
