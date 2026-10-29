"""Conservative page identity and explicit, reviewable cross-environment matches."""
from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit


def normalize_url(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 2000:
        raise ValueError('URL is required (maximum 2000 characters).')
    p = urlsplit(value.strip())
    if p.scheme not in ('http', 'https') or not p.hostname or p.username or p.password:
        raise ValueError('Use an http(s) URL without embedded credentials.')
    # Query ordering/repeated keys and hash routes can carry application meaning.
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path or '/', p.query, p.fragment))


def page_key(url):
    p = urlsplit(url)
    return (p.path or '/') + ('?' + p.query if p.query else '') + ('#' + p.fragment if p.fragment else '')


def _alias_key(url, aliases, side):
    identity = page_key(url)
    p = urlsplit(url)
    path = p.path or '/'
    for index, rule in enumerate(aliases):
        raw = rule.get(side)
        if not raw:
            continue
        rule_key = page_key(raw)
        # Path aliases preserve the state/query/hash rather than merging all instances.
        if identity == rule_key:
            return 'alias:' + str(index), rule.get('page_class', 'alias-' + str(index))
        if '?' not in rule_key and '#' not in rule_key and path == rule_key:
            suffix = ('?' + p.query if p.query else '') + ('#' + p.fragment if p.fragment else '')
            return 'alias:' + str(index) + suffix, rule.get('page_class', 'alias-' + str(index)) + suffix
    return None


def match_pages(baseline, candidate, aliases=None):
    """Return each observed page once; heading similarity only suggests REVIEW pairs."""
    aliases = aliases or []
    ambiguous_aliases = set()
    for side in ('baseline', 'candidate'):
        seen_rules = {}
        for rule in aliases:
            identity = page_key(rule.get(side, ''))
            counterpart = page_key(rule.get('candidate' if side == 'baseline' else 'baseline', ''))
            if identity in seen_rules and seen_rules[identity] != counterpart:
                ambiguous_aliases.add((side, identity))
            seen_rules[identity] = counterpart
    a_pages = list(baseline.values()) if isinstance(baseline, dict) else list(baseline)
    b_pages = list(candidate.values()) if isinstance(candidate, dict) else list(candidate)
    pairs, used_b = [], set()
    for a in a_pages:
        a_key = page_key(a['url'])
        a_alias = _alias_key(a['url'], aliases, 'baseline')
        matches = []
        method = 'UNMATCHED'
        if a_alias:
            matches = [i for i, b in enumerate(b_pages) if i not in used_b
                       and (pair := _alias_key(b['url'], aliases, 'candidate')) and pair[0] == a_alias[0]]
            method = 'EXPLICIT_ALIAS'
        if not matches:
            matches = [i for i, b in enumerate(b_pages) if i not in used_b and page_key(b['url']) == a_key]
            method = 'EXACT_ROUTE'
        if not matches and a.get('heading'):
            matches = [i for i, b in enumerate(b_pages) if i not in used_b
                       and a['heading'] == b.get('heading')
                       and a.get('structure') == b.get('structure')]
            method = 'STRUCTURE_CANDIDATE'
        if len(matches) == 1:
            idx = matches[0]
            b = b_pages[idx]
            used_b.add(idx)
            corroborated = bool(a.get('heading') and a['heading'] == b.get('heading'))
            conflict = any((side, page_key(page['url'])) in ambiguous_aliases
                           or (side, urlsplit(page['url']).path) in ambiguous_aliases
                           for side, page in (('baseline', a), ('candidate', b)))
            trusted = not conflict and (method == 'EXPLICIT_ALIAS' or (method == 'EXACT_ROUTE' and corroborated))
            if conflict:
                method = 'AMBIGUOUS_ALIAS'
            match = dict(method=method, confidence='HIGH' if trusted else 'LOW',
                         approved=trusted, reason='EXPLICIT_ROUTE_MAPPING' if method == 'EXPLICIT_ALIAS'
                         else 'ROUTE_AND_HEADING' if trusted else 'REQUIRES_QA_MAPPING')
            pairs.append(dict(key=a_alias[1] if method == 'EXPLICIT_ALIAS' else a_key,
                              baseline=a, candidate=b, match=match))
        else:
            pairs.append(dict(key=a_key, baseline=a, candidate=None,
                              match=dict(method='AMBIGUOUS' if len(matches) > 1 else 'UNMATCHED',
                                         confidence='LOW', approved=False,
                                         reason='MATCH_AMBIGUOUS' if len(matches) > 1 else 'NOT_DISCOVERED')))
    for index, b in enumerate(b_pages):
        if index not in used_b:
            pairs.append(dict(key=page_key(b['url']), baseline=None, candidate=b,
                              match=dict(method='UNMATCHED', confidence='LOW', approved=False,
                                         reason='NOT_DISCOVERED')))
    return pairs
