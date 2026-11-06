"""VISANG QA AI (Web QA Comparator): local HTTP UI and durable scan/review lifecycle.

The crawler, Playwright observers and Pillow comparison evolve the previous MVP.
Start with python app.py. No scan starts until requested in the local UI.
"""
from __future__ import annotations

import csv
import hashlib
import importlib.metadata
import io
import json
import os
import secrets
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from qa import __version__
from qa.config import parse_options, profiles, validate_url
from qa.projects_db import StorageError
from qa.store import ReportStore, ReviewConflict, RunDirectoryLease, redact, timestamp

ROOT = Path(__file__).resolve().parent
RUNS = Path(os.environ.get('QA_RUNS_DIR', str(ROOT / 'runs')))
PUBLIC = ROOT / 'public'


def csv_safe(value):
    value = '' if value is None else str(value)
    if value.lstrip(' \t\r\n').startswith(('=', '+', '-', '@')) or value.startswith(('\t', '\r', '\n')):
        return "'" + value
    return value


def _with_triage(job):
    """Legacy reports get the same deterministic triage on read; verdicts are untouched."""
    report = (job or {}).get('report') if isinstance(job, dict) else None
    if isinstance(report, dict) and isinstance(report.get('results'), list) and any(
            isinstance(row, dict) and 'triage' not in row for row in report['results']):
        from qa.triage import apply_triage
        apply_triage(report)
    return job


def csv_report(job):
    output = io.StringIO(newline='')
    writer = csv.writer(output)
    writer.writerow(['실행 ID', '실행 담당자', '페이지', '영역', '자동 상태', '검수 분류', '분류 사유', '분류', '차이율(%)',
                     '기준 URL', '비교 URL', '검수 상태', '검수 버전', '검증식 결과',
                     '테스트 목적', '오류 대분류', '세부 유형', '심각도', '고유 발견 ID', '회귀 구분', '연결 이슈'])
    for row in (job.get('report') or {}).get('results', []):
        writer.writerow([csv_safe(value) for value in (
            job['id'], job.get('operatorId'), row.get('key'), row.get('region_id'), row.get('status'),
            (row.get('triage') or {}).get('bucket', ''), (row.get('triage') or {}).get('label', ''),
            ' | '.join(row.get('flags', [])), (row.get('visual') or {}).get('differencePercent'),
            (row.get('baseline') or {}).get('url'), (row.get('candidate') or {}).get('url'),
            (row.get('review') or {}).get('status', 'UNREVIEWED'),
            (row.get('review') or {}).get('revision', 0),
            ' | '.join(f"{check.get('check_id')}: {check.get('status')} ({check.get('reason_code')})"
                       for check in row.get('checks', [])),
            (job.get('options') or {}).get('test_type', 'comparison'),
            ' | '.join(row.get('categories', [])), ' | '.join(row.get('subtypes', [])), row.get('severity'),
            ' | '.join(row.get('findingIds', [])), (row.get('regression') or {}).get('classification', 'NOT_EVALUATED'),
            (row.get('review') or {}).get('issueRef', ''),
        )])
    return ('\ufeff' + output.getvalue()).encode('utf-8')


def csv_inventory(job):
    output = io.StringIO(newline='')
    writer = csv.writer(output)
    writer.writerow(['실행 ID', '제품', '환경', '환경 이름', '페이지 키', '요청 URL', '최종 URL',
                     '제목', '메뉴 경로', '실제 방문', 'HTTP 상태', '발견 동작', '차단 동작', '미실행 사유'])
    inventory = (job.get('report') or {}).get('inventory') or {}
    for environment in inventory.get('environments', []):
        for page in environment.get('pages', []):
            writer.writerow([csv_safe(value) for value in (
                job['id'], inventory.get('productId'), environment.get('id'), environment.get('name'),
                page.get('pageKey'), page.get('url'), page.get('finalUrl'), page.get('title'),
                ' > '.join(str(item.get('label', '')) if isinstance(item, dict) else str(item)
                           for item in page.get('navigationTrail', [])),
                page.get('visited'), page.get('statusCode'), page.get('actionCount'), page.get('blockedActionCount'),
                ' | '.join(page.get('notExecutedReasons', [])),
            )])
    return ('\ufeff' + output.getvalue()).encode('utf-8')


def runtime_manifest():
    files = [ROOT / 'app.py', *sorted((ROOT / 'qa').glob('*.py'))]
    source_hash = hashlib.sha256()
    for path in files:
        source_hash.update(path.relative_to(ROOT).as_posix().encode())
        source_hash.update(path.read_bytes())
    return {'tool_version': __version__, 'source_sha256': source_hash.hexdigest(),
            'python': os.sys.version.split()[0],
            'dependencies': {name: importlib.metadata.version(name) for name in ('playwright', 'Pillow')}}


class JobService:
    def __init__(self, root, runner=None):
        self.store = ReportStore(root)
        self.store.recover()
        self.lock = threading.RLock()
        self.active = None
        self.jobs = {}
        self.cancel_events = {}
        self.auth_events = {}
        self.runner = runner
        self.worker_thread = None
        self.closing = False

    def start(self, options):
        with self.lock:
            if self.closing:
                raise ReviewConflict('서버가 종료 중입니다.')
            if self.active:
                raise ReviewConflict('이미 검사가 진행 중입니다. 완료하거나 중지한 후 시작하세요.')
            if options.get('test_type') == 'regression':
                previous = self.store.get(options.get('previous_run_id'))
                if not previous or not previous.get('report') or previous.get('state') not in ('done', 'cancelled', 'error'):
                    raise ValueError('결과가 저장된 과거 실행을 선택하세요. 진행 중인 실행은 회귀 기준으로 사용할 수 없습니다.')
            run_id = str(uuid.uuid4())
            job = {'id': run_id, 'schemaVersion': '2.0', 'state': 'running',
                   'progress': '브라우저 실행 준비 중', 'operatorId': options['operator_id'],
                   'profileId': options['profile_id'], 'startedAt': timestamp(), 'finishedAt': None,
                   'report': None, 'error': None, 'authSide': None, 'options': options}
            self.store.save(job)
            self.jobs[run_id] = job
            self.cancel_events[run_id] = threading.Event()
            self.auth_events[run_id] = threading.Event()
            self.active = run_id
            self.worker_thread = threading.Thread(target=self._worker, args=(job, options), daemon=True,
                                                 name='qa-scan-' + run_id[:8])
            self.worker_thread.start()
            return run_id

    def get(self, run_id):
        with self.lock:
            if run_id in self.jobs:
                # Copy before serializing so the HTTP thread sees a consistent snapshot.
                job = redact(json.loads(json.dumps(self.jobs[run_id])))
            else:
                job = self.store.get(run_id)
        return _with_triage(job)

    def list(self):
        saved = {item['id']: item for item in self.store.list()}
        with self.lock:
            for run_id, job in self.jobs.items():
                saved[run_id] = {key: job.get(key) for key in
                                ('id', 'state', 'progress', 'operatorId', 'profileId', 'startedAt', 'finishedAt')}
                saved[run_id].update(testType=job['options'].get('test_type', 'comparison'),
                                     totals=(job.get('report') or {}).get('totals'),
                                     schemaVersion=job.get('schemaVersion'))
        return sorted(saved.values(), key=lambda item: item.get('startedAt') or '', reverse=True)

    def delete(self, run_id):
        with self.lock:
            if self.active == run_id:
                raise ValueError('진행 중인 실행은 삭제할 수 없습니다. 먼저 중단하세요.')
            self.jobs.pop(run_id, None)
            removed = self.store.delete(run_id)
        if not removed:
            raise ValueError('삭제할 실행 기록을 찾을 수 없습니다.')
        return True

    def delete_finished(self):
        """Clear every run except the active one; evidence folders are removed permanently."""
        removed = 0
        for item in self.list():
            if item['id'] == self.active or item.get('state') in ('running', 'awaiting_auth'):
                continue
            try:
                self.delete(item['id'])
                removed += 1
            except ValueError:
                continue
        return removed

    def begin_close(self):
        with self.lock:
            self.closing = True
            worker = self.worker_thread
            if self.active:
                self.cancel_events[self.active].set()
                self.auth_events[self.active].set()
        return worker

    def close(self):
        worker = self.begin_close()
        if worker and worker is not threading.current_thread():
            worker.join(timeout=30)
        return worker

    def cancel(self, run_id):
        with self.lock:
            if self.active != run_id:
                raise ValueError('진행 중인 실행이 아닙니다.')
            self.cancel_events[run_id].set()
            self.auth_events[run_id].set()
            self.jobs[run_id]['progress'] = '현재 단계 정리 후 중지합니다.'
            self.store.save(self.jobs[run_id])

    def continue_auth(self, run_id):
        with self.lock:
            if self.active != run_id or self.jobs[run_id]['state'] != 'awaiting_auth':
                raise ValueError('로그인 확인을 기다리는 실행이 아닙니다.')
            self.auth_events[run_id].set()

    def _worker(self, job, options):
        run_id = job['id']
        deadline = time.monotonic() + options['timeout_seconds']

        def cancelled():
            # Engine owns its time budget; user cancellation is a different cause.
            return self.cancel_events[run_id].is_set()

        def progress(message):
            with self.lock:
                job['progress'] = str(message)
                self.store.save(job)

        def auth_gate(side, context, url, page=None):
            owned = page is None
            page = context.new_page() if owned else page
            try:
                self.auth_events[run_id].clear()
                page.goto(url, wait_until='domcontentloaded', timeout=20000)
                with self.lock:
                    job.update(state='awaiting_auth', authSide=side,
                               progress=f'{"기준 A" if side == "a" else "비교 B"} 브라우저에서 직접 로그인 후 계속을 누르세요.')
                    self.store.save(job)
                while not self.auth_events[run_id].is_set() and not cancelled() and time.monotonic() < deadline:
                    # Let Playwright dispatch manual navigation and route callbacks.
                    page.wait_for_timeout(150)
                if cancelled():
                    raise InterruptedError('로그인 대기를 취소했습니다.')
                if time.monotonic() >= deadline:
                    raise TimeoutError('AUTH_TIME_LIMIT_REACHED: 수동 로그인 대기 시간 한도에 도달했습니다.')
                with self.lock:
                    job.update(state='running', authSide=None, progress='수동 로그인 이후 검사 준비 중')
                    self.store.save(job)
            finally:
                if owned:
                    page.close()

        try:
            if self.runner is None:
                from qa.engine import run_scan
                runner = run_scan
            else:
                runner = self.runner
            report = runner(options, run_id, self.store.root, progress, cancelled,
                            auth_gate if options.get('manual_login') else None)
            report.setdefault('manifest', {}).update(runtime_manifest())
            report['manifest'].setdefault('testType', options.get('test_type', 'comparison'))
            # Preserve collected evidence if a later report/evaluation stage fails.
            with self.lock:
                job['report'] = report
            from qa.report_validation import validate_report
            validate_report(report)
            from qa.findings import enrich_report
            report = enrich_report(report)
            if options.get('test_type') == 'regression':
                from qa.regression import evaluate_regression
                previous = self.store.get(options['previous_run_id'])
                report['regression'] = evaluate_regression(previous['report'], report)
                report['regression']['previousRunId'] = options['previous_run_id']
                for row in report.get('results', []):
                    evaluation = report['regression'].get('rows', {}).get(str(row['id']))
                    if evaluation:
                        row['regression'] = evaluation
            with self.lock:
                job['report'] = report
                was_cancelled = cancelled() or report.get('cancelled', False) or report['manifest'].get('status') == 'CANCELLED'
                job.update(state='cancelled' if was_cancelled else 'done', authSide=None,
                           progress='중단된 범위와 완료 결과를 저장했습니다.' if was_cancelled else
                                    '검사 종료 · 차단·누락 범위를 확인하세요.' if report['manifest'].get('status') == 'PARTIAL' else '검사 완료',
                           finishedAt=timestamp())
        except InterruptedError as exc:
            with self.lock:
                job.update(state='cancelled', progress='검사를 중단했습니다.', error=str(exc),
                           authSide=None, finishedAt=timestamp())
        except Exception as exc:
            with self.lock:
                job.update(state='error', progress='실행 오류가 발생했습니다.',
                           error=f'{type(exc).__name__}: {str(exc)[:1500]}', authSide=None, finishedAt=timestamp())
        finally:
            with self.lock:
                saved = False
                try:
                    self.store.save(job)
                    saved = True
                except (OSError, ValueError) as exc:
                    job.update(state='error', progress='결과 저장에 실패했습니다. 이 서버를 종료하기 전에 JSON을 내려받으세요.',
                               error=f'EVIDENCE_SAVE_FAILED: {str(exc)[:1000]}', finishedAt=timestamp(), authSide=None)
                finally:
                    self.active = None
                    if saved:
                        self.jobs.pop(run_id, None)
                    self.cancel_events.pop(run_id, None)
                    self.auth_events.pop(run_id, None)


class Server(ThreadingHTTPServer):
    # A review handler may still be committing after serve_forever stops. Join it
    # before releasing directory ownership so a new process cannot lose its write.
    daemon_threads = False
    block_on_close = True

    def __init__(self, address, runs_dir=RUNS, runner=None):
        self.lease = RunDirectoryLease(runs_dir)
        try:
            super().__init__(address, Handler)
            self.service = JobService(runs_dir, runner)
        except Exception:
            self.lease.close()
            if hasattr(self, 'socket'):
                super().server_close()
            raise
        self.session_token = secrets.token_urlsafe(32)
        self.base_origin = f'http://127.0.0.1:{self.server_address[1]}'

    def server_close(self):
        if hasattr(self, 'service'):
            self.service.begin_close()
        super().server_close()
        if not hasattr(self, 'service'):
            return
        worker = self.service.close()
        if worker and worker.is_alive():
            # Keep the directory owned until an in-flight browser finishes cleanup.
            def release_after_worker():
                worker.join()
                self.lease.close()
            threading.Thread(target=release_after_worker, daemon=True).start()
        else:
            self.lease.close()


class Handler(BaseHTTPRequestHandler):
    server: Server

    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def log_message(self, *_):
        # Request URLs and exception messages can contain private data.
        pass

    def send_bytes(self, code, data, content_type='application/json; charset=utf-8', extra_headers=None):
        self.send_response(code)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Referrer-Policy', 'no-referrer')
        script = "'self' 'unsafe-inline'" if self.path.startswith('/demo/') else "'self'"
        self.send_header('Content-Security-Policy', f"default-src 'self'; script-src {script}; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        for key, value in (extra_headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass

    def json_response(self, code, obj, *, redact_payload=True):
        self.send_bytes(code, json.dumps(redact(obj) if redact_payload else obj,
                                        ensure_ascii=False, allow_nan=False).encode('utf-8'))

    def _valid_host(self):
        port = self.server.server_address[1]
        return self.headers.get('Host', '').lower() in (f'127.0.0.1:{port}', f'localhost:{port}')

    def _parse_body(self):
        # Read a bounded body before returning a rejection. Closing a Windows TCP
        # connection with unread POST bytes can reset the response before it arrives.
        try:
            length = int(self.headers.get('Content-Length', '0'))
        except ValueError as exc:
            raise ValueError('요청 길이가 올바르지 않습니다.') from exc
        if not 0 < length <= 80000:
            raise ValueError('요청은 1~80,000바이트여야 합니다.')
        previous_timeout = self.connection.gettimeout()
        self.connection.settimeout(5)
        try:
            raw = self.rfile.read(length)
        finally:
            self.connection.settimeout(previous_timeout)
        if len(raw) != length:
            raise ValueError('요청 데이터가 완전하지 않습니다.')
        if not self._valid_host():
            raise PermissionError('로컬 호스트에서만 사용할 수 있습니다.')
        origin = self.headers.get('Origin')
        port = self.server.server_address[1]
        if origin and origin not in (self.server.base_origin, f'http://localhost:{port}'):
            raise PermissionError('다른 출처의 실행 요청은 허용하지 않습니다.')
        if not secrets.compare_digest(self.headers.get('X-QA-Token', ''), self.server.session_token):
            raise PermissionError('로컬 실행 토큰이 만료되었습니다. 화면을 새로고침하세요.')
        if self.headers.get('Content-Type', '').split(';')[0].strip() != 'application/json':
            raise ValueError('application/json 요청이 필요합니다.')
        try:
            value = json.loads(raw.decode('utf-8'),
                               parse_constant=lambda _: (_ for _ in ()).throw(ValueError('유한한 JSON 숫자가 필요합니다.')))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValueError('JSON 형식이 올바르지 않습니다.') from exc
        if not isinstance(value, dict):
            raise ValueError('JSON 객체가 필요합니다.')
        return value

    def do_GET(self):
        if not self._valid_host():
            return self.json_response(403, {'error': '허용되지 않은 호스트입니다.'})
        path = urlsplit(self.path).path
        try:
            from qa.demo import handle_demo
            if path.startswith('/demo/') and handle_demo(self, path):
                return
            static = {'/': ('index.html', 'text/html'), '/index.html': ('index.html', 'text/html'),
                      '/app.js': ('app.js', 'text/javascript'), '/styles.css': ('styles.css', 'text/css'),
                      '/shell.js': ('shell.js', 'text/javascript'), '/theme-boot.js': ('theme-boot.js', 'text/javascript'),
                      '/m_dashboard.html': ('m_dashboard.html', 'text/html'),
                      '/m_project_settings.html': ('m_project_settings.html', 'text/html'),
                      '/m_workspace.js': ('m_workspace.js', 'text/javascript'),
                      '/m_project_settings.js': ('m_project_settings.js', 'text/javascript'),
                      '/m_rules.html': ('m_rules.html', 'text/html'), '/m_rules.js': ('m_rules.js', 'text/javascript')}
            if path in static:
                name, mime = static[path]
                return self.send_bytes(200, (PUBLIC / name).read_bytes(), mime + '; charset=utf-8')
            if path == '/api/bootstrap':
                # This token is deliberately returned only by a same-origin, no-CORS endpoint.
                return self.json_response(200, {'profiles': profiles(self.server.base_origin),
                                               'sessionToken': self.server.session_token, 'rememberedIds': {}, 'version': __version__,
                                               'schemaVersion': '2.0', 'testTypes': [
                                                   {'id': 'comparison', 'label': '환경 비교 QA'},
                                                   {'id': 'single', 'label': '단일 환경 QA'},
                                                   {'id': 'regression', 'label': '회귀 테스트'},
                                                   {'id': 'conditional', 'label': '조건 기반 UI QA'}]},
                                          redact_payload=False)
            if path == '/api/scans':
                return self.json_response(200, {'scans': self.server.service.list()})
            if path == '/api/credentials':
                from qa.secrets import credentials_status
                return self.json_response(200, credentials_status(), redact_payload=False)
            if path == '/api/projects':
                from qa import projects_db
                # Passwords never leave the store: environments only carry hasPassword.
                return self.json_response(200, {'projects': projects_db.list_projects(), 'storage': projects_db.status()},
                                          redact_payload=False)
            if path.startswith('/api/scans/') and path.endswith('/inventory.csv'):
                run_id = path.removeprefix('/api/scans/').removesuffix('/inventory.csv')
                job = self.server.service.get(run_id)
                if not job or not job.get('report'):
                    return self.json_response(404, {'error': '실행 결과를 찾을 수 없습니다.'})
                if not job['report'].get('inventory'):
                    return self.json_response(409, {'error': '이전 실행에는 환경별 페이지 목록이 없습니다. 새 탐색 실행이 필요합니다.'})
                return self.send_bytes(200, csv_inventory(job), 'text/csv; charset=utf-8',
                                       {'Content-Disposition': f'attachment; filename="qa-pages-{run_id}.csv"'})
            if path.startswith('/api/scans/'):
                suffix = path.removeprefix('/api/scans/')
                extension = '.csv' if suffix.endswith('.csv') else '.json' if suffix.endswith('.json') else ''
                run_id = suffix.removesuffix(extension) if extension else suffix
                job = self.server.service.get(run_id)
                if job is None:
                    return self.json_response(404, {'error': '실행 기록을 찾을 수 없습니다.'})
                if extension == '.csv':
                    if not job.get('report'):
                        return self.json_response(409, {'error': '아직 결과가 없습니다.'})
                    return self.send_bytes(200, csv_report(job), 'text/csv; charset=utf-8',
                                           {'Content-Disposition': f'attachment; filename="qa-{run_id}.csv"'})
                if extension == '.json':
                    return self.send_bytes(200, json.dumps(redact(job), ensure_ascii=False, indent=2).encode('utf-8'),
                                           'application/json; charset=utf-8',
                                           {'Content-Disposition': f'attachment; filename="qa-{run_id}.json"'})
                return self.json_response(200, job)
            if path.startswith('/artifacts/'):
                parts = path.strip('/').split('/')
                if len(parts) != 4 or parts[2] not in ('a', 'b', 'diff'):
                    raise ValueError('증거 경로가 올바르지 않습니다.')
                run_id, side, filename = parts[1:]
                if str(uuid.UUID(run_id)) != run_id or not filename.endswith('.png') or not all(
                        ch.isascii() and (ch.isalnum() or ch in '-_.') for ch in filename):
                    raise ValueError('증거 경로가 올바르지 않습니다.')
                target = (self.server.service.store.root / run_id / side / filename).resolve()
                if not target.is_relative_to(self.server.service.store.root.resolve()) or not target.is_file():
                    return self.json_response(404, {'error': '이미지를 찾을 수 없습니다.'})
                return self.send_bytes(200, target.read_bytes(), 'image/png')
            return self.json_response(404, {'error': '찾을 수 없는 경로입니다.'})
        except StorageError as exc:
            return self.json_response(503, {'error': str(exc)})
        except (ValueError, OSError) as exc:
            return self.json_response(400, {'error': str(exc)})

    def do_HEAD(self):
        if not self._valid_host():
            return self.send_bytes(403, b'')
        if urlsplit(self.path).path.startswith('/demo/'):
            from qa.demo import handle_demo
            if handle_demo(self, urlsplit(self.path).path):
                return
        self.send_response(405)
        self.send_header('Allow', 'GET, POST')
        self.send_header('Content-Length', '0')
        self.end_headers()

    def do_POST(self):
        path = urlsplit(self.path).path
        try:
            # Synthetic mutation traps are isolated test endpoints, never app actions.
            if path.startswith('/demo/'):
                if not self._valid_host():
                    raise PermissionError('로컬 호스트에서만 사용할 수 있습니다.')
                from qa.demo import handle_demo
                if handle_demo(self, path):
                    return
            data = self._parse_body()
            if self.server.service.closing:
                return self.json_response(503, {'error': '서버가 종료 중입니다. 새 서버에서 다시 시도하세요.'})
            if path == '/api/scans':
                options = parse_options(data, self.server.base_origin)
                require_login_credentials(options)
                run_id = self.server.service.start(options)
                return self.json_response(202, {'id': run_id})
            if path == '/api/credentials':
                # The password is written to the git-ignored secrets file and never echoed, logged or stored in runs.
                from qa.secrets import save_shared_credentials
                status = save_shared_credentials(data.get('id'), data.get('pw'))
                data.clear()
                return self.json_response(200, status, redact_payload=False)
            if path == '/api/projects/save':
                from qa import projects_db
                project = projects_db.save_project(data)
                data.clear()
                return self.json_response(200, {'project': project}, redact_payload=False)
            if path == '/api/projects/delete':
                from qa import projects_db
                return self.json_response(200, {'deleted': projects_db.delete_project(data.get('id', ''))})
            if path == '/api/credentials/clear':
                from qa.secrets import clear_shared_credentials
                return self.json_response(200, clear_shared_credentials(), redact_payload=False)
            parts = path.strip('/').split('/')
            if parts == ['api', 'scans', 'delete-finished']:
                return self.json_response(200, {'removed': self.server.service.delete_finished()})
            if len(parts) == 4 and parts[:2] == ['api', 'scans']:
                run_id, action = parts[2:]
                if action == 'delete':
                    self.server.service.delete(run_id)
                    return self.json_response(200, {'ok': True})
                if action == 'cancel':
                    self.server.service.cancel(run_id)
                    return self.json_response(200, {'ok': True})
                if action == 'continue':
                    self.server.service.continue_auth(run_id)
                    return self.json_response(200, {'ok': True})
                if action == 'reviews':
                    review = self.server.service.store.review(run_id, data.get('resultId'),
                        data.get('reviewer'), data.get('status'), data.get('reason'), data.get('expectedRevision'),
                        data.get('issueRef'))
                    return self.json_response(200, {'review': review})
            return self.json_response(404, {'error': '찾을 수 없는 경로입니다.'})
        except PermissionError as exc:
            return self.json_response(403, {'error': str(exc)})
        except ReviewConflict as exc:
            return self.json_response(409, {'error': str(exc)})
        except StorageError as exc:
            return self.json_response(503, {'error': str(exc)})
        except (ValueError, TypeError, KeyError, OSError) as exc:
            return self.json_response(400, {'error': str(exc)})


def require_login_credentials(options):
    """로그인 검사 needs an account for every side it will crawl: say which one is missing before starting."""
    if options.get('auth_mode') != 'login':
        return
    from qa.secrets import load_credentials
    sides = ['a', 'b'] if options.get('test_type') == 'comparison' else ['a']
    key = (options.get('login') or {}).get('accountKey', 'default')
    missing = [side for side in sides
               if load_credentials(side, key, project_ref=(options.get('credential_refs') or {}).get(side)) is None]
    if missing:
        names = ', '.join(options.get('baseline_name' if side == 'a' else 'candidate_name') or side.upper() for side in missing)
        raise ValueError(f'로그인 검사에 쓸 계정이 없습니다: {names}. 4단계 "공용 테스트 계정"에 ID·비밀번호를 저장하거나 '
                         '프로젝트 설정에서 해당 환경의 로그인 ID·비밀번호를 등록하세요. 비로그인으로 검사하려면 인증 상태를 "비로그인"으로 바꾸세요.')


def check_dependencies():
    """Fail loudly at startup instead of at the first scan when the wrong Python is used."""
    import importlib.util
    import sys
    missing = [name for name in ('playwright', 'PIL') if importlib.util.find_spec(name) is None]
    if not missing:
        return True
    print('=' * 72, flush=True)
    print(f'[경고] 현재 Python({sys.executable})에 {", ".join(missing)} 모듈이 없습니다.', flush=True)
    print('       검사를 시작하면 ModuleNotFoundError로 실패합니다. 아래 중 하나로 해결하세요.', flush=True)
    print('       1) 처음이면: setup_windows.bat 실행 후 run_windows.bat 로 시작', flush=True)
    print(r'       2) 직접 실행 시: .\.venv\Scripts\python.exe app.py  (시스템 python 대신 가상환경 사용)', flush=True)
    print(r'       3) 가상환경에 패키지만 없으면: .\.venv\Scripts\python.exe -m pip install -r requirements.txt', flush=True)
    print(r'          이어서: .\.venv\Scripts\python.exe -m playwright install chromium', flush=True)
    print('=' * 72, flush=True)
    return False


def main():
    port = int(os.environ.get('PORT', '3000'))
    check_dependencies()
    server = Server(('127.0.0.1', port))
    print(f'VISANG QA AI {__version__}: {server.base_origin}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        if server.service.active:
            server.service.cancel(server.service.active)
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
