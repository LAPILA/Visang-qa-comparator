"""Local reproduction: a legacy hash home and a differently titled new home."""
import tempfile
import threading
import unittest
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from qa.config import parse_options
from qa.engine import run_scan


class StartPageBrowserTests(unittest.TestCase):
    def test_selected_hash_and_path_homes_compare_with_scoped_static_dependency(self):
        class Fixture(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_GET(self):
                if self.path == '/dependency.js':
                    data, mime = b'window.qaDependencyReady = true;', 'text/javascript'
                else:
                    old = self.path.startswith('/old/')
                    title = 'Legacy teaching home' if old else 'New teaching home'
                    redirect = 'setTimeout(() => { location.hash="/coverPage"; }, 30);' if old else ''
                    html = f'''<!doctype html><html><head><title>{title}</title>
                        <script src="http://localhost:{self.server.server_port}/dependency.js"></script>
                        <script>{redirect}if (!window.qaDependencyReady) throw new Error("Required dependency missing");</script>
                        </head><body><main><h2>Teaching home</h2><button>Materials</button></main></body></html>'''
                    data, mime = html.encode(), 'text/html'
                self.send_response(200)
                self.send_header('Content-Type', mime)
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        server = ThreadingHTTPServer(('127.0.0.1', 0), Fixture)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        origin = f'http://127.0.0.1:{server.server_port}'
        temporary_root = Path(__file__).resolve().parents[1] / 'output' / 'tmp'
        temporary_root.mkdir(parents=True, exist_ok=True)
        try:
            with tempfile.TemporaryDirectory(dir=temporary_root) as folder:
                common = {'profileId': 'custom', 'baselineUrl': origin + '/old/#/',
                          'candidateUrl': origin + '/new/', 'maxPages': 1, 'maxDepth': 0,
                          'maxActions': 0, 'mode': 'visual', 'timeoutSeconds': 30}

                def scan(**changes):
                    return run_scan(parse_options({**common, **changes}, origin), str(uuid.uuid4()),
                                    folder, lambda _: None, lambda: False)

                blocked = scan()
                self.assertEqual(len(blocked['results']), 1)
                row = blocked['results'][0]
                self.assertEqual(row['match']['method'], 'SELECTED_START_PAGES')
                self.assertTrue(row['baseline']['finalUrl'].endswith('#/coverPage'),
                                {'url': row['baseline']['finalUrl'], 'checks': row['checks'], 'issues': row['baseline']['issues']})
                self.assertIsNotNone(row['baseline']['screenshot'])
                self.assertIsNotNone(row['candidate']['screenshot'])
                self.assertEqual(row['status'], 'REVIEW', 'A selected match must not hide policy interference')
                self.assertTrue(any(issue['category'] == 'JS_ERROR_AFTER_POLICY_BLOCK'
                                    for issue in row['baseline']['issues']))
                self.assertIsInstance(row['visual']['differencePercent'], (int, float))

                approved = scan(resourceHosts=[f'localhost:{server.server_port}'])
                self.assertEqual(len(approved['results']), 1)
                self.assertEqual(approved['results'][0]['status'], 'PASS')
                self.assertEqual(approved['results'][0]['visual']['differencePercent'], 0)
                self.assertEqual(approved['coverage']['blockedRequests'], [])
                self.assertNotEqual(approved['results'][0]['baseline']['title'], approved['results'][0]['candidate']['title'])

                independent = scan(pairStartPages=False, resourceHosts=[f'localhost:{server.server_port}'])
                self.assertEqual(len(independent['results']), 2)
                self.assertTrue(all(not row['match']['approved'] for row in independent['results']))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)


if __name__ == '__main__':
    unittest.main()
