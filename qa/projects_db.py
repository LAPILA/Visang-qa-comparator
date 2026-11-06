"""Project & environment settings storage (원안: origin/1105_mia ``qa/projects_db.py``).

Two interchangeable backends share one contract (``list_projects`` / ``save_project`` /
``delete_project`` / ``environment_credentials``):

* **PostgreSQL** — used when ``PGHOST``/``PGPORT``/``PGDATABASE``/``PGUSER``/``PGPASSWORD``
  are set (environment or ``.env``) and ``psycopg`` is installed. Schema: docs/db/m_local_db_schema.md.
* **Local JSON file** — the zero-setup default: ``local-settings/projects.json`` (git-ignored).

Per-environment login passwords are encrypted with Fernet (``cryptography``) using
``QA_CREDENTIAL_KEY`` from the environment or ``.env`` (generated on first save). The
plain password never leaves this module except to the engine's login step: API
responses only carry ``hasPassword``. Losing the key makes stored passwords unreadable.
"""
from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
_PG_KEYS = ('PGHOST', 'PGPORT', 'PGDATABASE', 'PGUSER', 'PGPASSWORD')
_LOCK = threading.Lock()


class StorageError(RuntimeError):
    """The configured project store is unreachable or misconfigured (HTTP 503)."""


def _env_path():
    return Path(os.environ.get('QA_ENV_FILE') or ROOT / '.env')


def _dotenv():
    values, path = {}, _env_path()
    try:
        lines = path.read_text(encoding='utf-8').splitlines() if path.exists() else []
    except OSError:
        lines = []
    for line in lines:
        if '=' in line and not line.lstrip().startswith('#'):
            key, value = line.split('=', 1)
            values[key.strip()] = value.strip()
    return values


def _setting(key, dotenv=None):
    return os.environ.get(key) or (dotenv if dotenv is not None else _dotenv()).get(key)


def _file_path():
    return Path(os.environ.get('QA_PROJECTS_FILE') or ROOT / 'local-settings' / 'projects.json')


def backend():
    """'postgres' when fully configured and psycopg is importable, otherwise 'file'."""
    dotenv = _dotenv()
    if all(_setting(key, dotenv) for key in _PG_KEYS):
        try:
            import psycopg  # noqa: F401
        except ImportError:
            return 'file'
        return 'postgres'
    return 'file'


def status():
    name = backend()
    return {'backend': name, 'label': '로컬 PostgreSQL' if name == 'postgres' else '이 PC 설정 파일 (local-settings/projects.json)',
            'encryption': _cipher_available()}


# ---------------------------------------------------------------- encryption
def _cipher_available():
    try:
        import cryptography  # noqa: F401
        return True
    except ImportError:
        return False


def _cipher(create=True):
    try:
        from cryptography.fernet import Fernet
    except ImportError as exc:
        raise ValueError('비밀번호를 암호화할 cryptography 패키지가 없습니다. setup_windows.bat를 다시 실행하거나 '
                         '공용 테스트 계정(검사 설정 4단계)을 사용하세요.') from exc
    key = _setting('QA_CREDENTIAL_KEY')
    if not key:
        if not create:
            return None
        key = Fernet.generate_key().decode('ascii')
        path = _env_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('a', encoding='utf-8') as stream:
            stream.write(f'\nQA_CREDENTIAL_KEY={key}\n')
    return Fernet(key.encode('ascii'))


def _encrypt(password):
    return _cipher().encrypt(password.encode('utf-8')).decode('ascii')


def _decrypt(ciphertext):
    try:
        cipher = _cipher(create=False)
    except ValueError:
        return None
    if cipher is None:
        return None
    try:
        return cipher.decrypt(ciphertext.encode('ascii')).decode('utf-8')
    except Exception:  # wrong/rotated key or corrupted value: behave as "no password"
        return None


# ---------------------------------------------------------------- validation
def _now():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')


def _http_url(value, label):
    parts = urlsplit(value)
    if parts.scheme not in ('http', 'https') or not parts.hostname or parts.username or parts.password:
        raise ValueError(f'{label}은 계정 정보가 없는 HTTP 또는 HTTPS 주소여야 합니다.')


def _clean_project(value):
    if not isinstance(value, dict):
        raise ValueError('프로젝트 형식이 올바르지 않습니다.')
    try:
        project_id = str(uuid.UUID(str(value.get('id', ''))))
    except ValueError as exc:
        raise ValueError('프로젝트 ID 형식이 올바르지 않습니다.') from exc
    name, environments = value.get('name'), value.get('environments')
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 60:
        raise ValueError('프로젝트 이름은 1~60자여야 합니다.')
    if not isinstance(environments, list) or not 1 <= len(environments) <= 100:
        raise ValueError('환경은 1~100개 등록해야 합니다.')
    cleaned, ids = [], set()
    for item in environments:
        if not isinstance(item, dict):
            raise ValueError('환경 형식이 올바르지 않습니다.')
        try:
            item_id = str(uuid.UUID(str(item.get('id', ''))))
        except ValueError as exc:
            raise ValueError('환경 ID 형식이 올바르지 않습니다.') from exc
        env_name, url = item.get('name'), item.get('url')
        if (item_id in ids or not isinstance(env_name, str) or not 1 <= len(env_name.strip()) <= 50
                or not isinstance(url, str) or not 8 <= len(url) <= 2000):
            raise ValueError('환경 이름, URL 또는 ID를 확인하세요.')
        _http_url(url, '환경 URL')
        login_url, login_id, password = item.get('loginUrl') or '', item.get('loginId') or '', item.get('password') or ''
        if (not isinstance(login_url, str) or len(login_url) > 2000 or not isinstance(login_id, str)
                or len(login_id) > 200 or not isinstance(password, str) or len(password) > 500):
            raise ValueError('로그인 URL, ID 또는 비밀번호 길이를 확인하세요.')
        if login_url:
            _http_url(login_url, '로그인 URL')
        ids.add(item_id)
        cleaned.append({'id': item_id, 'name': env_name.strip(), 'url': url, 'loginUrl': login_url.strip(),
                        'loginId': login_id.strip(), 'password': password, 'clearPassword': item.get('clearPassword') is True})
    return project_id, name.strip(), cleaned


def _public(project):
    """API shape: never the password or its ciphertext."""
    return {'id': project['id'], 'name': project['name'],
            'environments': [{'id': e['id'], 'name': e['name'], 'url': e['url'], 'loginUrl': e.get('loginUrl') or '',
                              'loginId': e.get('loginId') or '', 'hasPassword': bool(e.get('passwordCiphertext'))}
                             for e in project.get('environments', [])]}


# ---------------------------------------------------------------- file backend
def _read_file():
    path = _file_path()
    try:
        data = json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {}
    except (OSError, ValueError) as exc:
        raise StorageError('프로젝트 설정 파일(local-settings/projects.json)을 읽지 못했습니다.') from exc
    projects = data.get('projects') if isinstance(data, dict) else None
    return projects if isinstance(projects, list) else []


def _write_file(projects):
    path = _file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps({'version': 1, 'projects': projects}, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temporary, path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


# ---------------------------------------------------------------- postgres backend
def _connect():
    import psycopg
    dotenv = _dotenv()
    config = {key: _setting(key, dotenv) for key in _PG_KEYS}
    try:
        return psycopg.connect(host=config['PGHOST'], port=config['PGPORT'], dbname=config['PGDATABASE'],
                               user=config['PGUSER'], password=config['PGPASSWORD'], connect_timeout=5)
    except psycopg.Error as exc:
        raise StorageError('프로젝트 DB(PostgreSQL)에 연결하지 못했습니다. .env의 PG* 설정을 확인하세요.') from exc


def _pg(callback):
    import psycopg
    try:
        with _connect() as conn:
            return callback(conn)
    except psycopg.Error as exc:
        raise StorageError('프로젝트 DB 작업에 실패했습니다.') from exc


def initialize():
    if backend() != 'postgres':
        return
    def create(conn):
        conn.execute('''CREATE TABLE IF NOT EXISTS projects (
            id TEXT PRIMARY KEY, name TEXT NOT NULL CHECK (length(trim(name)) BETWEEN 1 AND 60),
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL)''')
        conn.execute('''CREATE TABLE IF NOT EXISTS project_environments (
            id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            name TEXT NOT NULL CHECK (length(trim(name)) BETWEEN 1 AND 50),
            start_url TEXT NOT NULL CHECK (length(start_url) BETWEEN 8 AND 2000),
            sort_order INTEGER NOT NULL CHECK (sort_order >= 0),
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            UNIQUE (project_id, sort_order))''')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_project_environments_project ON project_environments(project_id)')
        conn.execute('ALTER TABLE project_environments ADD COLUMN IF NOT EXISTS login_url TEXT')
        conn.execute('ALTER TABLE project_environments ADD COLUMN IF NOT EXISTS login_id TEXT')
        conn.execute('ALTER TABLE project_environments ADD COLUMN IF NOT EXISTS password_ciphertext TEXT')
    _pg(create)


def _pg_projects():
    def read(conn):
        projects = conn.execute('SELECT id, name FROM projects ORDER BY created_at DESC, id').fetchall()
        environments = conn.execute('''SELECT id, project_id, name, start_url, login_url, login_id, password_ciphertext
            FROM project_environments ORDER BY project_id, sort_order''').fetchall()
        return projects, environments
    projects, environments = _pg(read)
    by_id = {pid: {'id': pid, 'name': name, 'environments': []} for pid, name in projects}
    for eid, pid, name, url, login_url, login_id, ciphertext in environments:
        if pid in by_id:
            by_id[pid]['environments'].append({'id': eid, 'name': name, 'url': url, 'loginUrl': login_url or '',
                                               'loginId': login_id or '', 'passwordCiphertext': ciphertext})
    return list(by_id.values())


# ---------------------------------------------------------------- public API
def _all_projects():
    if backend() == 'postgres':
        initialize()
        return _pg_projects()
    return _read_file()


def list_projects():
    return [_public(project) for project in _all_projects()]


def save_project(value):
    project_id, name, environments = _clean_project(value)
    now = _now()
    if backend() == 'postgres':
        initialize()
        def write(conn):
            conn.execute('''INSERT INTO projects (id,name,created_at,updated_at) VALUES (%s,%s,%s,%s)
                ON CONFLICT (id) DO UPDATE SET name=EXCLUDED.name, updated_at=EXCLUDED.updated_at''',
                         (project_id, name, now, now))
            conn.execute('DELETE FROM project_environments WHERE project_id=%s AND NOT (id = ANY(%s))',
                         (project_id, [e['id'] for e in environments]))
            conn.execute('UPDATE project_environments SET sort_order=sort_order+1000 WHERE project_id=%s', (project_id,))
            for order, e in enumerate(environments):
                ciphertext = _encrypt(e['password']) if e['password'] else None
                conn.execute('''INSERT INTO project_environments
                    (id,project_id,name,start_url,sort_order,created_at,updated_at,login_url,login_id,password_ciphertext)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (id) DO UPDATE SET name=EXCLUDED.name, start_url=EXCLUDED.start_url,
                        sort_order=EXCLUDED.sort_order, updated_at=EXCLUDED.updated_at,
                        login_url=EXCLUDED.login_url, login_id=EXCLUDED.login_id,
                        password_ciphertext=CASE WHEN %s THEN NULL
                            ELSE COALESCE(EXCLUDED.password_ciphertext, project_environments.password_ciphertext) END''',
                             (e['id'], project_id, e['name'], e['url'], order, now, now, e['loginUrl'] or None,
                              e['loginId'] or None, ciphertext, e['clearPassword']))
        _pg(write)
    else:
        with _LOCK:
            projects = _read_file()
            previous = next((p for p in projects if p.get('id') == project_id), None)
            old_envs = {e.get('id'): e for e in (previous or {}).get('environments', [])}
            stored = []
            for e in environments:
                old = old_envs.get(e['id'], {})
                ciphertext = None if e['clearPassword'] else (_encrypt(e['password']) if e['password'] else old.get('passwordCiphertext'))
                stored.append({'id': e['id'], 'name': e['name'], 'url': e['url'], 'loginUrl': e['loginUrl'],
                               'loginId': e['loginId'], 'passwordCiphertext': ciphertext})
            record = {'id': project_id, 'name': name, 'environments': stored,
                      'createdAt': (previous or {}).get('createdAt') or now, 'updatedAt': now}
            _write_file([record, *[p for p in projects if p.get('id') != project_id]])
    return next(project for project in list_projects() if project['id'] == project_id)


def delete_project(project_id):
    project_id = str(uuid.UUID(str(project_id)))
    if backend() == 'postgres':
        initialize()
        return _pg(lambda conn: conn.execute('DELETE FROM projects WHERE id=%s', (project_id,)).rowcount > 0)
    with _LOCK:
        projects = _read_file()
        remaining = [p for p in projects if p.get('id') != project_id]
        if len(remaining) == len(projects):
            return False
        _write_file(remaining)
        return True


def environment_credentials(project_id, environment_id):
    """(login_id, password, login_url) for the engine's login step, or None. Never for API output."""
    try:
        project_id, environment_id = str(uuid.UUID(str(project_id))), str(uuid.UUID(str(environment_id)))
        projects = _all_projects()
    except (ValueError, StorageError):
        return None
    project = next((p for p in projects if p.get('id') == project_id), None)
    env = next((e for e in (project or {}).get('environments', []) if e.get('id') == environment_id), None)
    if not env:
        return None
    password = _decrypt(env['passwordCiphertext']) if env.get('passwordCiphertext') else None
    return env.get('loginId') or None, password, env.get('loginUrl') or None
