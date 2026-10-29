import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from qa.demo import get_demo_summary, handle_demo, reset_demo_counts
from qa.scenarios import SCENARIO_IDS, _DemoScenario, run_scenarios


class _NoInteractionPage:
    url = "https://example.invalid/"

    def locator(self, selector):
        raise AssertionError("Live pages must not be inspected by demo-only scenarios")


class ScenarioGuardTests(unittest.TestCase):
    def test_live_target_is_skipped_without_interaction(self):
        results = run_scenarios(_NoInteractionPage(), SCENARIO_IDS, "a", {}, lambda: False)
        self.assertEqual(len(results), 3)
        self.assertTrue(all(item["status"] == "SKIP" and item["reason_code"] == "DEMO_ONLY_SCENARIO" for item in results))

    def test_unknown_scenario_is_not_guessed(self):
        result = run_scenarios(_NoInteractionPage(), ["live.search"], "a", {}, lambda: False)[0]
        self.assertEqual((result["status"], result["reason_code"]), ("SKIP", "SCENARIO_NOT_REGISTERED"))

    def test_cancellation_prevents_page_interaction(self):
        results = run_scenarios(_NoInteractionPage(), SCENARIO_IDS, "a", {}, lambda: True)
        self.assertTrue(all(item["reason_code"] == "CANCELLED" for item in results))

    def test_completion_hook_records_only_successful_actions(self):
        completed = []
        runner = _DemoScenario(None, "demo.search", "http://127.0.0.1:3000", "a",
                               {"_action_completed": completed.append}, lambda: False)
        self.assertEqual(runner.action("fill", lambda: "done", selector="#search-input"), "done")
        self.assertEqual(len(completed), 1)
        self.assertEqual(completed[0]["scenario_id"], "demo.search")
        def failure():
            raise RuntimeError("Synthetic action failed")
        with self.assertRaises(RuntimeError):
            runner.action("click", failure, selector="#search-submit")
        self.assertEqual(len(completed), 1)


class _DemoHandler(BaseHTTPRequestHandler):
    def _handle(self):
        if not handle_demo(self, self.path):
            self.send_error(404)

    do_GET = _handle
    do_POST = _handle

    def log_message(self, *args):
        pass


class ScenarioBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise unittest.SkipTest("Playwright is not installed; browser assertions were not run")
        cls.playwright = sync_playwright().start()
        try:
            cls.browser = cls.playwright.chromium.launch(headless=True, timeout=10000)
        except Exception:
            cls.playwright.stop()
            raise unittest.SkipTest("Chromium is unavailable; browser assertions were not run")
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _DemoHandler)
        cls.origin = f"http://127.0.0.1:{cls.server.server_port}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self):
        reset_demo_counts()
        self.context = self.browser.new_context()
        # Any accidental external request causes an abort, never a real-site visit.
        self.context.route("**/*", lambda route: route.continue_() if route.request.url.startswith(self.origin + "/") else route.abort())
        self.page = self.context.new_page()

    def tearDown(self):
        self.context.close()

    def test_both_sides_pass_registered_contracts_and_restore_entry(self):
        for side in ("a", "b"):
            entry = self.origin + f"/demo/{side}/"
            self.page.goto(entry)
            guarded = []
            def allow(action):
                guarded.append(action)
                return True
            results = run_scenarios(self.page, SCENARIO_IDS, side, {"_action_guard": allow}, lambda: False)
            self.assertEqual(len(results), 15, results)
            self.assertTrue(all(item["status"] == "PASS" for item in results), results)
            self.assertEqual(self.page.url, entry)
            self.assertTrue(all(action["scenario_id"] in SCENARIO_IDS for action in guarded))
            self.assertIn("press", {action["kind"] for action in guarded})
            self.assertIn("forward", {action["kind"] for action in guarded})
        self.assertEqual(sum(sum(v.values()) for v in get_demo_summary()["mutation_counts"].values()), 0)

    def test_action_policy_can_deny_before_navigation(self):
        entry = self.origin + "/demo/a/"
        self.page.goto(entry)
        results = run_scenarios(self.page, ["demo.search"], "a", {"_action_guard": lambda action: False}, lambda: False)
        self.assertEqual(self.page.url, entry)
        self.assertEqual(results[0]["status"], "SKIP")
        self.assertEqual(results[0]["reason_code"], "POLICY_OR_BUDGET_BLOCKED")

    def test_environment_mismatch_is_error_without_action(self):
        self.page.goto(self.origin + "/demo/a/")
        results = run_scenarios(self.page, ["demo.search"], "b", {}, lambda: False)
        self.assertEqual(results[0]["reason_code"], "ENVIRONMENT_MISMATCH")
        self.assertEqual(results[0]["status"], "ERROR")

    def test_expired_scenario_budget_skips_without_action(self):
        entry = self.origin + "/demo/a/"
        self.page.goto(entry)
        results = run_scenarios(self.page, ["demo.history"], "a", {"scenario_max_seconds": 0}, lambda: False)
        self.assertEqual(results[0]["reason_code"], "SCENARIO_TIME_LIMIT")
        self.assertEqual(self.page.url, entry)


if __name__ == "__main__":
    unittest.main()
