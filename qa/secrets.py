"""Test-account credentials stay on the operator's machine.

Credentials are read only inside the engine process at login time, from
environment variables or a local secrets file that is ignored by git. They are
never accepted through the HTTP API, never written to ``runs/`` reports, never
logged and never echoed back to the UI. A missing or malformed source yields
``None`` so the run records ``LOGIN_CREDENTIALS_MISSING`` instead of guessing.

Resolution order for side ``a``/``b`` and ``accountKey`` (default ``default``):

1. ``QA_LOGIN_A_ID`` / ``QA_LOGIN_A_PW`` (side-specific environment variables)
2. ``QA_LOGIN_ID`` / ``QA_LOGIN_PW`` (shared environment variables)
3. ``QA_SECRETS_FILE`` or ``./secrets/accounts.json``::

       {"accounts": {"default": {"id": "tester", "pw": "..."},
                     "default.b": {"id": "tester-b", "pw": "..."}}}

   ``<accountKey>.<side>`` wins over ``<accountKey>``.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

DEFAULT_SECRETS_FILE = Path('secrets') / 'accounts.json'
_MAX_LENGTH = 200


class Credentials:
    """Opaque holder: repr/str never reveal the secret values."""

    __slots__ = ('username', 'password', 'source')

    def __init__(self, username, password, source):
        self.username, self.password, self.source = username, password, source

    def __repr__(self):
        return f'Credentials(source={self.source!r}, username=[REDACTED], password=[REDACTED])'

    __str__ = __repr__


def _clean(value):
    if not isinstance(value, str):
        return None
    value = value.strip('\r\n')
    return value if 0 < len(value) <= _MAX_LENGTH else None


def _from_environment(side, environ):
    for prefix in (f'QA_LOGIN_{side.upper()}_', 'QA_LOGIN_'):
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


def load_credentials(side, account_key='default', *, environ=None, root='.'):
    """Return Credentials or None. Callers must not store the result in reports."""
    environ = os.environ if environ is None else environ
    side = 'a' if str(side).lower() in ('a', 'baseline') else 'b'
    return _from_environment(side, environ) or _from_file(side, account_key or 'default', environ, root)
