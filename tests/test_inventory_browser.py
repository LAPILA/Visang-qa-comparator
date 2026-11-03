"""Bounded, read-only site discovery with different legacy/new route families."""
import tempfile
import threading
import unittest
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from qa.config import parse_options
from qa.engine import run_scan


class InventoryBrowserTests(unittest.TestCase):
    def test_independent_catalogues_find_different_routes_without_visiting_mutation_traps(self):
        hits = []

        class Fixture(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_GET(self):
                hits.append(self.path)
                old = self.path.startswith('/old/')
                links = [('/old/#/notices' if old else '/new/announcements', '공지사항'),
                         ('/old/#/materials' if old else '/new/resources', '교과자료'),
                         ('/delete?id=1', '삭제'), ('/account/profile', '내 계정'),
                         ('/export.csv', '자료 내려받기'), ('/api/list', 'API')]
                nav = ''.join(f'<a href="{url}">{label}</a>' for url, label in links)
                if old:
                    heading = '''<script>document.getElementById('page-heading').textContent =
                        location.hash.includes('notices')?'이전 알림':location.hash.includes('materials')?'이전 자료':'이전 홈';</script>'''
                    title = 'Legacy'
                else:
                    title = 'New'
                    heading = ''
                text = '새 공지' if 'announcements' in self.path else '새 자료' if 'resources' in self.path else '새 홈'
                heading_tag = 'h2' if old else 'h1'
                body = f'''<!doctype html><html><head><meta charset="utf-8"><title>{title}</title></head>
                    <body><nav>{nav}</nav><main><{heading_tag} id="page-heading">{text}</{heading_tag}>
                    <form><input name="keyword" aria-label="검색어"><button type="button">검색</button></form>
                    </main>{heading}</body></html>'''.encode()
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        server = ThreadingHTTPServer(('127.0.0.1', 0), Fixture)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        origin = f'http://127.0.0.1:{server.server_port}'
        temp_root = Path(__file__).resolve().parents[1] / 'output' / 'tmp'
        temp_root.mkdir(parents=True, exist_ok=True)
        try:
            with tempfile.TemporaryDirectory(dir=temp_root) as directory:
                options = parse_options({'profileId': 'custom', 'baselineName': 'DEV1', 'candidateName': 'DEV2',
                    'baselineUrl': origin + '/old/#/', 'candidateUrl': origin + '/new/',
                    'crawlScope': 'same_origin_readonly', 'mode': 'discovery',
                    'maxPages': 3, 'maxDepth': 1, 'maxActions': 0, 'timeoutSeconds': 60}, origin)
                report = run_scan(options, str(uuid.uuid4()), directory, lambda _: None, lambda: False)
                self.assertEqual((report['totals']['baselineVisited'], report['totals']['candidateVisited']), (3, 3))
                inventory = report['inventory']
                self.assertEqual([env['name'] for env in inventory['environments']], ['DEV1', 'DEV2'])
                self.assertTrue(all(env['visitedCount'] == 3 for env in inventory['environments']))
                a, b = inventory['environments']
                self.assertIn('/old/#/notices', [page['pageKey'] for page in a['pages']])
                self.assertIn('/new/announcements', [page['pageKey'] for page in b['pages']])
                notice_a = next(page for page in a['pages'] if page['pageKey'] == '/old/#/notices')
                self.assertEqual(notice_a['navigationTrail'], ['start-page', '공지사항'])
                self.assertTrue(notice_a['signature']['formFields'])
                self.assertEqual(report['totals']['attemptedActions'], 0)
                self.assertEqual(report['totals']['error'], 0)
                self.assertFalse(any(path.startswith(('/delete', '/account', '/export', '/api/')) for path in hits), hits)
                candidate = next(match for match in inventory['matches'] if match.get('baselineKey') == '/old/#/notices')
                self.assertEqual(candidate['candidateKey'], '/new/announcements')
                self.assertEqual(candidate['method'], 'SEMANTIC_CANDIDATE')
                self.assertFalse(candidate['approved'])
                self.assertTrue(candidate['evidence'])
                self.assertTrue(all(row['visual'] is None for row in report['results']))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)


if __name__ == '__main__':
    unittest.main()
