"""Registered assertions for the synthetic local fixture only.

Live sites deliberately have no inferred expectations. A site adapter and explicit
product contract are required before registering a live scenario.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlencode, urlsplit
import time

from qa.demo import DEMO_MARKER

SCENARIO_IDS = ("demo.search", "demo.input_length", "demo.history")


class _Stopped(Exception):
    def __init__(self, reason):
        self.reason = reason


def _result(scenario_id, step_id, status, reason, expected=None, actual=None):
    return {
        "check_id": f"{scenario_id}.{step_id}",
        "scenario_id": scenario_id,
        "step_id": step_id,
        "status": status,
        "reason_code": reason,
        "expected": expected,
        "actual": actual,
        "evidence": [],
    }


def _is_cancelled(cancelled):
    return bool(cancelled()) if callable(cancelled) else bool(cancelled)


def _demo_location(page):
    parsed = urlsplit(page.url)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        return None
    body = page.locator(f'body[data-qa-demo="{DEMO_MARKER}"]')
    if body.count() != 1:
        return None
    side = body.get_attribute("data-qa-environment")
    if side not in {"a", "b"} or not parsed.path.startswith(f"/demo/{side}/"):
        return None
    return f"{parsed.scheme}://{parsed.netloc}", side


class _DemoScenario:
    def __init__(self, page, scenario_id, origin, side, options, cancelled):
        self.page = page
        self.scenario_id = scenario_id
        self.origin = origin
        self.side = side
        self.options = options
        self.cancelled = cancelled
        self.timeout = min(max(int(options.get("scenario_timeout_ms", 5000)), 100), 30000)
        self.deadline = time.monotonic() + max(float(options.get("scenario_max_seconds", 30)), 0)
        self.results = []
        self.changed = False

    def url(self, feature, **query):
        suffix = ".do" if self.side == "b" and feature else ""
        path = f"{self.origin}/demo/{self.side}/{feature}{suffix}"
        return path + ("?" + urlencode(query) if query else "")

    def action(self, kind, callback, selector="", url=None, label="", **metadata):
        if _is_cancelled(self.cancelled):
            raise _Stopped("CANCELLED")
        if time.monotonic() >= self.deadline:
            raise _Stopped("SCENARIO_TIME_LIMIT")
        action = {"scenario_id": self.scenario_id, "kind": kind, "selector": selector, "label": label, **metadata}
        if url is not None:
            action["url"] = url
        guard = self.options.get("_action_guard")
        if callable(guard) and not guard(action):
            raise _Stopped("POLICY_OR_BUDGET_BLOCKED")
        self.changed = True
        value = callback()
        completed = self.options.get("_action_completed")
        if callable(completed):
            completed(action)
        if _is_cancelled(self.cancelled):
            raise _Stopped("CANCELLED")
        return value

    def goto(self, feature, **query):
        url = self.url(feature, **query)
        return self.action("goto", lambda: self.page.goto(url, wait_until="domcontentloaded", timeout=self.timeout), url=url, label="Synthetic scenario navigation")

    def fill(self, selector, value):
        return self.action("fill", lambda: self.page.locator(selector).fill(value, timeout=self.timeout), selector=selector, label="Synthetic fixture input")

    def click(self, selector):
        return self.action("click", lambda: self.page.locator(selector).click(timeout=self.timeout), selector=selector, label="Synthetic fixture action")

    def enter(self, selector):
        return self.action("press", lambda: self.page.locator(selector).press("Enter", timeout=self.timeout), selector=selector, label="Synthetic search Enter", key="Enter")

    def check(self, step, condition, expected, actual):
        self.results.append(_result(self.scenario_id, step, "PASS" if condition else "FAIL",
                                    "ASSERTION_SATISFIED" if condition else "ASSERTION_FAILED", expected, actual))

    def search(self):
        self.goto("search")
        for step, keyword, mode, expected_count in [
            ("button-search", "mathematics", "button", 1),
            ("enter-search", "reading", "enter", 1),
            ("no-results", "unmatched-synthetic-keyword", "button", 0),
            ("empty-input", "", "enter", 0),
        ]:
            self.fill("#search-input", keyword)
            if mode == "button":
                self.click("#search-submit")
            else:
                self.enter("#search-input")
            self.page.wait_for_url(self.url("search", q=keyword), timeout=self.timeout)
            region = self.page.locator("#search-results")
            region.wait_for(state="visible", timeout=self.timeout)
            actual = {
                "query": parse_qs(urlsplit(self.page.url).query, keep_blank_values=True).get("q", [None])[0],
                "rendered_keyword": self.page.locator("#search-keyword").inner_text(),
                "result_count": int(region.get_attribute("data-result-count")),
                "empty_state": self.page.locator("#search-empty").count() == 1,
            }
            expected = {"query": keyword, "rendered_keyword": keyword, "result_count": expected_count, "empty_state": expected_count == 0}
            self.check(step, actual == expected, expected, actual)

    def input_length(self):
        self.goto("input")
        field = self.page.locator("#limited-input")
        self.check("maxlength-contract", field.get_attribute("maxlength") == "10", "10", field.get_attribute("maxlength"))
        # HTML maxlength uses UTF-16 units. This does not claim IME or clipboard coverage.
        for step, typed, expected in [
            ("n-minus-one", "123456789", "123456789"),
            ("n", "1234567890", "1234567890"),
            ("n-plus-one", "12345678901", "1234567890"),
            ("korean-boundary", "가나다라마바사아자차카", "가나다라마바사아자차"),
            ("emoji-boundary", "😀" * 6, "😀" * 5),
        ]:
            self.fill("#limited-input", typed)
            value = field.input_value()
            units = len(value.encode("utf-16-le")) // 2
            actual = {"value": value, "utf16_units": units, "counter": self.page.locator("#input-count").inner_text()}
            expected_units = len(expected.encode("utf-16-le")) // 2
            expected_state = {"value": expected, "utf16_units": expected_units, "counter": str(expected_units)}
            self.check(step, actual == expected_state, expected_state, actual)

    def history(self):
        self.goto("notice")
        listing_url = self.page.url
        first = self.page.locator('[data-testid="notice-link"]').first
        selected_title = first.inner_text()
        self.click('#notice-list li:first-child [data-testid="notice-link"]')
        self.page.locator("#notice-title").wait_for(state="visible", timeout=self.timeout)
        detail_url = self.page.url
        actual_title = self.page.locator("#notice-title").inner_text()
        self.check("selected-local-notice", actual_title == selected_title, selected_title, actual_title)
        self.action("reload", lambda: self.page.reload(wait_until="domcontentloaded", timeout=self.timeout), url=detail_url, label="Reload synthetic detail")
        reloaded = {"url": self.page.url, "title": self.page.locator("#notice-title").inner_text()}
        expected = {"url": detail_url, "title": selected_title}
        self.check("detail-reload", reloaded == expected, expected, reloaded)
        self.action("back", lambda: self.page.go_back(wait_until="domcontentloaded", timeout=self.timeout), url=listing_url, label="Back to synthetic list")
        self.page.locator("#notice-list").wait_for(state="visible", timeout=self.timeout)
        self.check("browser-back", self.page.url == listing_url, listing_url, self.page.url)
        self.action("forward", lambda: self.page.go_forward(wait_until="domcontentloaded", timeout=self.timeout), url=detail_url, label="Forward to synthetic detail")
        self.page.locator("#notice-title").wait_for(state="visible", timeout=self.timeout)
        restored = {"url": self.page.url, "title": self.page.locator("#notice-title").inner_text()}
        self.check("browser-forward", restored == expected, expected, restored)
        self.click("#notice-list-link")
        self.page.locator("#notice-list").wait_for(state="visible", timeout=self.timeout)
        self.check("ui-list-return", self.page.url == listing_url, listing_url, self.page.url)


def run_scenarios(page, scenario_ids, environment, options, cancelled):
    """Run explicit local-demo contracts on the supplied page and preserve checks.

    The engine owns evidence/listeners and injects an action guard for its shared
    budget. Results are not aggregated here. Every action, including cleanup, is
    guarded; denied cleanup is reported and does not bypass cancellation.
    """
    options = options or {}
    if isinstance(scenario_ids, str):
        scenario_ids = [scenario_ids]
    results = []
    scenario_ids = list(scenario_ids or [])
    for scenario_index, scenario_id in enumerate(scenario_ids):
        if scenario_id not in SCENARIO_IDS:
            results.append(_result(scenario_id, "preconditions", "SKIP", "SCENARIO_NOT_REGISTERED"))
            continue
        if _is_cancelled(cancelled):
            results.append(_result(scenario_id, "preconditions", "SKIP", "CANCELLED"))
            continue
        try:
            location = _demo_location(page)
        except Exception as exc:
            results.append(_result(scenario_id, "preconditions", "ERROR", "DEMO_MARKER_CHECK_FAILED",
                                   actual={"exception_type": type(exc).__name__}))
            continue
        if location is None:
            results.append(_result(scenario_id, "preconditions", "SKIP", "DEMO_ONLY_SCENARIO"))
            continue
        origin, side = location
        expected_side = environment.get("side") if isinstance(environment, dict) else environment
        expected_side = {"baseline": "a", "candidate": "b"}.get(expected_side, expected_side)
        if expected_side in {"a", "b"} and expected_side != side:
            results.append(_result(scenario_id, "preconditions", "ERROR", "ENVIRONMENT_MISMATCH", expected_side, side))
            continue
        original_url = page.url
        runner = _DemoScenario(page, scenario_id, origin, side, options, cancelled)
        try:
            getattr(runner, {"demo.search": "search", "demo.input_length": "input_length", "demo.history": "history"}[scenario_id])()
        except _Stopped as exc:
            runner.results.append(_result(scenario_id, "execution", "SKIP", exc.reason))
        except Exception as exc:
            runner.results.append(_result(scenario_id, "execution", "ERROR", "SCENARIO_EXECUTION_ERROR",
                                          actual={"exception_type": type(exc).__name__}))
        finally:
            if runner.changed:
                try:
                    runner.action("goto", lambda: page.goto(original_url, wait_until="domcontentloaded", timeout=runner.timeout),
                                  url=original_url, label="Restore synthetic scenario entry")
                    if _demo_location(page) != location:
                        raise RuntimeError("Demo context was not restored")
                except _Stopped as exc:
                    runner.results.append(_result(scenario_id, "cleanup", "SKIP", "STATE_RESET_SKIPPED", actual={"cause": exc.reason}))
                except Exception as exc:
                    runner.results.append(_result(scenario_id, "cleanup", "ERROR", "STATE_RESET_FAILED",
                                                  actual={"exception_type": type(exc).__name__}))
        results.extend(runner.results)
        if any(item["step_id"] == "cleanup" for item in runner.results):
            # Do not run another scenario from an unverified page state.
            remaining = scenario_ids[scenario_index + 1:]
            results.extend(_result(next_id, "preconditions", "SKIP", "PREVIOUS_STATE_RESET_FAILED") for next_id in remaining)
            break
    return results
