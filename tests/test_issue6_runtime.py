import json
import multiprocessing
import os
import tempfile
import time
import unittest
from unittest import mock

import run_daily
import wx_daily as w


MP = w.MarketParams(fee_rate=0.05, tick=0.01,
                    min_notional=1.0, min_shares=0.0,
                    source="issue6")


def make_pick(index):
    return dict(city=f"Город {index}", date="2026-08-05",
                side="YES", conf=5, ev=round(1.0-index/100, 2),
                robust=True, stake=2.0, mp=MP,
                token_id=f"token-{index}", ask=0.25,
                p_cons=0.60)


def successful_builder(**_kwargs):
    return {"generated": "now", "paper_forecasts": []}


def hold_lock(lock_path, ready, release):
    with run_daily.exclusive_lock(lock_path):
        ready.set()
        release.wait(10)


class TestIssue6VerdictGate(unittest.TestCase):
    def test_build_report_never_emits_unexecuted_thirteenth_pick(self):
        produced = [make_pick(index) for index in range(13)]
        calibration = dict(
            fams={"1": {}, "2": {}}, tiers={"1": "A", "2": "C"},
            tier="A", bias=0.0, std=0.5, n=6)

        def fake_screen(*_args, **_kwargs):
            return produced

        def missing_book(_url):
            raise RuntimeError("book missing")

        with mock.patch.object(w, "ST", {
                "test-city": ("TEST", 0.0, 0.0, "C", "Тест")}), \
             mock.patch.object(w, "MIN_SLUGS", []), \
             mock.patch.object(w, "REF_BIAS", {"test-city": 0.0}), \
             mock.patch.object(w, "calibrate", return_value=calibration), \
             mock.patch.object(w, "screen", side_effect=fake_screen), \
             mock.patch.object(w, "portfolio_scan", return_value=None), \
             mock.patch.object(w, "check_coverage", return_value={}):
            report = w.build_report(
                fetch=missing_book, workers=1, include_tier_c=True)

        self.assertIsNone(report["verdicts"]["max"])
        self.assertFalse(produced[12].get("execution_approved"))
        self.assertEqual(produced[12]["stake"], 0.0)
        self.assertEqual(report["budget"]["allocations"], [])

    def test_thirteenth_invalid_pick_cannot_bypass_execution_gate(self):
        picks = [make_pick(index) for index in range(13)]
        allocator = w.BudgetAllocator()

        def missing_book(_url):
            raise RuntimeError("book missing")

        w.execute_weather_candidates([], picks, allocator, fetch=missing_book)

        self.assertFalse(picks[12].get("execution_approved"))
        self.assertEqual(picks[12]["stake"], 0.0)
        self.assertIsNone(w.select_weather_verdict(None, picks))
        self.assertEqual(allocator.snapshot()["allocations"], [])

    def test_thirteenth_valid_pick_is_executed_reserved_then_selected(self):
        picks = [make_pick(index) for index in range(13)]
        allocator = w.BudgetAllocator()

        def books(url):
            if url.endswith("token-12"):
                return dict(asks=[dict(price="0.25", size="100")],
                            min_order_size="1", tick_size="0.01")
            raise RuntimeError("book missing")

        w.execute_weather_candidates([], picks, allocator, fetch=books)
        verdict = w.select_weather_verdict(None, picks)

        self.assertTrue(picks[12].get("execution_approved"))
        self.assertGreater(picks[12]["stake"], 0.0)
        self.assertEqual(verdict["city"], "Город 12")
        self.assertEqual(verdict["kind"], "одиночная")
        allocations = allocator.snapshot()["allocations"]
        self.assertEqual(len(allocations), 1)
        self.assertEqual(allocations[0]["tag"],
                         "single:Город 12:2026-08-05")


class TestIssue6HardDeadline(unittest.TestCase):
    def test_blocked_child_is_killed_and_terminal_failure_is_stable(self):
        def blocked_builder(**_kwargs):
            time.sleep(30)
            return {"generated": "too late", "paper_forecasts": []}

        with tempfile.TemporaryDirectory() as td:
            output = os.path.join(td, "report.json")
            status = os.path.join(td, "status.json")
            lock = os.path.join(td, "scan.lock")
            with open(output, "w", encoding="utf-8") as handle:
                json.dump({"last_good": True}, handle)

            original_heartbeat = run_daily.HEARTBEAT_SECONDS
            run_daily.HEARTBEAT_SECONDS = 0.2
            try:
                started = time.monotonic()
                code, payload = run_daily.run_supervised(
                    output, status, lock, workers=4,
                    max_runtime_seconds=1, builder=blocked_builder)
                elapsed = time.monotonic() - started
            finally:
                run_daily.HEARTBEAT_SECONDS = original_heartbeat

            self.assertEqual(code, 1)
            self.assertLess(elapsed, 5.0)
            self.assertEqual(payload["state"], "failed")
            self.assertIn("TimeoutError", payload["error"])
            with open(output, encoding="utf-8") as handle:
                self.assertEqual(json.load(handle), {"last_good": True})
            with open(status, encoding="utf-8") as handle:
                first_status = json.load(handle)
            self.assertEqual(first_status["state"], "failed")

            # Wait longer than several test heartbeat intervals. A killed child
            # cannot publish a stale running state after terminal failure.
            time.sleep(0.7)
            with open(status, encoding="utf-8") as handle:
                self.assertEqual(json.load(handle), first_status)

            with run_daily.exclusive_lock(lock):
                pass

    def test_duplicate_run_returns_75_through_supervisor(self):
        context = multiprocessing.get_context("fork")
        with tempfile.TemporaryDirectory() as td:
            output = os.path.join(td, "report.json")
            status = os.path.join(td, "status.json")
            lock = os.path.join(td, "scan.lock")
            sentinel = {"state": "running", "owner": "first-run"}
            with open(status, "w", encoding="utf-8") as handle:
                json.dump(sentinel, handle)

            ready = context.Event()
            release = context.Event()
            holder = context.Process(
                target=hold_lock, args=(lock, ready, release),
                name="issue6-lock-holder")
            holder.start()
            self.assertTrue(ready.wait(2.0), "first run did not acquire lock")
            try:
                started = time.monotonic()
                code, payload = run_daily.run_supervised(
                    output, status, lock, workers=1,
                    max_runtime_seconds=3, builder=successful_builder)
                elapsed = time.monotonic() - started
            finally:
                release.set()
                holder.join(timeout=3.0)
                if holder.is_alive():
                    holder.kill()
                    holder.join()

            self.assertEqual(code, 75)
            self.assertEqual(payload["state"], "already_running")
            self.assertLess(elapsed, 2.0)
            self.assertFalse(os.path.exists(output))
            with open(status, encoding="utf-8") as handle:
                self.assertEqual(json.load(handle), sentinel)


if __name__ == "__main__":
    unittest.main()
