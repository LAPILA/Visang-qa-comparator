import json
from pathlib import Path
import tempfile
import threading
import unittest
import uuid
from urllib.parse import parse_qsl, urlsplit

from qa.store import ReportStore, ReviewConflict, RunDirectoryLease, redact


_TMP_ROOT = Path(__file__).resolve().parents[1] / "output" / "tmp"


class ReportStoreTests(unittest.TestCase):
    def setUp(self):
        _TMP_ROOT.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=_TMP_ROOT)
        self.addCleanup(self.temp.cleanup)
        self.store = ReportStore(self.temp.name)
        self.run_id = str(uuid.uuid4())

    def job(self, state="done"):
        return {"id": self.run_id, "state": state, "operatorId": "QA-A", "profileId": "synthetic-demo",
                "startedAt": "2026-10-30T00:00:00+00:00", "finishedAt": None, "authSide": "a",
                "report": {"manifest": {"schema_version": "1.0"}, "totals": {"FAIL": 1},
                           "results": [{"id": "row-1", "status": "FAIL", "key": "home",
                                        "checks": [{"check_id": "required-button", "status": "FAIL"}],
                                        "visual": {"differencePercent": 0}}]}}

    def test_restart_preserves_results_manifest_and_zero(self):
        expected = self.job()
        self.store.save(expected)
        reopened = ReportStore(self.temp.name)
        self.assertEqual(reopened.get(self.run_id), expected)
        self.assertEqual(reopened.list()[0]["operatorId"], "QA-A")
        self.assertEqual(reopened.get(self.run_id)["report"]["results"][0]["visual"]["differencePercent"], 0)
        self.assertEqual(list(Path(self.temp.name).glob("**/*.tmp")), [])

    def test_interrupted_runs_recover_as_error_without_losing_partial_evidence(self):
        for state in ("running", "awaiting_auth"):
            with self.subTest(state=state):
                self.store.save(self.job(state))
                reopened = ReportStore(self.temp.name)
                reopened.recover()
                recovered = reopened.get(self.run_id)
                self.assertEqual(recovered["state"], "error")
                self.assertEqual(recovered["error"], "PROCESS_INTERRUPTED")
                self.assertIsNone(recovered["authSide"])
                self.assertEqual(recovered["report"]["results"][0]["status"], "FAIL")
                self.assertIsNotNone(recovered["finishedAt"])

    def test_reviews_track_actor_history_and_never_overwrite_automatic_status(self):
        self.store.save(self.job())
        first = self.store.review(self.run_id, "row-1", " QA-A ", "BUG_CONFIRMED", "Reproduced locally", 0)
        second = self.store.review(self.run_id, "row-1", "QA-B", "RETEST_REQUIRED", "Retest after patch", 1)
        self.assertEqual(first["revision"], 1)
        self.assertEqual(second["revision"], 2)
        self.assertEqual([event["reviewer"] for event in second["events"]], ["QA-A", "QA-B"])
        self.assertEqual(second["events"][1]["previous"], "BUG_CONFIRMED")
        row = ReportStore(self.temp.name).get(self.run_id)["report"]["results"][0]
        self.assertEqual(row["status"], "FAIL")
        self.assertEqual(row["checks"][0]["status"], "FAIL")
        self.assertEqual(row["review"]["revision"], 2)

    def test_stale_review_revision_fails_without_lost_update(self):
        self.store.save(self.job())
        expected = self.store.review(self.run_id, "row-1", "QA-A", "BUG_CONFIRMED", "Evidence verified", 0)
        with self.assertRaises(ReviewConflict):
            self.store.review(self.run_id, "row-1", "QA-B", "FALSE_POSITIVE", "Stale client", 0)
        self.assertEqual(self.store.get(self.run_id)["report"]["results"][0]["review"], expected)

    def test_simultaneous_review_has_one_winner_and_one_conflict(self):
        self.store.save(self.job())
        barrier = threading.Barrier(2)
        outcomes = []

        def review(reviewer):
            barrier.wait(timeout=2)
            try:
                self.store.review(self.run_id, "row-1", reviewer, "BUG_CONFIRMED", "Concurrent review", 0)
                outcomes.append("saved")
            except ReviewConflict:
                outcomes.append("conflict")

        threads = [threading.Thread(target=review, args=(reviewer,)) for reviewer in ("QA-A", "QA-B")]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=3)
        self.assertCountEqual(outcomes, ["saved", "conflict"])
        current = self.store.get(self.run_id)["report"]["results"][0]["review"]
        self.assertEqual(current["revision"], 1)
        self.assertEqual(len(current["events"]), 1)

    def test_review_validation_and_running_state(self):
        self.store.save(self.job())
        for reviewer, status, reason, revision in [("", "VERIFIED_OK", "reason", 0),
                ("QA", "PASS", "reason", 0), ("QA", "VERIFIED_OK", "", 0),
                ("QA", "VERIFIED_OK", "reason", True), ("QA", "VERIFIED_OK", "reason", "0")]:
            with self.subTest(status=status, revision=revision), self.assertRaises(ValueError):
                self.store.review(self.run_id, "row-1", reviewer, status, reason, revision)
        self.store.save(self.job("running"))
        with self.assertRaises(ValueError):
            self.store.review(self.run_id, "row-1", "QA", "VERIFIED_OK", "reason", 0)

    def test_secret_redaction_applies_before_disk_write(self):
        job = self.job()
        job["options"] = {"password": "fixture-password", "nested": {"Authorization": "fixture-auth"},
                          "url": "https://user:fixture-userpass@example.invalid/a?access_token=fixture-token&query=allowed#/view?session_id=fixture-session"}
        job["error"] = "Synthetic failure: Bearer fixture-bearer"
        self.store.save(job)
        raw = (Path(self.temp.name) / self.run_id / "report.json").read_text(encoding="utf-8")
        for secret in ("fixture-password", "fixture-auth", "fixture-userpass", "fixture-token", "fixture-session", "fixture-bearer"):
            self.assertNotIn(secret, raw)
        self.assertIn("allowed", raw)
        self.assertIn("[REDACTED]", raw)
        self.assertEqual(job["options"]["password"], "fixture-password", "Redaction must not mutate caller input")

    def test_generic_token_and_oauth_fragment_are_redacted_without_losing_hash_route(self):
        values = {
            "token": "fixture-nested-token",
            "query_url": "https://example.invalid/?token=fixture-query-token&search=visible",
            "oauth_url": "https://example.invalid/callback#access_token=fixture-fragment-token&state=visible",
            "route_url": "https://example.invalid/#/search?q=visible&token=fixture-route-token",
        }
        serialized = json.dumps(redact(values))
        for secret in ("fixture-nested-token", "fixture-query-token", "fixture-fragment-token", "fixture-route-token"):
            self.assertNotIn(secret, serialized)
        self.assertIn("#/search?", serialized)
        self.assertIn("visible", serialized)

    def test_redaction_preserves_safe_query_order_repeated_keys_and_fragment(self):
        original = "https://example.invalid/a?token=fixture-secret&tag=first&tag=second&empty=#/search?q=visible"
        safe = urlsplit(redact(original))
        self.assertEqual(parse_qsl(safe.query, keep_blank_values=True),
                         [("token", "[REDACTED]"), ("tag", "first"), ("tag", "second"), ("empty", "")])
        self.assertEqual(safe.fragment, "/search?q=visible")
        oauth = urlsplit(redact("https://example.invalid/callback#access_token=fixture-secret&state=visible"))
        self.assertEqual(parse_qsl(oauth.fragment), [("access_token", "[REDACTED]"), ("state", "visible")])

    def test_persisted_safe_urls_preserve_exact_encoding_for_next_mapping_run(self):
        url = 'https://example.invalid/find?q=hello%20world&tag=b&tag=a#/search?label=REDACTED%20text'
        self.assertEqual(redact(url), url)
        job = self.job()
        job['options'] = {'baseline_url': url}
        job['report']['inventory'] = {'environments': [{'seedUrl': url, 'pages': [{'url': url}]}]}
        self.store.save(job)
        reopened = self.store.get(self.run_id)
        self.assertEqual(reopened['options']['baseline_url'], url)
        self.assertEqual(reopened['report']['inventory']['environments'][0]['pages'][0]['url'], url)

    def test_invalid_ids_corrupt_json_and_nonfinite_save_are_explicit_errors(self):
        for run_id in ("../outside", "", None, "row-1"):
            with self.subTest(run_id=run_id), self.assertRaises(ValueError):
                self.store.get(run_id)
        self.store.save(self.job())
        path = Path(self.temp.name) / self.run_id / "report.json"
        original = path.read_bytes()
        job = self.job()
        job["invalid"] = float("nan")
        with self.assertRaises(ValueError):
            self.store.save(job)
        self.assertEqual(path.read_bytes(), original)
        path.write_text("{broken", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.store.get(self.run_id)

    def test_issue_links_are_audited_with_review_revision_and_automatic_state_preserved(self):
        self.store.save(self.job())
        first = self.store.review(self.run_id, 'row-1', 'QA-A', 'BUG_CONFIRMED', 'Confirmed', 0,
                                  'https://issues.example.invalid/QA-12')
        self.assertEqual(first['issueRef'], 'https://issues.example.invalid/QA-12')
        self.assertEqual(first['events'][0]['issueRef'], first['issueRef'])
        self.assertEqual(self.store.get(self.run_id)['report']['totals']['linkedIssues'], 1)
        second = self.store.review(self.run_id, 'row-1', 'QA-B', 'RETEST_REQUIRED', 'Retest', 1)
        self.assertEqual(second['issueRef'], first['issueRef'])
        with self.assertRaises(ReviewConflict):
            self.store.review(self.run_id, 'row-1', 'QA-A', 'FALSE_POSITIVE', 'Stale', 1, '')
        third = self.store.review(self.run_id, 'row-1', 'QA-B', 'VERIFIED_OK', 'Retested', 2, '')
        self.assertEqual(third['issueRef'], '')
        report = self.store.get(self.run_id)['report']
        self.assertEqual(report['totals']['linkedIssues'], 0)
        self.assertEqual(report['results'][0]['status'], 'FAIL')
        for issue in ('javascript:alert(1)', 'https://user:pass@host.invalid/issue',
                      'https://host.invalid/issue?token=secret', 42):
            with self.subTest(issue=issue), self.assertRaises(ValueError):
                self.store.review(self.run_id, 'row-1', 'QA', 'BUG_CONFIRMED', 'Reason', 3, issue)

    def test_unknown_major_schema_is_rejected_without_rewriting_legacy_reports(self):
        job = self.job()
        job['schemaVersion'] = '1.0'
        self.store.save(job)
        self.assertEqual(self.store.get(self.run_id), job)
        job['schemaVersion'] = '2.0'
        self.store.save(job)
        self.assertEqual(self.store.get(self.run_id), job)
        job['schemaVersion'] = '999.0'
        self.store.save(job)
        with self.assertRaisesRegex(ValueError, '스키마'):
            self.store.get(self.run_id)

    def test_report_directory_has_one_server_owner_and_is_reusable_after_release(self):
        lease = RunDirectoryLease(self.temp.name)
        try:
            with self.assertRaisesRegex(ValueError, '다른 서버'):
                RunDirectoryLease(self.temp.name)
        finally:
            lease.close()
        new_owner = RunDirectoryLease(self.temp.name)
        new_owner.close()


if __name__ == "__main__":
    unittest.main()
