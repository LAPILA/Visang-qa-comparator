import math
import unittest

from qa.config import parse_options, profiles, validate_url


class ConfigValidationTests(unittest.TestCase):
    origin = "http://127.0.0.1:39001"

    def custom(self, **changes):
        return {"profileId": "custom", "baselineUrl": "https://baseline.invalid/start",
                "candidateUrl": "https://candidate.invalid/start", **changes}

    def test_demo_roundtrip_retains_routes_scenarios_and_budget(self):
        demo = next(item for item in profiles(self.origin) if item["id"] == "synthetic-demo")
        options = parse_options({"profileId": "synthetic-demo", **demo["defaults"]}, self.origin)
        self.assertEqual(options["baseline_url"], self.origin + "/demo/a/")
        self.assertEqual(options["candidate_url"], self.origin + "/demo/b/")
        self.assertEqual(len(options["scenario_ids"]), 3)
        self.assertEqual(len(options["route_aliases"]), 5)
        self.assertFalse(any("unsafe" in path for path in options["allowed_paths"]))
        self.assertEqual(options["max_actions"], 80)

    def test_demo_addresses_cannot_be_replaced(self):
        for key in ("baselineUrl", "candidateUrl"):
            with self.subTest(key=key), self.assertRaises(ValueError):
                parse_options({"profileId": "synthetic-demo", key: "https://other.invalid/"}, self.origin)

    def test_disabled_and_unknown_profiles_are_rejected(self):
        for profile in ("secondary-mobile", "does-not-exist"):
            with self.subTest(profile=profile), self.assertRaises(ValueError):
                parse_options({"profileId": profile}, self.origin)

    def test_numeric_limits_reject_nonfinite_boolean_fraction_and_range(self):
        for value in (math.nan, math.inf, -math.inf, "NaN", "1e309", True, 1.5, 0, 31, None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_options(self.custom(maxPages=value), self.origin)
        for key, value in (("maxActions", 51), ("timeoutSeconds", 14),
                           ("actionInterval", 0), ("visualThreshold", float("nan"))):
            with self.subTest(key=key), self.assertRaises(ValueError):
                parse_options(self.custom(**{key: value}), self.origin)

    def test_numeric_boundaries_and_mobile_viewport(self):
        options = parse_options(self.custom(maxPages=30, maxDepth=0, maxActions=0,
                                            timeoutSeconds=15, visualThreshold=100), self.origin)
        self.assertEqual((options["max_pages"], options["max_depth"], options["max_actions"]), (30, 0, 0))
        mobile = parse_options({"profileId": "elementary-mobile"}, self.origin)
        self.assertEqual(mobile["viewport"], {"width": 390, "height": 844})

    def test_credentials_and_unsafe_url_forms_are_rejected(self):
        for value in ("file:///tmp/test", "javascript:alert(1)", "https://user:secret@example.invalid/",
                      "https://example.invalid:99999/", "https://example.invalid/a\nb", "//example.invalid/"):
            with self.subTest(url=value), self.assertRaises(ValueError):
                validate_url(value)
        for key in ("password", "PW", "cookie", "token", "storage_state"):
            with self.subTest(key=key), self.assertRaises(ValueError):
                parse_options(self.custom(**{key: "synthetic-secret"}), self.origin)

    def test_malformed_and_ambiguous_mapping_region_inputs_fail(self):
        bad_inputs = [
            {"aliases": "{invalid"}, {"aliases": {}},
            {"aliases": [{"baseline": "//outside.invalid", "candidate": "/new", "page_class": "home"}]},
            {"aliases": [{"baseline": "/a", "candidate": "/b", "page_class": "same"},
                         {"baseline": "/c", "candidate": "/d", "page_class": "same"}]},
            {"regions": [{"id": "x", "selector": "#x"}, {"id": "x", "selector": "#y"}]},
            {"regions": [{"id": "x", "selector": "#x", "mask_selectors": [None]}]},
            {"safeActions": [{"id": "x", "selector": "#x", "kind": "evaluate"}]},
            {"scenarioIds": [None]},
        ]
        for change in bad_inputs:
            with self.subTest(change=change), self.assertRaises(ValueError):
                parse_options(self.custom(**change), self.origin)

    def test_host_and_path_allowlists_are_exact_and_bounded(self):
        for change in ({"allowedHosts": ["*.example.invalid"]}, {"allowedHosts": ["example.invalid/path"]},
                       {"allowedHosts": ["example.invalid:bad"]}, {"allowedPaths": ["/*"]},
                       {"allowedPaths": ["//outside.invalid/path"]}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                parse_options(self.custom(**change), self.origin)
        options = parse_options(self.custom(allowedHosts="cdn.invalid\ncdn.invalid", allowedPaths="/search\n/notice/*"), self.origin)
        self.assertEqual(options["allowed_hosts"], ["baseline.invalid", "candidate.invalid", "cdn.invalid"])
        self.assertEqual(options["allowed_paths"], ["/search", "/notice/*"])


if __name__ == "__main__":
    unittest.main()
