"""Small, deterministic policies; observations never silently become a pass."""
from __future__ import annotations

import fnmatch
import re
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit

STATUSES = frozenset({'PASS', 'FAIL', 'DIFF', 'SKIP', 'BLOCKED', 'ERROR', 'REVIEW'})
_SENSITIVE = re.compile(r'password|passwd|token|secret|authorization|session|cookie|credential|api.?key', re.I)
_DANGEROUS = re.compile(
    r'(?i)(logout|log-out|signout|sign-out|delete|remove|withdraw|unsubscribe|'
    r'purchase|checkout|payment|subscribe|register|save|submit|send|upload|'
    r'삭제|탈퇴|결제|구매|신청|등록|저장|전송|발송|로그아웃|수정|업로드)')
# Test-account level: everything a shared QA account may do, except what would break the
# account for everyone (withdrawal, password change, logout) or spend money.
_HARD_DENY = re.compile(
    r'(?i)(회원\s*탈퇴|탈퇴|withdraw|deactivate-?account|close-?account|'
    r'결제|구매|주문\s*하기|payment|purchase|checkout|billing|'
    r'비밀번호|password|passwd|'
    r'로그아웃|log-?out|sign-?out|'
    r'회원\s*가입|sign-?up|register|join)')
SAFETY_LEVELS = ('strict', 'test_account')


def _level(options_or_level):
    if isinstance(options_or_level, dict):
        return options_or_level.get('safety_level', 'strict')
    return options_or_level or 'strict'


_DOWNLOAD = re.compile(r'(?i)(download|다운로드|\.(?:pdf|zip|xlsx?|docx?|pptx?|hwp|exe|msi)(?:$|[?#]))')
# Expanded discovery never treats account management or data/file endpoints as
# general page navigation. Explicit-path mode retains its existing policy.
_PRIVATE_ROUTE = re.compile(
    r'(?i)(?:^|[/._\s-])(?:auth|oauth|sso|login|log-in|signin|sign-in|signup|sign-up|account|member|membership|'
    r'mypage|my-page|my-info|profile|privacy|personal|password|passwd|credential|admin|settings|preferences)'
    r'(?:$|[/._\s-])|회원정보|개인정보|계정설정|마이페이지|비밀번호|로그인|회원가입')
_WRITE_ROUTE = re.compile(
    r'(?i)(?:^|[/._\s-])(?:edit|update|modify|create|write|insert|add|clear|reset|confirm|'
    r'approve|reject|accept|agree|enroll|apply|reserve|cancel|cart|order|toggle|enable|disable|'
    r'activate|deactivate|archive|destroy|set|lock|unlock)(?:$|[/._\s-])')
_NON_PAGE_FILE = re.compile(
    r'(?i)\.(?:json|xml|csv|tsv|ya?ml|pdf|zip|rar|7z|tar|gz|bz2|xz|xlsx?|docx?|pptx?|hwp|'
    r'exe|msi|dmg|apk|iso|bin|mp[34]|wav|ogg|webm|avi|mov|jpe?g|png|gif|webp|svg|ico|'
    r'woff2?|ttf|eot|css|js|map)(?:$|[?#/])')
_API_ROUTE = re.compile(r'(?i)(?:^|/)(?:api|graphql|rest)(?:$|[/._-])')
_READ_ACTIONS = frozenset({'list', 'view', 'read', 'search', 'detail', 'get', 'index', 'select'})
_CONTROL_QUERY_KEYS = frozenset({
    'action', 'act', 'op', 'operation', 'cmd', 'command', 'method', 'mode', 'do',
    'actiontype', 'actionname', 'operationtype', 'operationname', 'commandtype', 'commandname',
    'methodtype', 'methodname', 'event', 'eventtype', 'eventname', 'task', 'tasktype', 'taskname',
    'function', 'functionname', 'fn', 'dispatch', 'handler',
})
_CONTENT_QUERY_KEYS = frozenset({'q', 'query', 'search', 'keyword', 'keywords', 'term', 'text',
                                'title', 'description', 'message', 'content'})
_TARGET_QUERY_KEYS = frozenset({'url', 'uri', 'redirect', 'redirecturl', 'redirecturi', 'returnurl',
                               'returnuri', 'returnto', 'next', 'target', 'destination', 'continue', 'callback'})


def sanitize_url(value):
    """Keep useful route evidence but never embed URL credentials or secret values."""
    try:
        p = urlsplit(str(value or ''))
        host = p.hostname or ''
        if ':' in host:
            host = '[' + host + ']'
        if p.port:
            host += ':' + str(p.port)
        query = urlencode([(k, '[REDACTED]' if _SENSITIVE.search(k) else v)
                           for k, v in parse_qsl(p.query, keep_blank_values=True)])
        fragment = p.fragment
        if '?' in fragment:
            route, _, raw = fragment.partition('?')
            fragment = route + '?' + urlencode([(k, '[REDACTED]' if _SENSITIVE.search(k) else v)
                                                for k, v in parse_qsl(raw, keep_blank_values=True)])
        elif '=' in fragment and not fragment.startswith('/'):
            fragment = urlencode([(k, '[REDACTED]' if _SENSITIVE.search(k) else v)
                                  for k, v in parse_qsl(fragment, keep_blank_values=True)])
        return urlunsplit((p.scheme, host, p.path, query, fragment))[:2000]
    except (ValueError, TypeError):
        return '[INVALID_URL]'


def sanitize_message(value, limit=500):
    text = str(value or '')
    text = re.sub(r'(?i)(password|passwd|token|secret|authorization|cookie|sessionid)\s*[=:]\s*[^\s,;]+', r'\1=[REDACTED]', text)
    text = re.sub(r'(?i)bearer\s+\S+', 'Bearer [REDACTED]', text)
    text = re.sub(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}', '[EMAIL]', text)
    return text[:limit]


def check(check_id, status, reason_code, expected=None, actual=None, *,
          scenario_id='engine', step_id='observe', evidence=None, required=True):
    if status not in STATUSES:
        raise ValueError('Unknown check status')
    return dict(check_id=check_id, scenario_id=scenario_id, step_id=step_id,
                status=status, reason_code=reason_code, expected=expected,
                actual=actual, evidence=evidence or [], required=required)


def aggregate_status(checks):
    # Informational observations are evidence, never a verdict (lenient observation mode).
    checks = [c for c in checks if not c.get('informational')] or checks
    statuses = [c.get('status', 'ERROR') for c in checks]
    for status in ('FAIL', 'ERROR'):
        if status in statuses:
            return status
    if any(c.get('status') == 'BLOCKED' and c.get('required', True) for c in checks):
        return 'BLOCKED'
    for status in ('REVIEW', 'DIFF'):
        if status in statuses:
            return status
    if any(c.get('status') == 'SKIP' and c.get('required', True) for c in checks):
        return 'SKIP'
    return 'PASS' if 'PASS' in statuses else 'SKIP'


def unexecuted_status(reason):
    """A budget/prerequisite prevents execution; a policy intentionally excludes it."""
    reason = str(reason or '')
    if reason == 'SAMPLE_LIMIT_REACHED':
        return 'SKIP'  # intentional sampling of same-shape records, not a missed check
    if (reason == 'CANCELLED' or 'LIMIT' in reason or 'PREREQUISITE' in reason
            or reason in {'MANUAL_AUTH_REQUIRED', 'LOGIN_REQUIRED', 'SESSION_EXPIRED',
                          'ROLE_UNAVAILABLE', 'INSUFFICIENT_DATA', 'NO_COMPARABLE_PIXELS',
                          'LOGIN_FAILED', 'LOGIN_CREDENTIALS_MISSING', 'LOGIN_HOST_NOT_APPROVED', 'LOGIN_FORM_NOT_FOUND',
                          'MATCH_SIDE_UNAVAILABLE', 'PAGE_NOT_READY', 'PREVIOUS_STATE_RESET_FAILED'}):
        return 'BLOCKED'
    return 'SKIP'


def dangerous_action(action, level='strict'):
    combined = unquote(' '.join(str(action.get(k, '')) for k in ('label', 'name', 'href', 'url', 'formAction')))
    if _level(level) == 'test_account':
        # Writes are allowed with a test account; only account-breaking / paid actions stay denied.
        if _HARD_DENY.search(combined):
            return 'ACCOUNT_BREAKING_ACTION'
        if _DOWNLOAD.search(combined) or action.get('download'):
            return 'DOWNLOAD_NOT_APPROVED'
        return None
    if _DANGEROUS.search(combined):
        return 'MUTATING_ACTION'
    if _DOWNLOAD.search(combined) or action.get('download'):
        return 'DOWNLOAD_NOT_APPROVED'
    if action.get('type', '').lower() in ('submit', 'image'):
        return 'FORM_SUBMIT_NOT_APPROVED'
    return None


def host_allowed(url, allowed_hosts):
    try:
        p = urlsplit(url)
        if p.scheme not in ('http', 'https') or p.username or p.password or not p.hostname:
            return False
        # No wildcard expansion: an explicit hostname does not grant sibling hosts.
        values = {str(h).lower().rstrip('.') for h in allowed_hosts}
        return p.hostname.lower().rstrip('.') in values or p.netloc.lower() in values
    except (ValueError, TypeError):
        return False


def resource_allowed(url, resource_type, method, navigation, hosts):
    """Grant only passive resource loads; this is not a navigation/API allowlist.

    Host-only entries permit default HTTP(S) ports. Other ports need an explicit
    host:port entry. A redirect is checked again using its own request URL/type.
    """
    if navigation or resource_type not in ('script', 'stylesheet', 'image', 'font', 'media'):
        return False
    if method not in ('GET', 'HEAD'):
        return False
    try:
        parts = urlsplit(url)
        if parts.scheme not in ('http', 'https') or not parts.hostname or parts.username or parts.password:
            return False
        default_port = 443 if parts.scheme == 'https' else 80
        requested_port = parts.port if parts.port is not None else default_port
        for host in hosts:
            if not isinstance(host, str) or '*' in host or any(char.isspace() for char in host):
                continue
            approved = urlsplit('https://' + host.lower())
            if (approved.path or approved.query or approved.fragment or approved.username or approved.password
                    or not approved.hostname or approved.netloc != host.lower()):
                continue
            if parts.hostname.lower().rstrip('.') != approved.hostname.lower().rstrip('.'):
                continue
            if requested_port == (approved.port if approved.port is not None else default_port):
                return True
    except (ValueError, TypeError):
        return False
    return False


def _origin_identity(url):
    try:
        parts = urlsplit(url)
        if (parts.scheme not in ('http', 'https') or not parts.hostname or parts.username or parts.password
                or any(char.isspace() for char in url) or '\\' in url):
            return None
        return parts.scheme.lower(), parts.hostname.lower(), parts.port if parts.port is not None else (443 if parts.scheme == 'https' else 80)
    except (ValueError, TypeError):
        return None


def _decode_query_policy(value):
    for _ in range(4):
        decoded = unquote(value)
        if decoded == value:
            return value
        value = decoded
    if unquote(value) != value:
        raise ValueError('Query encoding depth is not approved.')
    return value


def _readonly_query_reason(query, depth=0):
    if depth > 4:
        return 'NESTED_QUERY_NOT_APPROVED'
    try:
        for raw_key, raw_value in parse_qsl(query, keep_blank_values=True):
            key = _decode_query_policy(raw_key)
            normalized_key = re.sub(r'[^a-z0-9]', '', key.lower())
            if normalized_key in _CONTENT_QUERY_KEYS:
                # A search for "reset" is not an instruction to reset anything.
                continue
            value = _decode_query_policy(raw_value)
            if normalized_key in _CONTROL_QUERY_KEYS and value.strip().lower() not in _READ_ACTIONS:
                return 'UNKNOWN_ACTION_ENDPOINT'
            readable_key = re.sub(r'([a-z])([A-Z])', r'\1-\2', key)
            if _PRIVATE_ROUTE.search(readable_key) or _WRITE_ROUTE.search(readable_key):
                return 'MUTATING_OR_PRIVATE_QUERY_NOT_APPROVED'
            parts = urlsplit(value)
            if normalized_key in _TARGET_QUERY_KEYS:
                readable_path = re.sub(r'([a-z])([A-Z])', r'\1-\2', parts.path + '/' + parts.fragment.split('?', 1)[0])
                if dangerous_action({'url': value}) or _PRIVATE_ROUTE.search(readable_path) or _WRITE_ROUTE.search(readable_path):
                    return 'MUTATING_OR_PRIVATE_QUERY_NOT_APPROVED'
            nested_queries = [item for item in (parts.query, parts.fragment.partition('?')[2]) if item]
            if not nested_queries and '=' in value:
                nested_queries = [value]
            for nested in nested_queries:
                denied = _readonly_query_reason(nested, depth + 1)
                if denied:
                    return denied
    except (ValueError, TypeError):
        return 'ENCODED_QUERY_NOT_APPROVED'
    return None


def readonly_navigation_reason(action, level='strict'):
    """Return a conservative exclusion reason, not proof that a GET is safe."""
    level = _level(level)
    denied = dangerous_action(action, level)
    if denied:
        return denied
    url = action.get('href') or action.get('url') or ''
    if not _origin_identity(url):
        return 'INVALID_NAVIGATION_URL'
    denied = dangerous_action({**action, 'href': unquote(unquote(url))}, level)
    if denied:
        return denied
    if action.get('formAction') or action.get('tag', 'a').lower() not in ('a', 'area'):
        return 'NAVIGATION_LINK_REQUIRED'
    if action.get('method', 'GET').upper() not in ('GET', 'HEAD'):
        return 'WRITE_REQUEST_NOT_APPROVED'
    parts = urlsplit(url)
    # Decode for policy inspection only: the queued URL retains its exact state.
    path = unquote(unquote((parts.path or '/') + '/' + parts.fragment.split('?', 1)[0]))
    readable_path = re.sub(r'([a-z])([A-Z])', r'\1-\2', path)
    label = ' '.join(str(action.get(key) or '') for key in ('label', 'name'))
    if level == 'test_account':
        # Mypage/settings/write routes are in scope for a test account; API/file links still are not.
        if _HARD_DENY.search(readable_path + ' ' + label):
            return 'ACCOUNT_BREAKING_ROUTE'
    else:
        if _PRIVATE_ROUTE.search(readable_path + ' ' + label):
            return 'ACCOUNT_OR_PRIVATE_ROUTE_NOT_APPROVED'
        if _WRITE_ROUTE.search(readable_path + ' ' + label):
            return 'MUTATING_ROUTE_NOT_APPROVED'
    if _NON_PAGE_FILE.search(unquote(unquote(url))):
        return 'NON_PAGE_RESOURCE_NOT_APPROVED'
    if _API_ROUTE.search(readable_path):
        return 'API_NAVIGATION_NOT_APPROVED'
    if level == 'test_account':
        return None
    queries = [parts.query, parts.fragment.partition('?')[2]]
    for query in queries:
        denied = _readonly_query_reason(query)
        if denied:
            return denied
    return None


def _selected_origin(seed_urls, origin_url):
    origins = {_origin_identity(seed) for seed in seed_urls} - {None}
    if origin_url:
        selected = _origin_identity(origin_url)
        return selected if selected in origins else None
    return next(iter(origins)) if len(origins) == 1 else None


def route_allowed(url, options, seed_urls=(), *, origin_url=None):
    def route_identity(value):
        parts = urlsplit(value)
        # /#/a and /#/b share a document path, but are different application routes.
        return (parts.path or '/') + ('#' + parts.fragment.split('?', 1)[0] if parts.fragment else '')

    try:
        if options.get('crawl_scope', 'approved_paths') == 'same_origin_readonly':
            origin = _selected_origin(seed_urls, origin_url or options.get('_environment_seed'))
            return bool(origin and _origin_identity(url) == origin and
                        not readonly_navigation_reason({'url': url}, _level(options)))
        identity = route_identity(url)
        if identity in options.get('_mirror_paths', ()):
            return True
        paths = {route_identity(seed) for seed in seed_urls}
        for alias in options.get('route_aliases', []):
            paths.update(route_identity(alias[side]) for side in ('baseline', 'candidate') if alias.get(side))
        if identity in paths:
            return True
        return any(fnmatch.fnmatchcase(identity, pattern) for pattern in options.get('allowed_paths', []))
    except (ValueError, TypeError):
        return False


def classify_candidate(action, options, seed_urls=(), *, origin_url=None):
    """Discovery is broad; execution requires an independent policy decision."""
    denied = dangerous_action(action, _level(options))
    if denied:
        return False, denied
    if action.get('disabled') or not action.get('visible', True):
        return False, 'ELEMENT_NOT_ACTIONABLE'
    href = action.get('href')
    if href:
        if not host_allowed(href, options.get('allowed_hosts', [])):
            return False, 'HOST_NOT_APPROVED'
        selected_origin_url = origin_url or options.get('_environment_seed') or action.get('pageUrl')
        if options.get('crawl_scope', 'approved_paths') == 'same_origin_readonly':
            denied = readonly_navigation_reason(action, _level(options))
            if denied:
                return False, denied
            origin = _selected_origin(seed_urls, selected_origin_url)
            if not origin or _origin_identity(href) != origin:
                return False, 'ORIGIN_NOT_APPROVED'
        if not route_allowed(href, options, seed_urls, origin_url=selected_origin_url):
            return False, 'ROUTE_NOT_APPROVED'
        return True, 'APPROVED_NAVIGATION'
    for rule in options.get('safe_actions', []):
        if rule.get('selector') == action.get('selector') and rule.get('kind', 'click') == 'click':
            if rule.get('url_pattern') and not fnmatch.fnmatchcase(action.get('pageUrl', ''), rule['url_pattern']):
                continue
            return True, 'APPROVED_UI_ACTION'
    return False, 'UNKNOWN_ACTION'


def http_observation(status, resource_type, same_origin):
    """No blanket 400 suppression; optional/API errors remain reviewable evidence."""
    if status < 400:
        return None
    if same_origin and resource_type == 'document' and status in (401, 403):
        return dict(category='LOGIN_REQUIRED' if status == 401 else 'ACCESS_DENIED', level='BLOCKED')
    critical = same_origin and resource_type in ('document', 'script', 'stylesheet')
    return dict(category='HTTP_5XX' if status >= 500 else 'HTTP_4XX',
                level='FAIL' if critical and status not in (400, 401, 403) else 'REVIEW')
