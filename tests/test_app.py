import csv
import http.client
import io
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
import uuid
from unittest.mock import patch

from app import Server, csv_report, csv_safe
from qa.store import ReviewConflict


_TMP_ROOT = Path(__file__).resolve().parents[1] / "output" / "tmp"


def _report():
    return {"manifest": {"synthetic": True}, "totals": {"PASS": 1}, "results": [
        {"id": "row-1", "key": "home", "region_id": "main", "status": "PASS", "flags": [],
         "baseline": {"url": "http://127.0.0.1/demo/a/"}, "candidate": {"url": "http://127.0.0.1/demo/b/"},
         "visual": {"differencePercent": 0}, "checks": [{"check_id": "fake-local", "status": "PASS", "reason_code": "ASSERTION_SATISFIED"}]}]}


class _FakePage:
    def __init__(self):
        self.closed = False

    def goto(self, *args, **kwargs):
        pass

    def wait_for_timeout(self, _):
        threading.Event().wait(0.01)

    def close(self):
        self.closed = True


class _FakeContext:
    def __init__(self):
        self.page = _FakePage()

    def new_page(self):
        return self.page


class LocalHTTPAppTests(unittest.TestCase):
    def setUp(self):
        _TMP_ROOT.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=_TMP_ROOT)
        self.mode = "complete"
        self.runner_started = threading.Event()
        self.fake_context = _FakeContext()

        def runner(options, run_id, root, progress, cancelled, auth_gate):
            self.runner_started.set()
            progress("Synthetic test runner")
            if self.mode == "auth":
                auth_gate("a", self.fake_context, options["baseline_url"])
            elif self.mode == "wait-cancel":
                deadline = time.monotonic() + 3
                while not cancelled() and time.monotonic() < deadline:
                    threading.Event().wait(0.01)
            elif self.mode == "error":
                raise RuntimeError("Synthetic runner error")
            report = _report()
            if self.mode == 'invalid-report':
                report['results'][0]['status'] = 'SUCCESS'
            report["cancelled"] = cancelled()
            return report

        self.server = Server(("127.0.0.1", 0), runs_dir=Path(self.temp.name), runner=runner)
        self.port = self.server.server_port
        self.origin = f"http://127.0.0.1:{self.port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        status, bootstrap, _ = self.request("GET", "/api/bootstrap", authorized=False)
        self.assertEqual(status, 200)
        self.token = bootstrap["sessionToken"]

    def tearDown(self):
        active = self.server.service.active
        if active:
            self.server.service.cancel(active)
            deadline = time.monotonic() + 3
            while self.server.service.active and time.monotonic() < deadline:
                threading.Event().wait(0.01)
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temp.cleanup()

    def request(self, method, path, body=None, headers=None, authorized=True, raw=None):
        request_headers = {"Host": f"127.0.0.1:{self.port}"}
        if method == "POST":
            request_headers["Content-Type"] = "application/json"
            request_headers["Origin"] = self.origin
            if authorized:
                request_headers["X-QA-Token"] = self.token
        request_headers.update(headers or {})
        data = raw if raw is not None else json.dumps({} if body is None else body).encode("utf-8") if method == "POST" else None
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=4)
        try:
            connection.request(method, path, body=data, headers=request_headers)
            response = connection.getresponse()
            payload = response.read()
            response_headers = dict(response.getheaders())
            if response_headers.get("Content-Type", "").startswith("application/json"):
                payload = json.loads(payload)
            return response.status, payload, response_headers
        finally:
            connection.close()

    def start(self, **changes):
        return self.request("POST", "/api/scans", {"profileId": "synthetic-demo", "operatorId": "QA-A", **changes})

    def await_state(self, run_id, states):
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            status, job, _ = self.request("GET", "/api/scans/" + run_id)
            self.assertEqual(status, 200)
            if job["state"] in states:
                return job
            threading.Event().wait(0.01)
        self.fail(f"Run did not reach {states}")

    def test_bootstrap_no_cors_and_write_csrf_origin_host_checks(self):
        status, bootstrap, headers = self.request("GET", "/api/bootstrap", authorized=False)
        self.assertEqual(status, 200)
        self.assertTrue(bootstrap["sessionToken"])
        self.assertEqual(bootstrap["rememberedIds"], {})
        self.assertNotIn("Access-Control-Allow-Origin", headers)
        self.assertEqual(headers["Cache-Control"], "no-store")
        payload = {"profileId": "synthetic-demo"}
        self.assertEqual(self.request("POST", "/api/scans", payload, authorized=False)[0], 403)
        self.assertEqual(self.request("POST", "/api/scans", payload, headers={"X-QA-Token": "wrong-token"})[0], 403)
        self.assertEqual(self.request("POST", "/api/scans", payload, headers={"Origin": "https://outside.invalid"})[0], 403)
        self.assertEqual(self.request("POST", "/api/scans", payload, headers={"Host": "outside.invalid"})[0], 403)
        self.assertEqual(self.request("GET", "/api/bootstrap", headers={"Host": "outside.invalid"})[0], 403)
        self.assertFalse(self.runner_started.is_set())

    def test_malformed_nonfinite_and_invalid_configuration_return_400(self):
        for raw in (b"{", b"[]", b'{"maxPages":NaN}', b'{"maxPages":Infinity}',
                    b'{"profileId":"synthetic-demo","maxPages":1e309}'):
            with self.subTest(raw=raw):
                self.assertEqual(self.request("POST", "/api/scans", raw=raw)[0], 400)
        for body in ({"profileId": "secondary-mobile", "candidateEnvironmentId": "unknown-environment"},
                     {"profileId": "synthetic-demo", "baselineUrl": "https://outside.invalid/"},
                     {"profileId": "synthetic-demo", "password": "synthetic-password"}):
            with self.subTest(body=body):
                self.assertEqual(self.request("POST", "/api/scans", body)[0], 400)
        self.assertFalse(self.runner_started.is_set())

    def test_completed_run_persists_and_exports_without_browser(self):
        status, created, _ = self.start()
        self.assertEqual(status, 202)
        job = self.await_state(created["id"], {"done", "error"})
        self.assertEqual(job["state"], "done", job)
        self.assertEqual(job["report"]["results"][0]["status"], "PASS")
        self.assertIn("source_sha256", job["report"]["manifest"])
        self.assertEqual(self.request("GET", f'/api/scans/{created["id"]}.csv')[0], 200)
        self.assertEqual(self.request("GET", f'/api/scans/{created["id"]}.json')[0], 200)
        status, listed, _ = self.request("GET", "/api/scans")
        self.assertEqual(status, 200)
        self.assertEqual(listed["scans"][0]["operatorId"], "QA-A")

    def test_registered_environment_ids_resolve_and_persist_before_fake_runner(self):
        status, created, _ = self.request('POST', '/api/scans', {
            'profileId': 'elementary-mobile', 'operatorId': 'QA-registry',
            'baselineEnvironmentId': 'legacy-dev', 'candidateEnvironmentId': 'vibe-dev'})
        self.assertEqual(status, 202)
        job = self.await_state(created['id'], {'done', 'error'})
        self.assertEqual(job['state'], 'done', job.get('error'))
        self.assertEqual(job['options']['baseline_url'], 'https://me-dev.vivasam.com/#/')
        self.assertEqual(job['options']['candidate_url'], 'https://dev2-me.vivasam.com/')
        self.assertEqual(job['options']['baseline_environment_id'], 'legacy-dev')
        self.assertEqual(job['options']['candidate_environment_id'], 'vibe-dev')
        self.assertEqual(job['options']['baseline_name'], '레거시 개발')
        self.assertEqual(job['options']['candidate_name'], '바이브 개발')
        self.assertEqual(job['options']['allowed_hosts'], ['dev2-me.vivasam.com', 'me-dev.vivasam.com'])

    def test_inventory_csv_route_requires_inventory_and_exports_environment_names(self):
        _, created, _ = self.start()
        self.await_state(created['id'], {'done', 'error'})
        path = f"/api/scans/{created['id']}/inventory.csv"
        self.assertEqual(self.request('GET', path)[0], 409)
        job = self.server.service.store.get(created['id'])
        job['report']['inventory'] = {'productId': 'custom', 'environments': [
            {'id': 'a', 'name': 'DEV2', 'pages': [{'pageKey': '/notice', 'url': 'https://a.test/notice',
                'title': 'Notice', 'visited': True, 'statusCode': 200, 'actionCount': 0, 'blockedActionCount': 0}]}]}
        self.server.service.store.save(job)
        status, payload, headers = self.request('GET', path)
        self.assertEqual(status, 200)
        self.assertIn('DEV2', payload.decode('utf-8-sig'))
        self.assertIn('attachment', headers['Content-Disposition'])
        self.assertIn(self.request('GET', '/api/scans/../outside/inventory.csv')[0], (400, 404))

    def test_single_active_run_conflict_cancel_and_next_run(self):
        self.mode = "wait-cancel"
        status, created, _ = self.start()
        self.assertEqual(status, 202)
        self.assertTrue(self.runner_started.wait(1))
        self.assertEqual(self.start()[0], 409)
        self.assertEqual(self.request("POST", f'/api/scans/{created["id"]}/cancel')[0], 200)
        job = self.await_state(created["id"], {"cancelled", "error"})
        self.assertEqual(job["state"], "cancelled")
        self.assertIsNotNone(job["report"])
        self.mode = "complete"
        status, second, _ = self.start(operatorId="QA-B")
        self.assertEqual(status, 202)
        self.assertEqual(self.await_state(second["id"], {"done", "error"})["operatorId"], "QA-B")

    def test_manual_auth_wait_continue_and_cancel_close_fake_page(self):
        self.mode = "auth"
        status, created, _ = self.start(manualLogin=True)
        self.assertEqual(status, 202)
        waiting = self.await_state(created["id"], {"awaiting_auth", "error"})
        self.assertEqual(waiting["authSide"], "a")
        self.assertEqual(self.request("POST", f'/api/scans/{created["id"]}/continue')[0], 200)
        self.assertEqual(self.await_state(created["id"], {"done", "error"})["state"], "done")
        self.assertTrue(self.fake_context.page.closed)
        self.fake_context = _FakeContext()
        status, cancelled, _ = self.start(manualLogin=True)
        self.assertEqual(status, 202)
        self.await_state(cancelled["id"], {"awaiting_auth", "error"})
        self.assertEqual(self.request("POST", f'/api/scans/{cancelled["id"]}/cancel')[0], 200)
        self.assertEqual(self.await_state(cancelled["id"], {"cancelled", "error"})["state"], "cancelled")
        self.assertTrue(self.fake_context.page.closed)

    def test_runner_exception_is_error_and_does_not_lock_future_runs(self):
        self.mode = "error"
        _, created, _ = self.start()
        failed = self.await_state(created["id"], {"done", "error"})
        self.assertEqual(failed["state"], "error")
        self.assertIn("RuntimeError", failed["error"])
        self.assertIsNone(failed["report"])
        self.mode = "complete"
        self.assertEqual(self.start()[0], 202)

    def test_review_api_conflict_preserves_automatic_state_and_actor(self):
        _, created, _ = self.start()
        self.await_state(created["id"], {"done", "error"})
        path = f'/api/scans/{created["id"]}/reviews'
        review = {"resultId": "row-1", "reviewer": "QA-B", "status": "VERIFIED_OK", "reason": "Synthetic evidence checked", "expectedRevision": 0}
        status, changed, _ = self.request("POST", path, review)
        self.assertEqual(status, 200)
        self.assertEqual(changed["review"]["events"][0]["reviewer"], "QA-B")
        self.assertEqual(self.request("POST", path, review)[0], 409)
        row = self.request("GET", "/api/scans/" + created["id"])[1]["report"]["results"][0]
        self.assertEqual(row["status"], "PASS")
        self.assertEqual(row["review"]["revision"], 1)

    def test_artifact_valid_path_and_traversal_rejection(self):
        run_id = str(uuid.uuid4())
        artifact = Path(self.temp.name) / run_id / "a" / "local.png"
        artifact.parent.mkdir(parents=True)
        artifact.write_bytes(b"synthetic-png-placeholder")
        self.assertEqual(self.request("GET", f"/artifacts/{run_id}/a/local.png")[0], 200)
        for path in (f"/artifacts/{run_id}/a/../../outside.png", f"/artifacts/{run_id}/a/%2e%2e%2foutside.png",
                     f"/artifacts/{run_id}/a/local.json", "/artifacts/not-a-uuid/a/local.png"):
            with self.subTest(path=path):
                self.assertIn(self.request("GET", path)[0], (400, 404))
        self.assertEqual(self.request("GET", f"/artifacts/{run_id}/a/missing.png")[0], 404)

    def test_missing_or_running_regression_reference_is_rejected_before_runner_start(self):
        status, _, _ = self.start(testType='regression', previousRunId=str(uuid.uuid4()))
        self.assertEqual(status, 400)
        self.assertFalse(self.runner_started.is_set())
        self.mode = 'wait-cancel'
        _, first, _ = self.start(testType='single')
        self.assertTrue(self.runner_started.wait(1))
        self.assertEqual(self.start(testType='regression', previousRunId=first['id'])[0], 409)

    def test_regression_preserves_past_report_and_attaches_comparability_evaluation(self):
        _, first, _ = self.start(testType='single')
        self.await_state(first['id'], {'done', 'error'})
        before = (Path(self.temp.name) / first['id'] / 'report.json').read_bytes()
        status, second, _ = self.start(testType='regression', previousRunId=first['id'])
        self.assertEqual(status, 202)
        current = self.await_state(second['id'], {'done', 'error'})
        self.assertEqual(current['state'], 'done', current)
        self.assertEqual(current['report']['regression']['previousRunId'], first['id'])
        self.assertIn('comparability', current['report']['regression'])
        self.assertEqual((Path(self.temp.name) / first['id'] / 'report.json').read_bytes(), before)

    def test_issue_reference_roundtrip_is_revision_protected_and_exported(self):
        _, created, _ = self.start(testType='single')
        self.await_state(created['id'], {'done', 'error'})
        payload = {'resultId': 'row-1', 'reviewer': 'QA-B', 'status': 'BUG_CONFIRMED',
                   'reason': 'Checked against contract', 'expectedRevision': 0,
                   'issueRef': 'https://issues.example.invalid/QA-12'}
        path = f"/api/scans/{created['id']}/reviews"
        status, body, _ = self.request('POST', path, payload)
        self.assertEqual(status, 200)
        self.assertEqual(body['review']['issueRef'], payload['issueRef'])
        self.assertEqual(self.request('POST', path, payload)[0], 409)
        status, export, _ = self.request('GET', f"/api/scans/{created['id']}.csv")
        self.assertEqual(status, 200)
        self.assertIn(payload['issueRef'], export.decode('utf-8-sig'))

    def test_disk_failure_is_error_and_keeps_collected_report_available_in_memory(self):
        original_save = self.server.service.store.save

        def fail_terminal(job):
            if job.get('state') in ('done', 'cancelled', 'error'):
                raise OSError('Synthetic disk unavailable')
            return original_save(job)

        with patch.object(self.server.service.store, 'save', side_effect=fail_terminal):
            _, created, _ = self.start()
            failed = self.await_state(created['id'], {'error'})
            self.assertIn('EVIDENCE_SAVE_FAILED', failed['error'])
            self.assertIsNotNone(failed['report'])
            self.assertEqual(self.request('GET', f"/api/scans/{created['id']}.json")[0], 200)
            listed = self.request('GET', '/api/scans')[1]['scans']
            self.assertEqual(listed[0]['state'], 'error')
        self.assertIsNone(self.server.service.active)

    def test_second_server_cannot_recover_an_owned_report_directory(self):
        with self.assertRaisesRegex(ValueError, '다른 서버'):
            Server(('127.0.0.1', 0), runs_dir=Path(self.temp.name))

    def test_invalid_runner_report_is_error_with_original_evidence_retained(self):
        self.mode = 'invalid-report'
        _, created, _ = self.start()
        failed = self.await_state(created['id'], {'error'})
        self.assertIn('REPORT_CONTRACT_INVALID', failed['error'])
        self.assertIsNotNone(failed['report'])
        self.assertEqual(self.request('GET', f"/api/scans/{created['id']}.json")[0], 200)

    def test_shutdown_keeps_directory_lease_until_inflight_review_is_durable(self):
        _, created, _ = self.start()
        self.await_state(created['id'], {'done', 'error'})
        entered, release = threading.Event(), threading.Event()
        replies, failures = [], []
        original_save = self.server.service.store.save

        def delayed_save(job):
            entered.set()
            if not release.wait(timeout=5):
                raise RuntimeError('Review gate was not released')
            return original_save(job)

        payload = {'resultId': 'row-1', 'reviewer': 'QA-A', 'status': 'BUG_CONFIRMED',
                   'reason': 'First reviewer', 'expectedRevision': 0}

        def post_review():
            try:
                replies.append(self.request('POST', f"/api/scans/{created['id']}/reviews", payload)[0])
            except Exception as exc:
                failures.append(exc)

        with patch.object(self.server.service.store, 'save', side_effect=delayed_save):
            request_thread = threading.Thread(target=post_review)
            request_thread.start()
            close_thread = None
            try:
                self.assertTrue(entered.wait(timeout=2))
                self.server.shutdown()
                close_thread = threading.Thread(target=self.server.server_close)
                close_thread.start()
                deadline = time.monotonic() + 1
                while not self.server.service.closing and time.monotonic() < deadline:
                    threading.Event().wait(0.01)
                self.assertTrue(self.server.service.closing)
                self.assertTrue(close_thread.is_alive(), 'In-flight review must finish before releasing the lease')
                with self.assertRaisesRegex(ValueError, '다른 서버'):
                    Server(('127.0.0.1', 0), runs_dir=Path(self.temp.name))
            finally:
                release.set()
                request_thread.join(timeout=3)
                if close_thread:
                    close_thread.join(timeout=3)
            self.assertFalse(request_thread.is_alive())
            self.assertFalse(close_thread.is_alive())
        self.assertEqual(failures, [])
        self.assertEqual(replies, [200])
        replacement = Server(('127.0.0.1', 0), runs_dir=Path(self.temp.name))
        try:
            with self.assertRaises(ReviewConflict):
                replacement.service.store.review(created['id'], 'row-1', 'QA-B', 'VERIFIED_OK', 'Stale review', 0)
            review = replacement.service.store.review(created['id'], 'row-1', 'QA-B', 'RETEST_REQUIRED', 'Latest review', 1)
            self.assertEqual([event['reviewer'] for event in review['events']], ['QA-A', 'QA-B'])
        finally:
            replacement.server_close()


class CsvExportTests(unittest.TestCase):
    def test_zero_null_and_formula_cells_remain_distinct(self):
        report = _report()
        report["results"][0]["key"] = "=1+1"
        second = dict(report["results"][0], id="row-2", key="normal", visual={"differencePercent": None})
        report["results"].append(second)
        job = {"id": str(uuid.uuid4()), "operatorId": "QA-A", "report": report}
        decoded = csv_report(job).decode("utf-8-sig")
        rows = list(csv.reader(io.StringIO(decoded)))
        self.assertEqual(rows[1][2], "'=1+1")
        self.assertEqual(rows[1][8], "0")
        self.assertEqual(rows[2][8], "")
        self.assertEqual(csv_safe("  @SUM(A1)"), "'  @SUM(A1)")
        self.assertEqual(csv_safe("\ttext"), "'\ttext")
        self.assertEqual(csv_safe(0), "0")


if __name__ == "__main__":
    unittest.main()
