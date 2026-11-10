"""Persistent project QA cases, including cases awaiting automation mapping."""

import json
import re
import uuid
from datetime import datetime, timezone

from qa.conditions import validate_conditions
from qa.projects_db import _connect


def _now():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')


def initialize():
    with _connect() as conn:
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


def list_rules():
    with _connect() as conn:
        rows = conn.execute('''SELECT id, project_id, name, rule_key, condition_json, enabled, created_at
            FROM project_rules ORDER BY created_at DESC, id''').fetchall()
    result = []
    for id, project_id, name, rule_key, raw, enabled, created_at in rows:
        data = json.loads(raw)
        wrapped = isinstance(data, dict) and isinstance(data.get('condition'), dict)
        result.append({'id': id, 'projectId': project_id, 'name': name,
                       'condition': data['condition'] if wrapped else data,
                       'caseData': data.get('caseData', {}) if wrapped else {},
                       'automationReady': data.get('automationReady', True) if wrapped else True,
                       'source': data.get('source') if wrapped else None,
                       'enabled': bool(enabled), 'createdAt': created_at})
    return result


def _validated(rule):
    if not isinstance(rule, dict):
        raise ValueError('검사 규칙 형식이 올바르지 않습니다.')
    id = str(uuid.UUID(rule.get('id', '')))
    project_id = str(uuid.UUID(rule.get('projectId', '')))
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
        raise ValueError('업로드 파일에 중복 규칙 ID가 있습니다.')
    now = _now()
    with _connect() as conn:
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
    return len(rows)


def delete_rule(rule_id):
    rule_id = str(uuid.UUID(rule_id))
    with _connect() as conn:
        return conn.execute('DELETE FROM project_rules WHERE id=%s', (rule_id,)).rowcount > 0
