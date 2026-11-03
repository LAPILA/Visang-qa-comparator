"""Environment-scoped page catalogue; it records coverage, not site completeness."""
from __future__ import annotations

import hashlib

from .matching import page_key, public_url
from .policy import sanitize_message


def _safe(value):
    if isinstance(value, dict):
        return {key: _safe(item) for key, item in value.items() if not key.startswith('_')}
    if isinstance(value, list):
        return [_safe(item) for item in value]
    if isinstance(value, str):
        return public_url(value) if value.startswith(('http://', 'https://', '/')) else sanitize_message(value, 500)
    return value


def build_inventory(options, baseline, candidate, baseline_deferred, candidate_deferred, pairs):
    environments = []
    for side, name_key, seed_key, observed, deferred in (
            ('a', 'baseline_name', 'baseline_url', baseline, baseline_deferred),
            ('b', 'candidate_name', 'candidate_url', candidate, candidate_deferred)):
        if not options.get(seed_key):
            continue
        records = list(observed.values()) + list(deferred)
        pages, seen = [], set()
        for record in records:
            url = public_url(record['url'])
            if url in seen:
                continue
            seen.add(url)
            actions = record.get('actions') or []
            pages.append({
                'id': hashlib.sha256((side + url).encode()).hexdigest()[:20],
                'pageKey': page_key(url), 'url': url, 'finalUrl': public_url(record.get('finalUrl') or url),
                'title': sanitize_message(record.get('title') or '', 160),
                'navigationTrail': _safe(record.get('navigationTrail') or []),
                'signature': _safe(record.get('pageSignature') or {}),
                'visited': bool(record.get('navigated')), 'statusCode': record.get('statusCode'),
                'captureReady': bool(record.get('captureReady')), 'actionCount': len(actions),
                'approvedActionCount': sum(bool(action.get('allowed')) for action in actions),
                'blockedActionCount': sum(not action.get('allowed') for action in actions),
                'notExecutedReasons': sorted({item.get('reason_code') for item in record.get('checks', [])
                                              if item.get('status') in ('SKIP', 'BLOCKED', 'ERROR') and item.get('reason_code')}),
            })
        environments.append({
            'id': side, 'name': options.get(name_key) or side.upper(),
            'environmentId': options.get('baseline_environment_id' if side == 'a' else 'candidate_environment_id', 'custom'),
            'seedUrl': public_url(options[seed_key]), 'pages': pages,
            'discoveredCount': len(pages), 'visitedCount': sum(page['visited'] for page in pages),
            'deferredCount': sum(not page['visited'] for page in pages),
        })
    matches = []
    for pair in pairs or []:
        a, b, match = pair.get('baseline'), pair.get('candidate'), pair.get('match') or {}
        urls = [public_url(item['url']) if item else None for item in (a, b)]
        matches.append({
            'id': hashlib.sha256(str(urls).encode()).hexdigest()[:20], 'key': public_url(pair['key']),
            'baselineUrl': urls[0], 'candidateUrl': urls[1],
            'baselineKey': page_key(urls[0]) if urls[0] else None,
            'candidateKey': page_key(urls[1]) if urls[1] else None,
            'aliasSafe': bool(a and b and urls[0] == a['url'] and urls[1] == b['url']),
            'method': match.get('method'), 'approved': bool(match.get('approved')),
            'reason': match.get('reason'), 'evidence': _safe(match.get('evidence') or []),
            'candidates': _safe(match.get('candidates') or []),
        })
    return {'schemaVersion': '1.0', 'productId': options.get('profile_id', 'custom'),
            'crawlScope': options.get('crawl_scope', 'approved_paths'), 'environments': environments,
            'matches': matches, 'requiresReview': any(not match['approved'] for match in matches),
            'limitations': ['Catalogue contains only pages observed or deferred in this bounded run.',
                            'Unknown buttons, write requests and downloads are not executed.',
                            'Semantic similarity is a mapping suggestion, not product correctness.']}
