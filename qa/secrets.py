"""Test-account credentials stay on the operator's machine.

Credentials are read only inside the engine process at login time, from
environment variables or a local secrets file that is ignored by git. They are
never accepted through the HTTP API, never written to ``runs/`` reports, never
logged and never echoed back to the UI. A missing or malformed source yields
``None`` so the run records ``LOGIN_CREDENTIALS_MISSING`` instead of guessing.

Resolution order for side ``a``/``b`` and ``accountKey`` (default ``default``):

1. ``QA_LOGIN_A_ID`` / ``QA_LOGIN_A_PW`` (side-specific environment variables)
2. The environment's own login ID/PW registered in 프로젝트 설정 (``project_ref``),
   decrypted server-side by ``qa.projects_db`` — only when the run selected that environment
3. ``QA_LOGIN_ID`` / ``QA_LOGIN_PW`` (shared environment variables)
4. ``QA_SECRETS_FILE`` or ``./secrets/accounts.json``::

       {"accounts": {"default": {"id": "tester", "pw": "..."},
                     "default.b": {"id": "tester-b", "pw": "..."}}}

   ``<accountKey>.<side>`` wins over ``<accountKey>``.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

DEFAULT_SECRETS_FILE = Path('secrets') / 'accounts.json'
PROJECT_ROOT = Path(__file__).resolve().parents[1]
_MAX_LENGTH = 200


class Credentials:
    """Opaque holder: repr/str never reveal the secret values."""

    __slots__ = ('username', 'password', 'source', 'login_url')

    def __init__(self, username, password, source, login_url=None):
        self.username, self.password, self.source, self.login_url = username, password, source, login_url

    def __repr__(self):
        return f'Credentials(source={self.source!r}, username=[REDACTED], password=[REDACTED])'

    __str__ = __repr__


def _clean(value):
    if not isinstance(value, str):
        return None
    value = value.strip('\r\n')
    return value if 0 < len(value) <= _MAX_LENGTH else None


def _from_environment(side, environ, prefixes=None):
    for prefix in prefixes or (f'QA_LOGIN_{side.upper()}_', 'QA_LOGIN_'):
        username, password = _clean(environ.get(prefix + 'ID')), _clean(environ.get(prefix + 'PW'))
        if username and password:
            return Credentials(username, password, 'environment:' + prefix.rstrip('_'))
    return None


def _from_file(side, account_key, environ, root):
    raw_path = environ.get('QA_SECRETS_FILE')
    path = Path(raw_path) if raw_path else Path(root) / DEFAULT_SECRETS_FILE
    try:
        if not path.is_file():
            return None
        with path.open('r', encoding='utf-8') as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    accounts = data.get('accounts') if isinstance(data, dict) else None
    if not isinstance(accounts, dict):
        return None
    for key in (f'{account_key}.{side}', account_key):
        entry = accounts.get(key)
        if isinstance(entry, dict):
            username, password = _clean(entry.get('id')), _clean(entry.get('pw'))
            if username and password:
                return Credentials(username, password, 'file:' + key)
    return None


def _from_project(project_ref):
    if not isinstance(project_ref, dict) or not project_ref.get('projectId') or not project_ref.get('environmentId'):
        return None
    from . import projects_db
    found = projects_db.environment_credentials(project_ref['projectId'], project_ref['environmentId'])
    if not found:
        return None
    username, password, login_url = _clean(found[0]), _clean(found[1]), found[2]
    if username and password:
        return Credentials(username, password, 'project:environment', login_url)
    return None


def load_credentials(side, account_key='default', *, environ=None, root=None, project_ref=None):
    """Return Credentials or None. Callers must not store the result in reports."""
    environ = os.environ if environ is None else environ
    root = PROJECT_ROOT if root is None else root
    side = 'a' if str(side).lower() in ('a', 'baseline') else 'b'
    return (_from_environment(side, environ, (f'QA_LOGIN_{side.upper()}_',)) or _from_project(project_ref)
            or _from_environment(side, environ, ('QA_LOGIN_',)) or _from_file(side, account_key or 'default', environ, root))


def _secrets_path(environ=None, root=None):
    environ = os.environ if environ is None else environ
    raw = environ.get('QA_SECRETS_FILE')
    return Path(raw) if raw else Path(PROJECT_ROOT if root is None else root) / DEFAULT_SECRETS_FILE


def _mask(value):
    return value[:2] + '*' * max(1, len(value) - 4) + value[-2:] if len(value) > 4 else value[:1] + '***'


def credentials_status(*, environ=None, root=None):
    """What the UI may know: whether a shared account exists, its source and a masked ID. Never the password."""
    found = load_credentials('a', environ=environ, root=root)
    if found is None:
        return {'configured': False}
    return {'configured': True, 'source': found.source.split(':')[0], 'maskedId': _mask(found.username)}


def save_shared_credentials(username, password, *, environ=None, root=None):
    """Write the shared test account to the git-ignored secrets file (accountKey ``default``)."""
    username, password = _clean(username), _clean(password)
    if not username or not password:
        raise ValueError('아이디와 비밀번호를 모두 입력하세요 (각 200자 이하).')
    path = _secrets_path(environ, root)
    data = {}
    try:
        if path.is_file():
            data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict) or not isinstance(data.get('accounts'), dict):
        data = {'accounts': {}}
    data['accounts']['default'] = {'id': username, 'pw': password}
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temporary, path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return credentials_status(environ=environ, root=root)


def clear_shared_credentials(*, environ=None, root=None):
    path = _secrets_path(environ, root)
    try:
        data = json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {}
    except (OSError, ValueError):
        data = {}
    if isinstance(data, dict) and isinstance(data.get('accounts'), dict):
        data['accounts'].pop('default', None)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    return credentials_status(environ=environ, root=root)
