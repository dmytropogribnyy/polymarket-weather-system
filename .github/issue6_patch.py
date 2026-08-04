#!/usr/bin/env python3
import argparse
from pathlib import Path

TEST_FILE = r'''import json
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
'''

ORIGINAL_TESTS_YML = r'''name: tests

# Тесты обязаны идти на каждый push и pull request: «зелено у меня локально» —
# не доказательство. Сети в CI нет по замыслу: все внешние API замоканы.
on:
  push:
    branches: ["**"]
  pull_request:

permissions:
  contents: read

jobs:
  tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - uses: actions/setup-node@v4
        with:
          node-version: "20"
      - name: Синтаксис Python
        run: python -m compileall -q src tests
      - name: Синтаксис веб-скринеров
        run: node tests/parity/check_syntax.js
      - name: Ядро паритета считается само по себе
        run: node tests/parity/parity_test.js > /dev/null
      - name: Весь набор тестов
        run: python -m unittest discover -s tests -t . -v
'''


def write_tests():
    Path("tests/test_issue6_runtime.py").write_text(TEST_FILE, encoding="utf-8")


def apply_code():
    wx_path = Path("src/wx_daily.py")
    wx = wx_path.read_text(encoding="utf-8")

    old = (
        '    for t in sorted(picks, key=lambda t: -t.get("conf", 0)*t.get("ev", 0)):\n'
        '        want = t.get("stake") or 0.0\n'
    )
    new = (
        '    for t in sorted(picks, key=lambda t: -t.get("conf", 0)*t.get("ev", 0)):\n'
        '        t["execution_approved"] = False\n'
        '        t.pop("execution", None)\n'
        '        want = t.get("stake") or 0.0\n'
    )
    assert wx.count(old) == 1
    wx = wx.replace(old, new)

    old = (
        '        else:\n'
        '            t["stake"] = granted\n'
        '    return approved\n\n'
        'PM_WALLET = ""'
    )
    new = (
        '        else:\n'
        '            t["stake"] = granted\n'
        '            t["execution_approved"] = True\n'
        '            t["execution"] = exec_result\n'
        '    return approved\n\n'
        'PM_WALLET = ""'
    )
    assert wx.count(old) == 1
    wx = wx.replace(old, new)

    marker = '\ndef build_report(fetch=None, workers=None, include_tier_c=False,\n'
    helpers = '''
def execute_weather_candidates(combos, picks, allocator, fetch=None):
    """Run the executable-book and shared-budget gate for every candidate
    that can later become a report verdict."""
    return plan_weather(combos, picks, allocator, fetch=fetch)


def select_weather_verdict(combo, picks, series=None):
    """Return a BET verdict only from explicitly executed and reserved state."""
    if combo is not None:
        return dict(combo, kind="серия-комбо" if combo is series else "шанс-комбо")
    pick = next((candidate for candidate in picks
                 if candidate.get("conf", 0) >= 5
                 and candidate.get("robust")
                 and candidate.get("execution_approved")
                 and (candidate.get("stake") or 0) > 0), None)
    if pick is None:
        return None
    return dict({key: value for key, value in pick.items() if key != "tid"},
                kind="одиночная")

'''
    assert wx.count(marker) == 1
    wx = wx.replace(marker, helpers + marker)

    old = '    approved = plan_weather(combo_top, picks[:12], allocator, fetch=fetch)'
    new = '    approved = execute_weather_candidates(combo_top, picks, allocator, fetch=fetch)'
    assert wx.count(old) == 1
    wx = wx.replace(old, new)

    old = '''    def wx_verdict(combo, ps):
        if combo is not None:
            return dict(combo, kind="серия-комбо" if combo is series else "шанс-комбо")
        p = next((t for t in ps if t["conf"] >= 5 and t.get("robust") and (t.get("stake") or 0) > 0), None)
        if p: return dict({k: v for k, v in p.items() if k not in ("tid",)}, kind="одиночная")
        return None
'''
    new = '''    def wx_verdict(combo, ps):
        return select_weather_verdict(combo, ps, series=series)
'''
    assert wx.count(old) == 1
    wx = wx.replace(old, new)
    wx_path.write_text(wx, encoding="utf-8")

    runner_path = Path("src/run_daily.py")
    runner = runner_path.read_text(encoding="utf-8")
    imports_old = "import json\nimport os\nimport signal\nimport sys\n"
    imports_new = "import json\nimport multiprocessing\nimport os\nimport sys\n"
    assert runner.count(imports_old) == 1
    runner = runner.replace(imports_old, imports_new)

    start = runner.index("\ndef main(argv=None):")
    end = runner.index('\n\nif __name__ == "__main__":', start)
    replacement = r'''
def _child_entry(conn, output, status, lock, workers,
                 include_tier_c, builder):
    try:
        result = run_once(output, status, lock, workers,
                          builder=builder,
                          include_tier_c=include_tier_c)
    except AlreadyRunning as exc:
        message = dict(code=75, payload=dict(
            state="already_running", error=str(exc)))
    except BaseException as exc:
        message = dict(code=1, payload=dict(
            state="failed", error=f"{type(exc).__name__}: {exc}"))
    else:
        message = dict(code=0, payload=result)
    try:
        conn.send(message)
    finally:
        conn.close()


def run_supervised(output, status, lock, workers=None,
                   include_tier_c=False, max_runtime_seconds=1500,
                   builder=None):
    """Run the scan in a killable child process with a real deadline."""
    started = utc_now()
    context = multiprocessing.get_context("fork")
    parent_conn, child_conn = context.Pipe(duplex=False)
    process = context.Process(
        target=_child_entry,
        args=(child_conn, output, status, lock, workers,
              include_tier_c, builder),
        name="wx-daily-scan")
    try:
        process.start()
    except BaseException as exc:
        child_conn.close()
        parent_conn.close()
        failed = dict(state="failed", pid=os.getpid(),
                      started_at=started, finished_at=utc_now(),
                      output=os.path.abspath(output),
                      error=f"{type(exc).__name__}: {exc}")
        _atomic_json(status, failed)
        return 1, failed
    child_conn.close()
    deadline = max(1.0, float(max_runtime_seconds))
    process.join(deadline)
    if process.is_alive():
        process.terminate()
        process.join(timeout=2.0)
        if process.is_alive():
            process.kill()
            process.join()
        parent_conn.close()
        failed = dict(
            state="failed", pid=os.getpid(), started_at=started,
            finished_at=utc_now(), output=os.path.abspath(output),
            error=("TimeoutError: daily scan exceeded "
                   f"{max_runtime_seconds} seconds"))
        _atomic_json(status, failed)
        return 1, failed

    if parent_conn.poll(0.5):
        message = parent_conn.recv()
    else:
        message = dict(code=1, payload=dict(
            state="failed",
            error=("ChildProcessError: scan child exited "
                   f"with code {process.exitcode} without a result")))
    parent_conn.close()
    return message["code"], message["payload"]


def main(argv=None):
    args = parse_args(argv)
    code, payload = run_supervised(
        args.output, args.status, args.lock, args.workers,
        include_tier_c=args.include_tier_c,
        max_runtime_seconds=args.max_runtime_seconds)
    print(json.dumps(payload, ensure_ascii=False),
          file=(sys.stdout if code == 0 else sys.stderr))
    return code
'''
    runner = runner[:start] + replacement + runner[end:]
    runner_path.write_text(runner, encoding="utf-8")


def cleanup_bootstrap():
    Path(".github/workflows/tests.yml").write_text(
        ORIGINAL_TESTS_YML, encoding="utf-8")
    for path in (
        Path(".github/workflows/issue6-self-patch.yml"),
        Path(".github/issue6_patch.py"),
    ):
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("write-tests", "apply"))
    args = parser.parse_args()
    if args.command == "write-tests":
        write_tests()
    else:
        apply_code()
        cleanup_bootstrap()


if __name__ == "__main__":
    main()
