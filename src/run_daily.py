#!/usr/bin/env python3
"""Durable Linux entrypoint for the long daily scan.

The scheduler runs this command in the foreground.  A non-blocking OS lock
prevents duplicate scans, status is always atomic, and the last good report is
replaced only after a complete in-memory report has been serialized and fsynced.
"""
import argparse
import fcntl
import hashlib
import json
import os
import signal
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone

import wx_daily


class AlreadyRunning(RuntimeError):
    pass


def utc_now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _atomic_json(path, payload):
    path = os.path.abspath(path)
    parent = os.path.dirname(path)
    os.makedirs(parent, exist_ok=True)
    data = (json.dumps(payload, ensure_ascii=False, indent=1) + "\n").encode("utf-8")
    fd, temporary = tempfile.mkstemp(prefix="." + os.path.basename(path) + ".",
                                     suffix=".tmp", dir=parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        # Persist the directory entry as well as the file contents.
        try:
            dir_fd = os.open(parent, os.O_RDONLY)
            try: os.fsync(dir_fd)
            finally: os.close(dir_fd)
        except OSError:
            pass
    except BaseException:
        try: os.unlink(temporary)
        except FileNotFoundError: pass
        raise
    return dict(report_sha256=hashlib.sha256(data).hexdigest(),
                report_bytes=len(data))


@contextmanager
def exclusive_lock(path):
    path = os.path.abspath(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a+", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise AlreadyRunning(f"daily scan already holds {path}") from exc
        handle.seek(0)
        handle.truncate()
        handle.write(json.dumps({"pid": os.getpid(), "started_at": utc_now()}))
        handle.flush()
        os.fsync(handle.fileno())
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def run_once(output, status, lock, workers=None, builder=None,
             include_tier_c=False):
    started = utc_now()
    with exclusive_lock(lock):
        running = dict(state="running", pid=os.getpid(), started_at=started,
                       heartbeat_at=started, output=os.path.abspath(output))
        _atomic_json(status, running)
        progress_lock = threading.Lock()
        last_progress = [0.0]
        last_stage = [None]
        heartbeat_stop = threading.Event()

        def heartbeat_loop():
            while not heartbeat_stop.wait(15.0):
                with progress_lock:
                    running["heartbeat_at"] = utc_now()
                    _atomic_json(status, running)

        heartbeat_thread = threading.Thread(target=heartbeat_loop,
                                            name="daily-heartbeat", daemon=True)
        heartbeat_thread.start()

        def stop_heartbeat():
            heartbeat_stop.set()
            heartbeat_thread.join(timeout=2.0)

        def publish_progress(event):
            now_mono = time.monotonic()
            complete = (event.get("total") is not None and
                        event.get("completed") == event.get("total"))
            with progress_lock:
                stage_changed = event.get("stage") != last_stage[0]
                if not stage_changed and not complete and now_mono-last_progress[0] < 5.0:
                    return
                running.update(event)
                running["heartbeat_at"] = utc_now()
                _atomic_json(status, running)
                last_progress[0] = now_mono
                last_stage[0] = event.get("stage")
        try:
            if builder is None:
                prior_report = None
                try:
                    with open(output, encoding="utf-8") as handle:
                        candidate = json.load(handle)
                    if isinstance(candidate, dict):
                        prior_report = candidate
                except (FileNotFoundError, OSError, ValueError):
                    pass
                report = wx_daily.build_report(
                    workers=workers, include_tier_c=include_tier_c,
                    progress=publish_progress,
                    prior_report=prior_report)
            else:
                report = builder(workers=workers)
            if not isinstance(report, dict) or not report.get("generated"):
                raise ValueError("daily builder returned an invalid report")
            if not isinstance(report.get("paper_forecasts"), list):
                raise ValueError("daily report has no paper_forecasts list")
            report_meta = _atomic_json(output, report)
        except BaseException as exc:
            stop_heartbeat()
            _atomic_json(status, dict(state="failed", pid=os.getpid(),
                                      started_at=started, finished_at=utc_now(),
                                      output=os.path.abspath(output),
                                      error=f"{type(exc).__name__}: {str(exc)[:500]}"))
            raise
        stop_heartbeat()
        final = dict(state="success", pid=os.getpid(), started_at=started,
                     finished_at=utc_now(), output=os.path.abspath(output),
                     paper_forecasts=len(report["paper_forecasts"]), **report_meta)
        _atomic_json(status, final)
        return final


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Run wx_daily atomically")
    parser.add_argument("--output", default="report.json")
    parser.add_argument("--status", default="scan_status.json")
    parser.add_argument("--lock", default="scan.lock")
    parser.add_argument("--workers", type=int, default=None,
                        help="bounded network workers; default WX_WORKERS or 4, max 8")
    parser.add_argument("--include-tier-c", action="store_true",
                        help="also screen historically unreliable tier-C cities")
    parser.add_argument("--max-runtime-seconds", type=int, default=1500,
                        help="hard process deadline; default 1500 (25 minutes)")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    def deadline(_signum, _frame):
        raise TimeoutError(f"daily scan exceeded {args.max_runtime_seconds} seconds")

    previous_handler = signal.signal(signal.SIGALRM, deadline)
    signal.alarm(max(1, args.max_runtime_seconds))
    try:
        try:
            result = run_once(args.output, args.status, args.lock, args.workers,
                              include_tier_c=args.include_tier_c)
        except AlreadyRunning as exc:
            print(json.dumps({"state": "already_running", "error": str(exc)}, ensure_ascii=False),
                  file=sys.stderr)
            return 75
        except BaseException as exc:
            print(json.dumps({"state": "failed", "error": f"{type(exc).__name__}: {exc}"},
                             ensure_ascii=False), file=sys.stderr)
            return 1
        print(json.dumps(result, ensure_ascii=False))
        return 0
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous_handler)


if __name__ == "__main__":
    raise SystemExit(main())
