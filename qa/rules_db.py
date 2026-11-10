"""Persistent project QA cases, including cases awaiting automation mapping.

Same two backends as ``qa.projects_db``: PostgreSQL ``project_rules`` when PG* is configured,
otherwise ``local-settings/rules.json`` (git-ignored). Each rule stores the automatic condition
(``qa/conditions.py`` contract), the editable test-case text (``caseData``), whether it can run
automatically (``automationReady``) and its Excel source.
"""

import json
import os
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from qa import projects_db
from qa.conditions import validate_conditions

_LOCK = threading.Lock()


class RuleConflict(ValueError):
    """Same rule ID twice in one project (HTTP 409)."""


def _now():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')


def _file_path():
    return Path(os.environ.get('QA_RULES_FILE') or projects_db.ROOT / 'local-settings' / 'rules.json')


# ---------------------------------------------------------------- postgres backend
def _pg(callback):
    import psycopg
    try:
        with projects_db._connect() as conn:
            return callback(conn)
    except psycopg.errors.UniqueViolation as exc:
        raise RuleConflict('같은 프로젝트에 동일한 규칙 ID가 있습니다.') from exc
    except psycopg.Error as exc:
        raise projects_db.StorageError('검사 규칙 DB 작업에 실패했습니다.') from exc


def initialize():
    if projects_db.backend() != 'postgres':
        return
    projects_db.initialize()

    def create(conn):
        conn.execute('''CREATE TABLE IF NOT EXISTS project_rules (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            name TEXT NOT NULL CHECK (length(trim(name)) BETWEEN 1 AND 100),
            rule_key TEXT NOT NULL CHECK (length(rule_key) BETWEEN 1 AND 100),
            condition_json TEXT NOT NULL CHECK ((condition_json IS JSON)),
            enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0,1)),
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            UNIQUE (project_id, rule_key))''')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_project_rules_project ON project_rules(project_id, enabled)')
    _pg(create)


# ---------------------------------------------------------------- file backend
def _read_file():
    path = _file_path()
    try:
        data = json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {}
    except (OSError, ValueError) as exc:
        raise projects_db.StorageError('검사 규칙 파일(local-settings/rules.json)을 읽지 못했습니다.') from exc
    rules = data.get('rules') if isinstance(data, dict) else None
    return rules if isinstance(rules, list) else []


def _write_file(rules):
    path = _file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps({'version': 1, 'rules': rules}, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temporary, path)


# ---------------------------------------------------------------- shared
def _public(id, project_id, name, raw, enabled, created_at):
    data = json.loads(raw) if isinstance(raw, str) else raw
    wrapped = isinstance(data, dict) and isinstance(data.get('condition'), dict)
    return {'id': id, 'projectId': project_id, 'name': name,
            'condition': data['condition'] if wrapped else data,
            'caseData': data.get('caseData', {}) if wrapped else {},
            'automationReady': data.get('automationReady', True) if wrapped else True,
            'source': data.get('source') if wrapped else None,
            'enabled': bool(enabled), 'createdAt': created_at}


def list_rules():
    if projects_db.backend() == 'postgres':
        initialize()
        rows = _pg(lambda conn: conn.execute('''SELECT id, project_id, name, rule_key, condition_json, enabled, created_at
            FROM project_rules ORDER BY created_at DESC, id''').fetchall())
        return [_public(id, project_id, name, raw, enabled, created_at)
                for id, project_id, name, _key, raw, enabled, created_at in rows]
    projects = {project['id'] for project in projects_db.list_projects()}
    stored = sorted(_read_file(), key=lambda item: (item.get('createdAt') or '', item.get('id') or ''), reverse=True)
    # Rules of a deleted project disappear with it (the PostgreSQL schema cascades the same way).
    return [_public(item['id'], item['projectId'], item['name'], item['payload'], item.get('enabled'), item.get('createdAt'))
            for item in stored if item.get('projectId') in projects]


def _validated(rule):
    if not isinstance(rule, dict):
        raise ValueError('검사 규칙 형식이 올바르지 않습니다.')
    id = str(uuid.UUID(str(rule.get('id', ''))))
    project_id = str(uuid.UUID(str(rule.get('projectId', ''))))
    name = rule.get('name')
    condition = rule.get('condition')
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 100 or not isinstance(condition, dict):
        raise ValueError('검사 규칙 이름 또는 조건을 확인하세요.')
    key = condition.get('id')
    if not isinstance(key, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,100}', key):
        raise ValueError('규칙 ID는 영문·숫자·점·밑줄·하이픈만 사용할 수 있습니다.')
    ready = rule.get('automationReady', True)
    if not isinstance(ready, bool):
        raise ValueError('자동 실행 상태가 올바르지 않습니다.')
    if ready:
        validate_conditions([condition])
    case_data = rule.get('caseData') or {}
    source = rule.get('source')
    if not isinstance(case_data, dict) or (source is not None and not isinstance(source, dict)):
        raise ValueError('테스트 케이스 세부 정보가 올바르지 않습니다.')
    payload = json.dumps({'condition': condition, 'caseData': case_data,
                          'automationReady': ready, 'source': source}, ensure_ascii=False)
    if len(payload.encode('utf-8')) > 32_000:
        raise ValueError('테스트 케이스 하나의 내용은 32KB 이하여야 합니다.')
    enabled = bool(rule.get('enabled', True)) and ready
    created_at = rule.get('createdAt') if isinstance(rule.get('createdAt'), str) else _now()
    return id, project_id, name.strip(), key, payload, int(enabled), created_at


def save_rules(items):
    if not isinstance(items, list) or not 1 <= len(items) <= 2000:
        raise ValueError('한 번에 1~2,000개 검사 규칙을 저장할 수 있습니다.')
    rows = [_validated(item) for item in items]
    if len({row[0] for row in rows}) != len(rows) or len({(row[1], row[3]) for row in rows}) != len(rows):
        raise RuleConflict('업로드 파일에 중복 규칙 ID가 있습니다.')
    now = _now()
    if projects_db.backend() == 'postgres':
        initialize()

        def write(conn):
            for id, project_id, name, key, payload, enabled, created_at in rows:
                result = conn.execute('''INSERT INTO project_rules
                    (id, project_id, name, rule_key, condition_json, enabled, created_at, updated_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (id) DO UPDATE SET name=EXCLUDED.name, rule_key=EXCLUDED.rule_key,
                        condition_json=EXCLUDED.condition_json, enabled=EXCLUDED.enabled,
                        updated_at=EXCLUDED.updated_at
                    WHERE project_rules.project_id=EXCLUDED.project_id''',
                    (id, project_id, name, key, payload, enabled, created_at, now))
                if result.rowcount != 1:
                    raise ValueError('다른 프로젝트에 속한 검사 규칙은 수정할 수 없습니다.')
        _pg(write)
        return len(rows)
    projects = {project['id'] for project in projects_db.list_projects()}
    with _LOCK:
        stored = {item['id']: item for item in _read_file()}
        for id, project_id, name, key, payload, enabled, created_at in rows:
            if project_id not in projects:
                raise ValueError('등록되지 않은 프로젝트의 검사 규칙입니다. 프로젝트 설정을 먼저 저장하세요.')
            previous = stored.get(id)
            if previous and previous['projectId'] != project_id:
                raise ValueError('다른 프로젝트에 속한 검사 규칙은 수정할 수 없습니다.')
            if any(other['id'] != id and other['projectId'] == project_id and other['ruleKey'] == key for other in stored.values()):
                raise RuleConflict('같은 프로젝트에 동일한 규칙 ID가 있습니다.')
            stored[id] = {'id': id, 'projectId': project_id, 'name': name, 'ruleKey': key, 'payload': json.loads(payload),
                          'enabled': enabled, 'createdAt': (previous or {}).get('createdAt') or created_at, 'updatedAt': now}
        _write_file(list(stored.values()))
    return len(rows)


def delete_rule(rule_id):
    rule_id = str(uuid.UUID(str(rule_id)))
    if projects_db.backend() == 'postgres':
        initialize()
        return _pg(lambda conn: conn.execute('DELETE FROM project_rules WHERE id=%s', (rule_id,)).rowcount > 0)
    with _LOCK:
        rules = _read_file()
        remaining = [item for item in rules if item.get('id') != rule_id]
        if len(remaining) == len(rules):
            return False
        _write_file(remaining)
        return True
