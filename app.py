"""Web QA Comparator: local HTTP UI and durable scan/review lifecycle.

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
from qa.store import ReportStore, ReviewConflict, redact, timestamp

ROOT = Path(__file__).resolve().parent
RUNS = Path(os.environ.get('QA_RUNS_DIR', str(ROOT / 'runs')))
PUBLIC = ROOT / 'public'


def csv_safe(value):
    value = '' if value is None else str(value)
    if value.lstrip(' \t\r\n').startswith(('=', '+', '-', '@')) or value.startswith(('\t', '\r', '\n')):
        return "'" + value
    return value


def csv_report(job):
    output = io.StringIO(newline='')
    writer = csv.writer(output)
    writer.writerow(['실행 ID', '실행 담당자', '페이지', '영역', '자동 상태', '분류', '차이율(%)',
                     '기준 URL', '비교 URL', '검수 상태', '검수 버전', '검증식 결과'])
    for row in (job.get('report') or {}).get('results', []):
        writer.writerow([csv_safe(value) for value in (
            job['id'], job.get('operatorId'), row.get('key'), row.get('region_id'), row.get('status'),
            ' | '.join(row.get('flags', [])), (row.get('visual') or {}).get('differencePercent'),
            (row.get('baseline') or {}).get('url'), (row.get('candidate') or {}).get('url'),
            (row.get('review') or {}).get('status', 'UNREVIEWED'),
            (row.get('review') or {}).get('revision', 0),
            ' | '.join(f"{check.get('check_id')}: {check.get('status')} ({check.get('reason_code')})"
                       for check in row.get('checks', [])),
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

    def start(self, options):
        with self.lock:
            if self.active:
                raise ReviewConflict('이미 검사가 진행 중입니다. 완료하거나 중지한 후 시작하세요.')
            run_id = str(uuid.uuid4())
            job = {'id': run_id, 'schemaVersion': '1.0', 'state': 'running',
                   'progress': '브라우저 실행 준비 중', 'operatorId': options['operator_id'],
                   'profileId': options['profile_id'], 'startedAt': timestamp(), 'finishedAt': None,
                   'report': None, 'error': None, 'authSide': None, 'options': options}
            self.store.save(job)
            self.jobs[run_id] = job
            self.cancel_events[run_id] = threading.Event()
            self.auth_events[run_id] = threading.Event()
            self.active = run_id
            threading.Thread(target=self._worker, args=(job, options), daemon=True,
                             name='qa-scan-' + run_id[:8]).start()
            return run_id

    def get(self, run_id):
        with self.lock:
            if run_id == self.active:
                # Copy before serializing so the HTTP thread sees a consistent snapshot.
                return redact(json.loads(json.dumps(self.jobs[run_id])))
            return self.store.get(run_id)

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
            return self.cancel_events[run_id].is_set() or time.monotonic() >= deadline

        def progress(message):
            with self.lock:
                job['progress'] = str(message)
                self.store.save(job)

        def auth_gate(side, context, url):
            page = context.new_page()
            try:
                self.auth_events[run_id].clear()
                page.goto(url, wait_until='domcontentloaded', timeout=20000)
                with self.lock:
                    job.update(state='awaiting_auth', authSide=side,
                               progress=f'{"기준 A" if side == "a" else "비교 B"} 브라우저에서 직접 로그인 후 계속을 누르세요.')
                    self.store.save(job)
                while not self.auth_events[run_id].is_set() and not cancelled():
                    # Let Playwright dispatch manual navigation and route callbacks.
                    page.wait_for_timeout(150)
                if cancelled():
                    raise InterruptedError('로그인 대기가 취소되거나 실행 시간 한도에 도달했습니다.')
                with self.lock:
                    job.update(state='running', authSide=None, progress='수동 로그인 이후 검사 준비 중')
                    self.store.save(job)
            finally:
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
            with self.lock:
                job['report'] = report
                was_cancelled = cancelled() or report.get('cancelled', False)
                job.update(state='cancelled' if was_cancelled else 'done', authSide=None,
                           progress='중단된 범위와 완료 결과를 저장했습니다.' if was_cancelled else '검사 완료',
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
                try:
                    self.store.save(job)
                finally:
                    self.active = None
                    self.jobs.pop(run_id, None)
                    self.cancel_events.pop(run_id, None)
                    self.auth_events.pop(run_id, None)


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, runs_dir=RUNS, runner=None):
        super().__init__(address, Handler)
        self.service = JobService(runs_dir, runner)
        self.session_token = secrets.token_urlsafe(32)
        self.base_origin = f'http://127.0.0.1:{self.server_address[1]}'


class Handler(BaseHTTPRequestHandler):
    server: Server

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
                      '/app.js': ('app.js', 'text/javascript'), '/styles.css': ('styles.css', 'text/css')}
            if path in static:
                name, mime = static[path]
                return self.send_bytes(200, (PUBLIC / name).read_bytes(), mime + '; charset=utf-8')
            if path == '/api/bootstrap':
                # This token is deliberately returned only by a same-origin, no-CORS endpoint.
                return self.json_response(200, {'profiles': profiles(self.server.base_origin),
                                               'sessionToken': self.server.session_token, 'rememberedIds': {}},
                                          redact_payload=False)
            if path == '/api/scans':
                return self.json_response(200, {'scans': self.server.service.store.list()})
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
            if path == '/api/scans':
                options = parse_options(data, self.server.base_origin)
                run_id = self.server.service.start(options)
                return self.json_response(202, {'id': run_id})
            parts = path.strip('/').split('/')
            if len(parts) == 4 and parts[:2] == ['api', 'scans']:
                run_id, action = parts[2:]
                if action == 'cancel':
                    self.server.service.cancel(run_id)
                    return self.json_response(200, {'ok': True})
                if action == 'continue':
                    self.server.service.continue_auth(run_id)
                    return self.json_response(200, {'ok': True})
                if action == 'reviews':
                    review = self.server.service.store.review(run_id, data.get('resultId'),
                        data.get('reviewer'), data.get('status'), data.get('reason'), data.get('expectedRevision'))
                    return self.json_response(200, {'review': review})
            return self.json_response(404, {'error': '찾을 수 없는 경로입니다.'})
        except PermissionError as exc:
            return self.json_response(403, {'error': str(exc)})
        except ReviewConflict as exc:
            return self.json_response(409, {'error': str(exc)})
        except (ValueError, TypeError, KeyError, OSError) as exc:
            return self.json_response(400, {'error': str(exc)})


def main():
    port = int(os.environ.get('PORT', '3000'))
    server = Server(('127.0.0.1', port))
    print(f'Web QA Comparator {__version__}: {server.base_origin}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        if server.service.active:
            server.service.cancel(server.service.active)
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
