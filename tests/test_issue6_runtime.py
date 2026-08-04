import json
import os
import tempfile
import time
import unittest

from tests.support import FakeFetch  # also adds src/ to sys.path
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


class TestIssue6VerdictGate(unittest.TestCase):
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

            started = time.monotonic()
            code, payload = run_daily.run_supervised(
                output, status, lock, workers=4,
                max_runtime_seconds=1, builder=blocked_builder)
            elapsed = time.monotonic() - started

            self.assertEqual(code, 1)
            self.assertLess(elapsed, 5.0)
            self.assertEqual(payload["state"], "failed")
            self.assertIn("TimeoutError", payload["error"])
            with open(output, encoding="utf-8") as handle:
                self.assertEqual(json.load(handle), {"last_good": True})
            with open(status, encoding="utf-8") as handle:
                first_status = json.load(handle)
            self.assertEqual(first_status["state"], "failed")

            time.sleep(2.5)
            with open(status, encoding="utf-8") as handle:
                self.assertEqual(json.load(handle), first_status)

            with run_daily.exclusive_lock(lock):
                pass


if __name__ == "__main__":
    unittest.main()
