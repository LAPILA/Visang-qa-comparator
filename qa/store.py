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
        # Ordinary URLs are identities too: do not turn %20 into + or rewrite
        # hash/query state merely because the report is being persisted.
        queries = [parts.query]
        if '?' in parts.fragment:
            queries.append(parts.fragment.partition('?')[2])
        elif '=' in parts.fragment:
            queries.append(parts.fragment)
        if not parts.username and not parts.password and not any(
                SENSITIVE.search(key) for query in queries for key, _ in parse_qsl(query, keep_blank_values=True)):
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


class RunDirectoryLease:
    """One server owns a report directory; separate processes must use separate roots."""
    def __init__(self, root):
        root = Path(root).resolve()
        root.mkdir(parents=True, exist_ok=True)
        self.stream = (root / '.server.lock').open('a+b')
        try:
            self.stream.seek(0, os.SEEK_END)
            if self.stream.tell() == 0:
                self.stream.write(b'\0')
                self.stream.flush()
            self.stream.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.stream.close()
            raise ValueError('이 결과 폴더를 다른 서버가 사용 중입니다. 기존 서버를 종료하거나 QA_RUNS_DIR을 분리하세요.') from exc

    def close(self):
        if self.stream.closed:
            return
        try:
            self.stream.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.stream.fileno(), fcntl.LOCK_UN)
        finally:
            self.stream.close()


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

    @staticmethod
    def _summary(job, report_path):
        summary = {key: job.get(key) for key in
                   ('id', 'state', 'progress', 'operatorId', 'profileId', 'startedAt', 'finishedAt')}
        summary.update(totals=(job.get('report') or {}).get('totals'),
                       testType=(job.get('options') or {}).get('test_type', 'comparison'),
                       schemaVersion=job.get('schemaVersion', '1.0'),
                       updatedAt=timestamp(), version=uuid.uuid4().hex,
                       reportMtimeNs=report_path.stat().st_mtime_ns)
        return summary

    @staticmethod
    def _write_summary(path, summary):
        temporary = path.with_name('m_summary.' + uuid.uuid4().hex + '.tmp')
        try:
            temporary.write_text(json.dumps(summary, ensure_ascii=False), encoding='utf-8')
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def save(self, job):
        path = self._path(job['id'])
        with self.lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name('report.' + uuid.uuid4().hex + '.tmp')
            safe_job = redact(job)
            payload = json.dumps(safe_job, ensure_ascii=False, indent=2, allow_nan=False)
            try:
                with temporary.open('w', encoding='utf-8', newline='\n') as stream:
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, path)
                try:
                    self._write_summary(path.parent / 'm_summary.json', self._summary(safe_job, path))
                except OSError:
                    # The report remains authoritative; list() can rebuild the small summary.
                    pass
            finally:
                temporary.unlink(missing_ok=True)

    def get(self, run_id):
        path = self._path(run_id)
        with self.lock:
            if not path.is_file():
                return None
            try:
                job = json.loads(path.read_text(encoding='utf-8'))
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise ValueError('저장된 보고서가 손상되었습니다.') from exc
            if not isinstance(job, dict):
                raise ValueError('저장된 보고서가 JSON 객체가 아닙니다.')
            major = str(job.get('schemaVersion', '1.0')).split('.')[0]
            if major not in ('1', '2'):
                raise ValueError(f'지원하지 않는 보고서 스키마입니다: {major}')
            return job

    def list(self):
        jobs = []
        with self.lock:
            for path in self.root.glob('*/report.json'):
                summary_path = path.parent / 'm_summary.json'
                try:
                    summary = json.loads(summary_path.read_text(encoding='utf-8'))
                    if not isinstance(summary, dict) or summary.get('reportMtimeNs') != path.stat().st_mtime_ns:
                        raise ValueError('Summary is stale')
                except (OSError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
                    try:
                        job = self.get(path.parent.name)
                        if not job:
                            continue
                        summary = self._summary(job, path)
                        try:
                            self._write_summary(summary_path, summary)
                        except OSError:
                            pass
                    except (ValueError, OSError):
                        continue
                summary.pop('reportMtimeNs', None)
                jobs.append(summary)
        return sorted(jobs, key=lambda item: item.get('startedAt') or '', reverse=True)

    def delete(self, run_id):
        """Remove one saved run (report + evidence folder). The caller guards the active run."""
        path = self._path(run_id)
        with self.lock:
            folder = path.parent
            if not folder.is_dir():
                return False
            import shutil
            shutil.rmtree(folder)
            return True

    def recover(self):
        """A killed worker is incomplete, never silently resumed or marked successful."""
        for summary in self.list():
            if summary['state'] in ('running', 'awaiting_auth'):
                job = self.get(summary['id'])
                job.update(state='error', progress='이전 실행이 중단되었습니다.',
                           error='PROCESS_INTERRUPTED', finishedAt=timestamp(), authSide=None)
                self.save(job)

    def review(self, run_id, result_id, reviewer, status, reason, revision, issue_ref=None):
        if status not in REVIEW_STATES:
            raise ValueError('검수 상태가 올바르지 않습니다.')
        if not isinstance(reviewer, str) or not reviewer.strip() or len(reviewer) > 50:
            raise ValueError('검수 담당자를 입력하세요. (최대 50자)')
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 2000:
            raise ValueError('검수 사유를 입력하세요. (최대 2,000자)')
        if not isinstance(revision, int) or isinstance(revision, bool):
            raise ValueError('검수 버전이 필요합니다.')
        if issue_ref is not None:
            if not isinstance(issue_ref, str) or len(issue_ref) > 2000:
                raise ValueError('이슈 참조는 최대 2,000자의 http(s) URL이어야 합니다.')
            issue_ref = issue_ref.strip()
            if issue_ref:
                from qa.config import validate_url
                issue_ref = validate_url(issue_ref)
                if SENSITIVE.search(urlsplit(issue_ref).query) or SENSITIVE.search(urlsplit(issue_ref).fragment):
                    raise ValueError('이슈 URL에 인증 파라미터를 넣을 수 없습니다.')
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
            issue_ref = current.get('issueRef', '') if issue_ref is None else issue_ref
            event['issueRef'] = issue_ref
            updated = {'status': status, 'revision': revision + 1, 'events': [*current['events'], event],
                       'issueRef': issue_ref}
            row['review'] = updated
            job['report'].setdefault('totals', {})['linkedIssues'] = len({
                item.get('review', {}).get('issueRef') for item in job['report']['results']
                if item.get('review', {}).get('issueRef')})
            self.save(job)
            return redact(updated)
