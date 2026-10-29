"""Small, deterministic policies; observations never silently become a pass."""
from __future__ import annotations

import fnmatch
import re
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit

STATUSES = frozenset({'PASS', 'FAIL', 'REVIEW', 'SKIP', 'ERROR'})
_SENSITIVE = re.compile(r'password|passwd|token|secret|authorization|session|cookie|credential|api.?key', re.I)
_DANGEROUS = re.compile(
    r'(?i)(logout|log-out|signout|sign-out|delete|remove|withdraw|unsubscribe|'
    r'purchase|checkout|payment|subscribe|register|save|submit|send|upload|'
    r'삭제|탈퇴|결제|구매|신청|등록|저장|전송|발송|로그아웃|수정|업로드)')
_DOWNLOAD = re.compile(r'(?i)(download|다운로드|\.(?:pdf|zip|xlsx?|docx?|pptx?|hwp|exe|msi)(?:$|[?#]))')


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
    statuses = [c.get('status', 'ERROR') for c in checks]
    for status in ('FAIL', 'ERROR', 'REVIEW'):
        if status in statuses:
            return status
    if any(c.get('status') == 'SKIP' and c.get('required', True) for c in checks):
        return 'SKIP'
    return 'PASS' if 'PASS' in statuses else 'SKIP'


def dangerous_action(action):
    combined = unquote(' '.join(str(action.get(k, '')) for k in ('label', 'name', 'href', 'url', 'formAction')))
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


def route_allowed(url, options, seed_urls=()):
    def route_identity(value):
        parts = urlsplit(value)
        # /#/a and /#/b share a document path, but are different application routes.
        return (parts.path or '/') + ('#' + parts.fragment.split('?', 1)[0] if parts.fragment else '')

    try:
        identity = route_identity(url)
        paths = {route_identity(seed) for seed in seed_urls}
        for alias in options.get('route_aliases', []):
            paths.update(route_identity(alias[side]) for side in ('baseline', 'candidate') if alias.get(side))
        if identity in paths:
            return True
        return any(fnmatch.fnmatchcase(identity, pattern) for pattern in options.get('allowed_paths', []))
    except (ValueError, TypeError):
        return False


def classify_candidate(action, options, seed_urls=()):
    """Discovery is broad; execution requires an independent policy decision."""
    denied = dangerous_action(action)
    if denied:
        return False, denied
    if action.get('disabled') or not action.get('visible', True):
        return False, 'ELEMENT_NOT_ACTIONABLE'
    href = action.get('href')
    if href:
        if not host_allowed(href, options.get('allowed_hosts', [])):
            return False, 'HOST_NOT_APPROVED'
        if not route_allowed(href, options, seed_urls):
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
    critical = same_origin and resource_type in ('document', 'script', 'stylesheet')
    return dict(category='HTTP_5XX' if status >= 500 else 'HTTP_4XX',
                level='FAIL' if critical else 'REVIEW')
