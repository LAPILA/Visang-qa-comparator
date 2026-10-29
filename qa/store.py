"""Atomic, local JSON reports and optimistic review revisions."""
from __future__ import annotations

import json
import os
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


REVIEW_STATES = {'BUG_CONFIRMED', 'EXPECTED_DIFFERENCE', 'FALSE_POSITIVE', 'RETEST_REQUIRED', 'VERIFIED_OK'}
SENSITIVE = re.compile(r'(password|passwd|authorization|cookie|token|session.?id|secret|api.?key)', re.I)


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def redact_url(value):
    try:
        parts = urlsplit(value)
        if parts.scheme not in ('http', 'https'):
            return value
        host = parts.netloc.rsplit('@', 1)[-1]
        query = urlencode([(key, '[REDACTED]' if SENSITIVE.search(key) else val)
                           for key, val in parse_qsl(parts.query, keep_blank_values=True)])
        fragment = parts.fragment
        if '?' in fragment:
            route, suffix = fragment.split('?', 1)
            fragment = route + '?' + urlencode([(key, '[REDACTED]' if SENSITIVE.search(key) else val)
                                                for key, val in parse_qsl(suffix, keep_blank_values=True)])
        elif '=' in fragment:
            fragment = urlencode([(key, '[REDACTED]' if SENSITIVE.search(key) else val)
                                  for key, val in parse_qsl(fragment, keep_blank_values=True)])
        return urlunsplit((parts.scheme, host, parts.path, query, fragment))
    except ValueError:
        return '[INVALID_URL]'


def redact(value):
    if isinstance(value, dict):
        return {key: ('[REDACTED]' if SENSITIVE.search(str(key)) else redact(item))
                for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str):
        value = re.sub(r'https?://[^\s<>"\']+', lambda match: redact_url(match.group()), value)
        value = re.sub(r'(?i)\bBearer\s+[^\s,;]+', 'Bearer [REDACTED]', value)
        value = re.sub(r'(?i)(password|passwd|token|secret|authorization|cookie|sessionid)\s*[=:]\s*[^\s,;&?#]+', r'\1=[REDACTED]', value)
        return value
    return value


class ReviewConflict(Exception):
    pass


class ReportStore:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()

    def _path(self, run_id):
        try:
            if str(uuid.UUID(run_id)) != run_id:
                raise ValueError()
        except (ValueError, AttributeError, TypeError) as exc:
            raise ValueError('실행 ID가 올바르지 않습니다.') from exc
        return self.root / run_id / 'report.json'

    def save(self, job):
        path = self._path(job['id'])
        with self.lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name('report.' + uuid.uuid4().hex + '.tmp')
            payload = json.dumps(redact(job), ensure_ascii=False, indent=2, allow_nan=False)
            try:
                with temporary.open('w', encoding='utf-8', newline='\n') as stream:
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, path)
            finally:
                temporary.unlink(missing_ok=True)

    def get(self, run_id):
        path = self._path(run_id)
        with self.lock:
            if not path.is_file():
                return None
            try:
                return json.loads(path.read_text(encoding='utf-8'))
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise ValueError('저장된 보고서가 손상되었습니다.') from exc

    def list(self):
        jobs = []
        with self.lock:
            for path in self.root.glob('*/report.json'):
                try:
                    job = self.get(path.parent.name)
                except (ValueError, OSError):
                    continue
                if job:
                    jobs.append({key: job.get(key) for key in
                                 ('id', 'state', 'progress', 'operatorId', 'profileId', 'startedAt', 'finishedAt')}
                                | {'totals': (job.get('report') or {}).get('totals')})
        return sorted(jobs, key=lambda item: item.get('startedAt') or '', reverse=True)

    def recover(self):
        """A killed worker is incomplete, never silently resumed or marked successful."""
        for summary in self.list():
            if summary['state'] in ('running', 'awaiting_auth'):
                job = self.get(summary['id'])
                job.update(state='error', progress='이전 실행이 중단되었습니다.',
                           error='PROCESS_INTERRUPTED', finishedAt=timestamp(), authSide=None)
                self.save(job)

    def review(self, run_id, result_id, reviewer, status, reason, revision):
        if status not in REVIEW_STATES:
            raise ValueError('검수 상태가 올바르지 않습니다.')
        if not isinstance(reviewer, str) or not reviewer.strip() or len(reviewer) > 50:
            raise ValueError('검수 담당자를 입력하세요. (최대 50자)')
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 2000:
            raise ValueError('검수 사유를 입력하세요. (최대 2,000자)')
        if not isinstance(revision, int) or isinstance(revision, bool):
            raise ValueError('검수 버전이 필요합니다.')
        with self.lock:
            job = self.get(run_id)
            if not job or not job.get('report'):
                raise ValueError('검수할 실행 결과가 없습니다.')
            if job['state'] not in ('done', 'cancelled', 'error'):
                raise ValueError('진행 중에는 검수를 저장할 수 없습니다.')
            row = next((row for row in job['report']['results'] if row['id'] == result_id), None)
            if row is None:
                raise ValueError('결과 항목을 찾을 수 없습니다.')
            current = row.get('review') or {'status': 'UNREVIEWED', 'revision': 0, 'events': []}
            if current['revision'] != revision:
                raise ReviewConflict('다른 검수 변경이 있습니다. 결과를 새로고침하고 다시 확인하세요.')
            event = {'reviewer': reviewer.strip(), 'reason': reason.strip(), 'status': status,
                     'previous': current['status'], 'revision': revision + 1, 'timestamp': timestamp()}
            updated = {'status': status, 'revision': revision + 1, 'events': [*current['events'], event]}
            row['review'] = updated
            self.save(job)
            return redact(updated)
