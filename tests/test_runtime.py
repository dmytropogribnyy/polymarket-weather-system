"""Runtime contracts for the long daily scan.

These tests keep performance work from weakening the trading safety gates:
safe GETs may be cached/single-flighted, volatile books may not, concurrency is
bounded, and the durable runner never exposes a partial report.
"""
import hashlib
import json
import os
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor

from tests.support import FakeFetch, market  # also adds src/ to sys.path
import wx_daily as w


class TestRunFetcher(unittest.TestCase):
    def test_http_timeout_is_bounded_and_has_safe_default(self):
        self.assertEqual(w.http_timeout("0"), 5.0)
        self.assertEqual(w.http_timeout("999"), 60.0)
        self.assertEqual(w.http_timeout("bad"), 20.0)

    def test_safe_response_is_cached_for_the_run(self):
        calls = []

        def base(url):
            calls.append(url)
            return {"url": url}

        fetch = w.RunFetcher(base)
        url = "https://ensemble-api.open-meteo.com/v1/ensemble?city=x"
        self.assertEqual(fetch(url), fetch(url))
        self.assertEqual(calls, [url])
        self.assertEqual(fetch.stats()["cache_hits"], 1)

    def test_order_books_are_never_cached(self):
        calls = []

        def base(url):
            calls.append(url)
            return {"sequence": len(calls)}

        fetch = w.RunFetcher(base)
        url = "https://clob.polymarket.com/book?token_id=live"
        self.assertNotEqual(fetch(url), fetch(url))
        self.assertEqual(len(calls), 2)

    def test_same_inflight_url_is_single_flight(self):
        calls = 0
        lock = threading.Lock()

        def base(url):
            nonlocal calls
            with lock:
                calls += 1
            time.sleep(0.04)
            return {"ok": True}

        fetch = w.RunFetcher(base)
        url = "https://previous-runs-api.open-meteo.com/v1/forecast?city=x"
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(fetch, [url] * 4))
        self.assertEqual(results, [{"ok": True}] * 4)
        self.assertEqual(calls, 1)
        self.assertEqual(fetch.stats()["singleflight_hits"], 3)


class TestBoundedParallelism(unittest.TestCase):
    def test_parallel_map_preserves_order_and_worker_limit(self):
        active = peak = 0
        lock = threading.Lock()

        def work(value):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(0.02)
            with lock:
                active -= 1
            return value * 2

        self.assertEqual(w._parallel_map(work, range(8), workers=3),
                         [value * 2 for value in range(8)])
        self.assertGreater(peak, 1)
        self.assertLessEqual(peak, 3)

    def test_daily_scope_keeps_only_pre_outcome_tiers_a_and_b(self):
        calibrations = {
            "a": {"tiers": {"1": "A", "2": "C"}},
            "b": {"tier": "B", "tiers": {}},
            "c": {"tiers": {"1": "C", "2": "C"}},
            "missing": {},
        }
        self.assertEqual(w.selected_city_slugs(
            ["a", "b", "c", "missing"], calibrations), ["a", "b"])
        self.assertEqual(w.selected_city_slugs(
            ["a", "b", "c", "missing"], calibrations, include_tier_c=True),
            ["a", "b", "c", "missing"])
        dates = [(1, "tomorrow"), (2, "day-after")]
        self.assertEqual(w.selected_weather_dates(dates, calibrations["a"]),
                         [(1, "tomorrow")])
        self.assertEqual(w.selected_weather_dates(
            dates, calibrations["a"], include_tier_c=True), dates)

    def test_calibration_refreshes_ab_daily_and_rotates_c(self):
        from datetime import date

        slugs = ["a", "c1", "c2", "c3", "c4", "c5", "c6", "c7"]
        previous = {slug: {"tier": "B" if slug == "a" else "C",
                           "tiers": {"1": "B" if slug == "a" else "C",
                                     "2": "C"}}
                    for slug in slugs}
        refreshed, carried = w.calibration_refresh_plan(
            slugs, previous, date(2026, 8, 3))
        self.assertIn("a", refreshed)
        self.assertEqual(set(refreshed) | set(carried), set(slugs))
        self.assertTrue(set(refreshed).isdisjoint(carried))
        self.assertLess(len(refreshed), len(slugs))

    def test_first_calibration_or_full_audit_refreshes_every_city(self):
        from datetime import date

        slugs = ["a", "b"]
        self.assertEqual(w.calibration_refresh_plan(slugs, {}, date(2026, 8, 3)),
                         (slugs, {}))
        previous = {slug: {"tier": "C", "tiers": {"1": "C", "2": "C"}}
                    for slug in slugs}
        self.assertEqual(w.calibration_refresh_plan(
            slugs, previous, date(2026, 8, 3), include_tier_c=True), (slugs, {}))


class TestFastMarketParameterPath(unittest.TestCase):
    def test_complete_gamma_params_skip_optional_clob_enrichment(self):
        gamma = market(conditionId="0xcomplete")
        fetch = FakeFetch({"clob.polymarket.com/markets/0xcomplete":
                           {"minimum_order_size": 5, "minimum_tick_size": 0.01,
                            "taker_base_fee": 500}})
        params = w.event_params([gamma], fetch, enrich_clob=False)
        self.assertIsNotNone(params)
        self.assertEqual(params.min_shares, 0.0)
        self.assertFalse(any("clob.polymarket.com/markets/" in url for url in fetch.calls))

    def test_required_clob_fallback_still_runs(self):
        gamma = market(taker_base_fee=None, minimum_tick_size=None,
                       conditionId="0xfallback")
        fetch = FakeFetch({"clob.polymarket.com/markets/0xfallback":
                           {"minimum_order_size": 5, "minimum_tick_size": 0.01,
                            "taker_base_fee": 500}})
        params = w.event_params([gamma], fetch, enrich_clob=False)
        self.assertIsNotNone(params)
        self.assertEqual(params.source, "event")
        self.assertTrue(any("clob.polymarket.com/markets/" in url for url in fetch.calls))


class TestRunState(unittest.TestCase):
    def test_retired_non_weather_circuits_have_no_runtime_entrypoints(self):
        import run_daily

        for name in ("quake_scan", "crypto_scan", "load_surface", "q_bucket"):
            self.assertFalse(hasattr(w, name), name)
        args = run_daily.parse_args([])
        self.assertFalse(hasattr(args, "include_extras"))

    def test_reset_prevents_cross_run_accumulation(self):
        w.SLOPPY.append({"old": True})
        w.COMBOS.append({"old": True})
        w.PAPER_FORECASTS.append({"old": True})
        w.RES_FAILS.append("old")
        w.POOL_FAILS.append("old")
        w.PARAM_FAILS.append("old")
        w.RES_SEEN["old"] = "old"
        w.PARSE_FAIL[0] = 9
        w.reset_run_state()
        self.assertEqual((w.SLOPPY, w.COMBOS, w.PAPER_FORECASTS,
                          w.RES_FAILS, w.POOL_FAILS, w.PARAM_FAILS),
                         ([], [], [], [], [], []))
        self.assertEqual(w.RES_SEEN, {})
        self.assertEqual(w.PARSE_FAIL[0], 0)


class TestAtomicRunner(unittest.TestCase):
    def test_duplicate_run_is_rejected_by_os_lock(self):
        import run_daily

        with tempfile.TemporaryDirectory() as td:
            lock = os.path.join(td, "scan.lock")
            with run_daily.exclusive_lock(lock):
                with self.assertRaises(run_daily.AlreadyRunning):
                    with run_daily.exclusive_lock(lock):
                        self.fail("second lock must never be acquired")

    def test_success_publishes_complete_report_and_status(self):
        import run_daily

        with tempfile.TemporaryDirectory() as td:
            output = os.path.join(td, "report.json")
            status = os.path.join(td, "status.json")
            lock = os.path.join(td, "scan.lock")
            result = run_daily.run_once(
                output, status, lock, workers=2,
                builder=lambda **_: {"generated": "now", "paper_forecasts": [{"x": 1}]})
            with open(output, encoding="utf-8") as fh:
                self.assertEqual(json.load(fh)["paper_forecasts"], [{"x": 1}])
            with open(output, "rb") as fh:
                actual_hash = hashlib.sha256(fh.read()).hexdigest()
            with open(status, encoding="utf-8") as fh:
                saved_status = json.load(fh)
            self.assertEqual(saved_status["state"], "success")
            self.assertEqual(saved_status["report_sha256"], result["report_sha256"])
            self.assertEqual(saved_status["report_sha256"], actual_hash)

    def test_live_builder_progress_is_published_to_status(self):
        import run_daily

        with tempfile.TemporaryDirectory() as td:
            output = os.path.join(td, "report.json")
            status = os.path.join(td, "status.json")
            lock = os.path.join(td, "scan.lock")
            seen = {}
            original = w.build_report

            def fake_build_report(**kwargs):
                kwargs["progress"]({"stage": "weather_max", "completed": 3, "total": 8})
                with open(status, encoding="utf-8") as fh:
                    seen.update(json.load(fh))
                return {"generated": "now", "paper_forecasts": []}

            try:
                w.build_report = fake_build_report
                run_daily.run_once(output, status, lock, workers=2)
            finally:
                w.build_report = original
            self.assertEqual(seen["state"], "running")
            self.assertEqual(seen["stage"], "weather_max")
            self.assertEqual(seen["completed"], 3)
            self.assertEqual(seen["total"], 8)
            self.assertIn("heartbeat_at", seen)

    def test_last_complete_report_is_supplied_for_calibration_rotation(self):
        import run_daily

        with tempfile.TemporaryDirectory() as td:
            output = os.path.join(td, "report.json")
            status = os.path.join(td, "status.json")
            lock = os.path.join(td, "scan.lock")
            with open(output, "w", encoding="utf-8") as fh:
                json.dump({"generated": "yesterday", "paper_forecasts": [],
                           "calib_json": {"cal_date": "yesterday"}}, fh)
            seen = {}
            original = w.build_report

            def fake_build_report(**kwargs):
                seen.update(kwargs["prior_report"])
                return {"generated": "today", "paper_forecasts": []}

            try:
                w.build_report = fake_build_report
                run_daily.run_once(output, status, lock)
            finally:
                w.build_report = original
            self.assertEqual(seen["generated"], "yesterday")
            self.assertEqual(seen["calib_json"]["cal_date"], "yesterday")

    def test_failure_preserves_last_good_report(self):
        import run_daily

        with tempfile.TemporaryDirectory() as td:
            output = os.path.join(td, "report.json")
            status = os.path.join(td, "status.json")
            lock = os.path.join(td, "scan.lock")
            with open(output, "w", encoding="utf-8") as fh:
                json.dump({"last_good": True}, fh)

            def fail(**_):
                raise RuntimeError("network exploded")

            with self.assertRaisesRegex(RuntimeError, "network exploded"):
                run_daily.run_once(output, status, lock, builder=fail)
            with open(output, encoding="utf-8") as fh:
                self.assertEqual(json.load(fh), {"last_good": True})
            with open(status, encoding="utf-8") as fh:
                self.assertEqual(json.load(fh)["state"], "failed")


if __name__ == "__main__":
    unittest.main()
