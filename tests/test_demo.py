import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

from qa.demo import demo_profile, get_demo_summary, handle_demo, reset_demo_counts


class DemoHandler(BaseHTTPRequestHandler):
    def _handle(self):
        if not handle_demo(self, self.path):
            self.send_error(404)

    do_GET = _handle
    do_HEAD = _handle
    do_POST = _handle

    def log_message(self, *args):
        pass


class DemoHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), DemoHandler)
        cls.origin = f"http://127.0.0.1:{cls.server.server_port}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def setUp(self):
        reset_demo_counts()

    def request(self, path, method="GET"):
        request = Request(self.origin + path, method=method, data=b"" if method == "POST" else None)
        try:
            with build_opener(ProxyHandler({})).open(request, timeout=3) as response:
                return response.status, response.read().decode("utf-8")
        except HTTPError as response:
            return response.code, response.read().decode("utf-8")

    def test_alias_routes_and_seeded_header_defect(self):
        for path in ("/demo/a/", "/demo/a/search", "/demo/b/", "/demo/b/search.do"):
            status, content = self.request(path)
            self.assertEqual(status, 200)
            self.assertIn('data-qa-demo="web-qa-comparator-v1"', content)
        self.assertIn('id="required-action"', self.request("/demo/a/")[1])
        self.assertNotIn('id="required-action"', self.request("/demo/b/")[1])
        self.assertEqual(self.request("/demo/b/search")[0], 404)
        self.assertEqual(self.request("/demo/a/search.do")[0], 404)

    def test_environment_data_is_distinct_and_resolved_locally(self):
        self.assertIn("Synthetic autumn", self.request("/demo/a/detail?id=a-101")[1])
        self.assertIn("Synthetic spring", self.request("/demo/b/detail.do?id=b-701")[1])
        self.assertIn('id="notice-not-found"', self.request("/demo/b/detail.do?id=a-101")[1])

    def test_search_has_deterministic_results_empty_state_and_escaping(self):
        self.assertIn('data-result-count="1"', self.request("/demo/a/search?q=mathematics")[1])
        self.assertIn('id="search-empty"', self.request("/demo/b/search.do?q=")[1])
        content = self.request("/demo/a/search?q=%3Cscript%3Ealert(1)%3C/script%3E")[1]
        self.assertNotIn("<script>alert(1)</script>", content)
        self.assertIn("&lt;script&gt;", content)

    def test_reads_never_change_mutation_counters(self):
        for path in ("/demo/a/", "/demo/b/", "/demo/a/notice", "/demo/b/input.do", "/demo/meta"):
            self.assertEqual(self.request(path)[0], 200)
        self.assertEqual(sum(sum(v.values()) for v in get_demo_summary()["mutation_counts"].values()), 0)

    def test_traps_count_only_explicit_get_or_post_requests(self):
        # Deliberately exercising an in-memory fixture, never a real application.
        self.assertEqual(self.request("/demo/a/unsafe/delete")[0], 200)
        self.assertEqual(self.request("/demo/b/unsafe/save", "POST")[0], 200)
        self.assertEqual(self.request("/demo/a/unsafe/delete", "HEAD")[0], 405)
        self.assertEqual(get_demo_summary()["mutation_counts"],
                         {"a": {"save": 0, "delete": 1}, "b": {"save": 1, "delete": 0}})

    def test_nontrap_post_is_rejected(self):
        self.assertEqual(self.request("/demo/a/search", "POST")[0], 405)
        self.assertEqual(self.request("/demo/meta", "POST")[0], 405)

    def test_profile_only_allows_known_read_routes(self):
        profile = demo_profile(self.origin)
        options = profile["options"]
        self.assertEqual(profile["baselineUrl"], self.origin + "/demo/a/")
        self.assertEqual(len(options["allowed_paths"]), 10)
        self.assertFalse(any("unsafe" in path or "*" in path for path in options["allowed_paths"]))
        self.assertEqual(options["scenario_ids"], ["demo.search", "demo.input_length", "demo.history"])
        with self.assertRaises(ValueError):
            demo_profile("https://example.invalid")

    def test_summary_identifies_synthetic_ground_truth(self):
        status, content = self.request("/demo/meta")
        summary = json.loads(content)
        self.assertEqual(status, 200)
        self.assertTrue(summary["synthetic"])
        self.assertEqual([item["id"] for item in summary["ground_truth"] if item["label"] == "DEFECT"],
                         ["demo.missing-help-action"])


if __name__ == "__main__":
    unittest.main()
