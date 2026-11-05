"""Conservative page identity and explicit, reviewable cross-environment matches."""
from __future__ import annotations

from collections import Counter, defaultdict
from hashlib import sha256
import re
import unicodedata
from urllib.parse import parse_qsl, unquote, urlsplit, urlunsplit

from .policy import sanitize_message, sanitize_url, _SENSITIVE as SENSITIVE_URL_KEY


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


_ROUTE_EXTENSION = re.compile(r'\.(?:do|html?|jsp|php|aspx?|action)$', re.I)
_HOME_ALIASES = frozenset({'', 'index', 'main', 'home', 'index.html', 'main.do', 'index.do'})


def equivalent_route_key(url):
    """Return a conservative application-route identity shared by SPA and legacy URLs.

    The same product is often served as ``/notice``, ``/#/notice`` and
    ``/notice.do`` depending on the environment generation, and the home page as
    ``/``, ``/#/`` or ``/main``. This key folds only those well-known shapes:
    hash-route prefix, a server-side page extension, a trailing slash and the
    home aliases. Query order, instance IDs and every other path segment stay
    exact, so ``/notice?id=1`` and ``/notice?id=2`` remain different pages.
    """
    p = urlsplit(url)
    path, query = p.path or '/', p.query
    hash_route, _, hash_query = p.fragment.partition('?')
    if hash_route.startswith('/'):
        # /#/notice?x=1 is an application route rendered by the document at /.
        path, query = hash_route, '&'.join(item for item in (query, hash_query) if item)
    elif p.fragment:
        # A plain anchor (#top) is not a route; it never changes identity.
        pass
    segments = [unquote(item) for item in path.split('/') if item]
    if segments:
        segments[-1] = _ROUTE_EXTENSION.sub('', segments[-1])
    if len(segments) == 1 and segments[0].casefold() in _HOME_ALIASES:
        segments = []
    route = '/' + '/'.join(segment.casefold() for segment in segments)
    return route + ('?' + query if query else '')


def instance_template(url):
    """Route with instance identifiers wildcarded: ``/notice/view?seq=123`` → ``/notice/view?seq=*``.

    Used to sample "the same page with another record" (notice detail, prev/next post,
    pagination) instead of walking every record. Path segments that are numbers/UUIDs,
    instance-like query keys (id, idx, no, seq, ...Id) and purely numeric query values
    are wildcarded; everything else keeps its exact value.
    """
    p = urlsplit(url)
    hash_route, _, hash_query = p.fragment.partition('?')

    def path_shape(path):
        return '/'.join('*' if _PATH_INSTANCE.fullmatch(unquote(part)) else part for part in path.split('/'))

    def query_shape(query):
        pairs = parse_qsl(query, keep_blank_values=True)
        return '&'.join(f"{key}={'*' if _INSTANCE_KEY.search(key) or value.isdigit() else value}" for key, value in sorted(pairs))

    shape = path_shape(p.path or '/')
    if p.query:
        shape += '?' + query_shape(p.query)
    if hash_route.startswith('/'):
        shape += '#' + path_shape(hash_route) + ('?' + query_shape(hash_query) if hash_query else '')
    return shape


def _hash_only_difference(left, right):
    """True when the two URLs differ only by a ``#/`` SPA prefix or home alias."""
    def shape(value):
        p = urlsplit(value)
        if p.fragment.startswith('/'):
            return 'hash', (p.path or '/').rstrip('/') or '/'
        return 'path', None
    (kind_a, shell_a), (kind_b, shell_b) = shape(left), shape(right)
    if kind_a == kind_b == 'hash':
        return shell_a == shell_b
    return kind_a != kind_b


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


_GENERIC_LABELS = frozenset({'start-page', 'home', 'main', 'menu', '홈', '메인', '메뉴', '처음', '바로가기'})
_INSTANCE_KEY = re.compile(r'(?:^id$|^idx$|^no$|^seq$|^number$|(?:id|idx|seq|no)$)', re.I)
_PATH_INSTANCE = re.compile(r'^(?:\d+|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$', re.I)


def _label(value):
    return ' '.join(unicodedata.normalize('NFKC', sanitize_message(value, 160)).casefold().split())[:160]


def public_url(value):
    """Preserve exact ordinary identities, but redact secrets in suggestions."""
    try:
        parsed = urlsplit(value)
        queries = [parsed.query]
        if '?' in parsed.fragment:
            queries.append(parsed.fragment.partition('?')[2])
        elif '=' in parsed.fragment and not parsed.fragment.startswith('/'):
            queries.append(parsed.fragment)
        sensitive = parsed.username or parsed.password or any(
            SENSITIVE_URL_KEY.search(key) for query in queries for key, _ in parse_qsl(query, keep_blank_values=True))
        return sanitize_url(value) if sensitive else value
    except (ValueError, TypeError):
        return '[INVALID_URL]'


_public_url = public_url


def _evidence(kind, left, right, detail):
    return dict(kind=kind, baseline=left, candidate=right, detail=detail)


def _features(page):
    signature = page.get('pageSignature') or {}
    trail = [_label(item.get('label', '') if isinstance(item, dict) else item)
             for item in page.get('navigationTrail', [])]
    # A fallback URL is an identity, not an independently observed menu label.
    trail = [item for item in trail if item and item not in _GENERIC_LABELS
             and not item.startswith(('/', '#', 'http:', 'https:'))]
    headings = {_label(item.get('text')) for item in signature.get('headings', []) if isinstance(item, dict)}
    headings.discard('')
    primary = {_label(item.get('text')) for item in signature.get('headings', [])
               if isinstance(item, dict) and _label(item.get('tag')) == 'h1'} - {''} - _GENERIC_LABELS
    fields = sorted((_label(item.get('type')), _label(item.get('name')), _label(item.get('label')))
                    for item in signature.get('formFields', []) if isinstance(item, dict)
                    and _label(item.get('type')) not in ('hidden', 'password'))
    actions = {_label(item) for item in signature.get('actionLabels', []) if _label(item)}
    nav = {_label(item) for item in signature.get('navLabels', []) if _label(item)}
    return dict(trail=trail, headings=headings, primary=primary, fields=fields, actions=actions, nav=nav,
                landmarks=signature.get('landmarks') or {}, structure=page.get('structure') or '')


def _instances(url):
    parsed = urlsplit(url)
    hash_path, _, hash_query = parsed.fragment.partition('?')
    values = [(_label(key), value) for key, value in parse_qsl(parsed.query, keep_blank_values=True)
              if _INSTANCE_KEY.search(key)]
    values += [(_label(key), value) for key, value in parse_qsl(hash_query, keep_blank_values=True)
               if _INSTANCE_KEY.search(key)]
    for path in (parsed.path, hash_path):
        values.extend(('path-instance', part) for part in unquote(path).split('/') if _PATH_INSTANCE.fullmatch(part))
    return sorted(values)


def _semantic(left, right):
    """Return inspectable evidence, never a numerical probability or approval.

    Shared global navigation / landmarks alone cannot identify a function.
    Meaningful instance IDs remain distinct even when a template is identical.
    """
    a, b = _features(left), _features(right)
    evidence, conflicts = [], []
    same_trail = bool(a['trail'] and b['trail'] and a['trail'][-1] == b['trail'][-1])
    if same_trail and min(len(a['trail']), len(b['trail'])) >= 2:
        same_trail = a['trail'][-2:] == b['trail'][-2:]
    if a['trail'] and b['trail']:
        evidence.append(_evidence('NAVIGATION_TRAIL' if same_trail else 'NAVIGATION_CONFLICT',
                                  a['trail'], b['trail'], 'Observed menu trail labels; URL text is excluded.'))
        if not same_trail:
            conflicts.append('FUNCTION_TRAIL_CONFLICT')
    same_fields = bool(a['fields'] and a['fields'] == b['fields']
                       and any(name or label for _, name, label in a['fields']))
    if a['fields'] and b['fields']:
        evidence.append(_evidence('FORM_FIELDS' if same_fields else 'FORM_FIELDS_CONFLICT',
                                  a['fields'], b['fields'], 'Field type/name/label only; input values are never read.'))
        if a['fields'] != b['fields']:
            conflicts.append('FUNCTION_FIELDS_CONFLICT')
    shared_headings = sorted(a['headings'] & b['headings'] - _GENERIC_LABELS)
    if shared_headings:
        evidence.append(_evidence('HEADINGS', shared_headings, shared_headings, 'Shared page heading labels.'))
    if a['primary'] and b['primary'] and not a['primary'] & b['primary']:
        conflicts.append('FUNCTION_HEADING_CONFLICT')
        evidence.append(_evidence('HEADING_CONFLICT', sorted(a['primary']), sorted(b['primary']),
                                  'Different primary function headings require a manual mapping.'))
    same_structure = bool((a['landmarks'] and a['landmarks'] == b['landmarks'])
                          or (a['structure'] and a['structure'] == b['structure']))
    if same_structure:
        evidence.append(_evidence('LANDMARK_STRUCTURE', a['landmarks'] or a['structure'],
                                  b['landmarks'] or b['structure'], 'Supporting structure only; not functional identity.'))
    shared_actions = sorted((a['actions'] & b['actions']) - (a['nav'] | b['nav']) - _GENERIC_LABELS)
    if shared_actions:
        evidence.append(_evidence('ACTION_LABELS', shared_actions, shared_actions, 'Shared non-navigation action labels.'))
    shared_nav = sorted(a['nav'] & b['nav'])
    if shared_nav:
        evidence.append(_evidence('GLOBAL_NAVIGATION', shared_nav, shared_nav, 'Global navigation is supporting evidence only.'))
    legacy_heading = bool(left.get('heading') and left['heading'] == right.get('heading'))
    legacy_structure = legacy_heading and bool(a['structure'] and a['structure'] == b['structure'])
    if legacy_heading:
        evidence.append(_evidence('PRIMARY_HEADING', sanitize_message(left['heading'], 160),
                                  sanitize_message(right['heading'], 160), 'Same primary heading; requires QA mapping.'))
    function_evidence = (same_trail and (same_structure or same_fields or shared_headings or shared_actions)) \
        or (same_fields and shared_headings)
    # Template-only similarities are listed for inspection but never forced into a pair.
    potential = function_evidence or legacy_structure or same_trail or same_fields or shared_headings
    if not potential:
        return None
    left_ids, right_ids = _instances(left['url']), _instances(right['url'])
    if (left_ids or right_ids) and left_ids != right_ids:
        conflicts.append('DIFFERENT_INSTANCE_ID')
        evidence.append(_evidence('INSTANCE_ID_CONFLICT', page_key(_public_url(left['url'])),
                                  page_key(_public_url(right['url'])), 'Different detail identifiers are not merged.'))
    method = 'SEMANTIC_CANDIDATE' if function_evidence else 'STRUCTURE_CANDIDATE'
    return dict(method=method, approved=False, eligible=not conflicts and bool(function_evidence or legacy_structure),
                reason=conflicts[0] if conflicts else 'REQUIRES_QA_MAPPING', evidence=evidence)


def match_pages(baseline, candidate, aliases=None, *, start_pair=None, route_equivalence=True):
    """Reserve explicit identities first, then propose mutual unique function matches.

    Selected starts apply to the two requested URLs only, including their query
    and fragment. Every priority uses the full bipartite candidate graph, so an
    earlier ambiguous page cannot steal another page's exact or explicit match.
    Semantic evidence never sets approved=True and collisions remain unpaired.
    With ``route_equivalence`` (default) the well-known SPA/legacy URL shapes
    (``/``, ``/#/``, ``/main``, ``.do``) are paired as EQUIVALENT_ROUTE: approved
    when the heading corroborates or when only the ``#/`` prefix differs and no
    semantic conflict exists; otherwise listed as a reviewable candidate only.
    """
    aliases, start_pair = aliases or [], start_pair or {}
    a_pages = list(baseline.values()) if isinstance(baseline, dict) else list(baseline)
    b_pages = list(candidate.values()) if isinstance(candidate, dict) else list(candidate)
    selected, used_b, held_a, held_b, suggestions = {}, set(), set(), set(), {}
    ambiguous_aliases = set()
    for side, other in (('baseline', 'candidate'), ('candidate', 'baseline')):
        targets = defaultdict(set)
        for rule in aliases:
            if rule.get(side) and rule.get(other):
                targets[page_key(rule[side])].add(page_key(rule[other]))
        ambiguous_aliases.update((side, key) for key, values in targets.items() if len(values) > 1)

    def alias_conflict(side, page):
        return any((side, key) in ambiguous_aliases for key in (page_key(page['url']), urlsplit(page['url']).path))

    def add(i, j, method, *, approved=False, reason='REQUIRES_QA_MAPPING', evidence=None, eligible=True, key=None):
        # The first item has the highest priority for this pair of records.
        suggestions.setdefault((i, j), dict(method=method, approved=approved, reason=reason,
                                            evidence=evidence or [], eligible=eligible, key=key))

    def reserve(edges):
        active = [(i, j) for i, j in sorted(set(edges)) if i not in selected and j not in used_b
                  and i not in held_a and j not in held_b and suggestions[i, j]['eligible']]
        left_counts, right_counts = Counter(i for i, _ in active), Counter(j for _, j in active)
        unique = [(i, j) for i, j in active if left_counts[i] == right_counts[j] == 1]
        for i, j in unique:
            selected[i] = j
            used_b.add(j)
        # A lower-priority similarity must not resolve a higher-priority collision.
        held_a.update(i for i, _ in active if i not in selected)
        held_b.update(j for _, j in active if j not in used_b)

    explicit = []
    for i, a in enumerate(a_pages):
        for j, b in enumerate(b_pages):
            for rule_index, original_rule in enumerate(aliases):
                rule = dict(original_rule, page_class=original_rule.get('page_class', 'alias-' + str(rule_index)))
                ak, bk = _alias_key(a['url'], [rule], 'baseline'), _alias_key(b['url'], [rule], 'candidate')
                if not ak or not bk or ak[0] != bk[0]:
                    continue
                conflict = alias_conflict('baseline', a) or alias_conflict('candidate', b)
                add(i, j, 'AMBIGUOUS_ALIAS' if conflict else 'EXPLICIT_ALIAS', approved=not conflict,
                    reason='MATCH_AMBIGUOUS' if conflict else 'EXPLICIT_ROUTE_MAPPING', eligible=not conflict,
                    key=ak[1], evidence=[_evidence('EXPLICIT_ALIAS', page_key(_public_url(a['url'])),
                                                page_key(_public_url(b['url'])), 'Configured route alias.')])
                explicit.append((i, j))
                if conflict:
                    held_a.add(i)
                    held_b.add(j)
    reserve(explicit)
    if start_pair.get('baseline') and start_pair.get('candidate'):
        seed_a, seed_b = normalize_url(start_pair['baseline']), normalize_url(start_pair['candidate'])
        starts = []
        for i, a in enumerate(a_pages):
            for j, b in enumerate(b_pages):
                if normalize_url(a['url']) == seed_a and normalize_url(b['url']) == seed_b:
                    add(i, j, 'SELECTED_START_PAGES', approved=True, reason='START_URLS_DECLARED_EQUIVALENT',
                        key='start-page', evidence=[_evidence('SELECTED_START_PAGES', _public_url(seed_a), _public_url(seed_b),
                                                           'Only these two requested start URLs were declared equivalent.')])
                    starts.append((i, j))
        reserve(starts)
    exact = []
    for i, a in enumerate(a_pages):
        for j, b in enumerate(b_pages):
            if page_key(a['url']) == page_key(b['url']):
                semantic = _semantic(a, b)
                corroborated = bool(a.get('heading') and a['heading'] == b.get('heading'))
                trusted = corroborated and (not semantic or semantic['eligible'])
                add(i, j, 'EXACT_ROUTE', approved=trusted,
                    reason='ROUTE_AND_HEADING' if trusted else 'REQUIRES_QA_MAPPING',
                    evidence=[_evidence('EXACT_ROUTE', page_key(_public_url(a['url'])), page_key(_public_url(b['url'])),
                                        'Exact path, query sequence and fragment identity.')] + (semantic or {}).get('evidence', []))
                exact.append((i, j))
    reserve(exact)
    if route_equivalence:
        equivalent = []
        for i, a in enumerate(a_pages):
            for j, b in enumerate(b_pages):
                if (i, j) in suggestions or equivalent_route_key(a['url']) != equivalent_route_key(b['url']):
                    continue
                semantic = _semantic(a, b)
                conflicts = bool(semantic) and not semantic['eligible']
                corroborated = bool(a.get('heading') and a['heading'] == b.get('heading')) or bool(semantic and semantic['eligible'])
                hash_only = _hash_only_difference(a['url'], b['url'])
                trusted = not conflicts and (corroborated or hash_only)
                add(i, j, 'EQUIVALENT_ROUTE', approved=trusted,
                    reason='ROUTE_EQUIVALENT' if trusted else 'EQUIVALENT_ROUTE_CONFLICT' if conflicts else 'REQUIRES_QA_MAPPING',
                    eligible=trusted,
                    evidence=[_evidence('EQUIVALENT_ROUTE', page_key(_public_url(a['url'])), page_key(_public_url(b['url'])),
                                        'Same application route after folding #/ prefix, page extension, trailing slash and home alias.')]
                    + (semantic or {}).get('evidence', []))
                equivalent.append((i, j))
        reserve(equivalent)
    semantic_edges = []
    for i, a in enumerate(a_pages):
        for j, b in enumerate(b_pages):
            if (i, j) in suggestions:
                continue
            semantic = _semantic(a, b)
            if semantic:
                add(i, j, **semantic)
                semantic_edges.append((i, j))
    reserve(semantic_edges)

    def candidates_for(index, side):
        result = []
        for (i, j), item in suggestions.items():
            if (i if side == 'baseline' else j) != index:
                continue
            a, b = a_pages[i], b_pages[j]
            other = b if side == 'baseline' else a
            public_a, public_b = _public_url(a['url']), _public_url(b['url'])
            clean = public_a == a['url'] and public_b == b['url']
            available = (i not in selected or selected[i] == j) and (j not in used_b or selected.get(i) == j)
            alias = dict(baseline=page_key(public_a), candidate=page_key(public_b),
                         page_class='mapped-' + sha256((a['url'] + '\n' + b['url']).encode()).hexdigest()[:10]) if clean else None
            result.append(dict(url=_public_url(other['url']), key=page_key(_public_url(other['url'])),
                               method=item['method'], reason=item['reason'], evidence=item['evidence'],
                               available=available, eligible=item['eligible'], alias=alias))
        return sorted(result, key=lambda item: (not item['available'], item['key'], item['url']))

    def match_for(i=None, j=None):
        if i is not None and j is not None:
            item = suggestions[i, j]
            match = {key: item[key] for key in ('method', 'approved', 'reason', 'evidence')}
            match['confidence'] = 'HIGH' if item['approved'] else 'LOW'
        else:
            match = dict(method='UNMATCHED', approved=False, reason='NOT_DISCOVERED', evidence=[], confidence='LOW')
        choices = candidates_for(i, 'baseline') if i is not None else candidates_for(j, 'candidate')
        if (i is None or j is None) and choices:
            match.update(method='AMBIGUOUS', reason='MATCH_AMBIGUOUS', evidence=[
                _evidence('UNRESOLVED_CANDIDATES', len(choices), len(choices),
                          'Conflicting, insufficient, already reserved or non-unique evidence; no pair was forced.')])
            if any(item['method'] == 'AMBIGUOUS_ALIAS' for item in choices):
                match['method'] = 'AMBIGUOUS_ALIAS'
        match.update(baselineKey=page_key(_public_url(a_pages[i]['url'])) if i is not None else None,
                     candidateKey=page_key(_public_url(b_pages[j]['url'])) if j is not None else None,
                     candidates=choices)
        return match

    pairs = []
    for i, a in enumerate(a_pages):
        j = selected.get(i)
        item = suggestions[i, j] if j is not None else {}
        pairs.append(dict(key=item.get('key') or page_key(a['url']), baseline=a,
                          candidate=b_pages[j] if j is not None else None, match=match_for(i, j)))
    pairs.extend(dict(key=page_key(b['url']), baseline=None, candidate=b, match=match_for(None, j))
                 for j, b in enumerate(b_pages) if j not in used_b)
    return pairs
