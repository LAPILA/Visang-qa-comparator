"""PostgreSQL storage for project settings."""
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import psycopg


def _settings():
    values = {}
    path = Path(__file__).resolve().parent.parent / '.env'
    if path.exists():
        for line in path.read_text(encoding='utf-8').splitlines():
            if '=' in line and not line.lstrip().startswith('#'):
                key, value = line.split('=', 1)
                values[key.strip()] = value.strip()
    return {key: os.environ.get(key, values.get(key)) for key in ('PGHOST', 'PGPORT', 'PGDATABASE', 'PGUSER', 'PGPASSWORD')}


def _connect():
    config = _settings()
    if not all(config.values()):
        raise RuntimeError('PostgreSQL 접속 설정이 없습니다. .env의 PGHOST, PGPORT, PGDATABASE, PGUSER, PGPASSWORD를 확인하세요.')
    return psycopg.connect(host=config['PGHOST'], port=config['PGPORT'], dbname=config['PGDATABASE'],
                           user=config['PGUSER'], password=config['PGPASSWORD'], connect_timeout=5)


def initialize():
    with _connect() as conn:
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


def list_projects():
    with _connect() as conn:
        projects = conn.execute('SELECT id, name FROM projects ORDER BY created_at DESC, id').fetchall()
        environments = conn.execute('SELECT id, project_id, name, start_url FROM project_environments ORDER BY project_id, sort_order').fetchall()
    by_id = {id: {'id': id, 'name': name, 'environments': []} for id, name in projects}
    for id, project_id, name, url in environments:
        by_id[project_id]['environments'].append({'id': id, 'name': name, 'url': url})
    return list(by_id.values())


def save_project(value):
    if not isinstance(value, dict):
        raise ValueError('프로젝트 형식이 올바르지 않습니다.')
    project_id = str(uuid.UUID(value.get('id', '')))
    name = value.get('name')
    environments = value.get('environments')
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 60:
        raise ValueError('프로젝트 이름은 1~60자여야 합니다.')
    if not isinstance(environments, list) or not 1 <= len(environments) <= 100:
        raise ValueError('환경은 1~100개 등록해야 합니다.')
    cleaned = []
    ids = set()
    for item in environments:
        if not isinstance(item, dict):
            raise ValueError('환경 형식이 올바르지 않습니다.')
        item_id = str(uuid.UUID(item.get('id', '')))
        env_name, url = item.get('name'), item.get('url')
        if item_id in ids or not isinstance(env_name, str) or not 1 <= len(env_name.strip()) <= 50 or not isinstance(url, str) or not 8 <= len(url) <= 2000:
            raise ValueError('환경 이름, URL 또는 ID를 확인하세요.')
        parsed = urlsplit(url)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError('환경 URL은 계정 정보가 없는 HTTP 또는 HTTPS 주소여야 합니다.')
        ids.add(item_id)
        cleaned.append((item_id, env_name.strip(), url))
    now = datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')
    with _connect() as conn:
        conn.execute('''INSERT INTO projects (id,name,created_at,updated_at) VALUES (%s,%s,%s,%s)
            ON CONFLICT (id) DO UPDATE SET name=EXCLUDED.name, updated_at=EXCLUDED.updated_at''',
            (project_id, name.strip(), now, now))
        conn.execute('DELETE FROM project_environments WHERE project_id=%s AND NOT (id = ANY(%s))',
                     (project_id, list(ids)))
        conn.execute('UPDATE project_environments SET sort_order=sort_order+1000 WHERE project_id=%s', (project_id,))
        for order, (item_id, env_name, url) in enumerate(cleaned):
            conn.execute('''INSERT INTO project_environments
                (id,project_id,name,start_url,sort_order,created_at,updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (id) DO UPDATE SET name=EXCLUDED.name, start_url=EXCLUDED.start_url,
                    sort_order=EXCLUDED.sort_order, updated_at=EXCLUDED.updated_at''',
                (item_id, project_id, env_name, url, order, now, now))
    return {'id': project_id, 'name': name.strip(), 'environments': [
        {'id': item_id, 'name': env_name, 'url': url} for item_id, env_name, url in cleaned]}


def delete_project(project_id):
    project_id = str(uuid.UUID(project_id))
    with _connect() as conn:
        result = conn.execute('DELETE FROM projects WHERE id=%s', (project_id,))
        return result.rowcount > 0
