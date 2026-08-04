#!/usr/bin/env python3
"""Append-only paper forecasts and proper scoring for weather city-days.

This module never places orders and never needs wallet access.  It consumes the
full mutually-exclusive distributions emitted by ``wx_daily.py`` and later
scores them against an immutable settlement ledger.
"""
import argparse
import hashlib
import json
import math
import os
import tempfile


PROB_KEYS = ("p_model", "p_shrunk", "p_market")
SOURCES = {"model": "p_model", "shrunk": "p_shrunk", "market": "p_market"}
SCHEMA_VERSION = 1
EPS = 1e-15


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def _without_id(record):
    return {k: v for k, v in record.items() if k != "forecast_id"}


def forecast_id(record):
    return hashlib.sha256(_canonical(_without_id(record)).encode("utf-8")).hexdigest()


def validate_forecast(record):
    """Return a normalized copy or fail closed on malformed score inputs."""
    try:
        clean = json.loads(_canonical(record))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"forecast is not canonical JSON: {exc}") from exc
    if clean.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported forecast schema_version")
    for key in ("captured_at", "event_slug", "city_slug", "weather_date",
                "kind", "unit", "station", "resolution_fingerprint"):
        if not isinstance(clean.get(key), str) or not clean[key].strip():
            raise ValueError(f"missing forecast field: {key}")
    buckets = clean.get("buckets")
    if not isinstance(buckets, list) or len(buckets) < 2:
        raise ValueError("forecast needs at least two buckets")
    labels = []
    previous_hi = None
    for index, bucket in enumerate(buckets):
        label = bucket.get("label")
        if not isinstance(label, str) or not label.strip() or label in labels:
            raise ValueError("bucket labels must be non-empty and unique")
        labels.append(label)
        try:
            lo, hi = float(bucket["lo"]), float(bucket["hi"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("bucket coverage has invalid bounds") from exc
        if not (math.isfinite(lo) and math.isfinite(hi) and lo < hi):
            raise ValueError("bucket coverage has invalid bounds")
        if index == 0 and lo > -900:
            raise ValueError("bucket coverage does not include lower tail")
        if previous_hi is not None and abs(lo - previous_hi) > 1e-9:
            raise ValueError("bucket coverage has a gap or overlap")
        previous_hi = hi
        bucket["lo"], bucket["hi"] = lo, hi
        for key in PROB_KEYS:
            try:
                value = float(bucket[key])
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"invalid probability: {key}") from exc
            if not math.isfinite(value) or value < 0.0 or value > 1.0:
                raise ValueError(f"invalid probability: {key}")
            bucket[key] = value
    if previous_hi is None or previous_hi < 900:
        raise ValueError("bucket coverage does not include upper tail")
    for key in PROB_KEYS:
        total = sum(bucket[key] for bucket in buckets)
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"{key} probability sum is {total}, expected 1")
    computed = forecast_id(clean)
    supplied = clean.get("forecast_id")
    if supplied is not None and supplied != computed:
        raise ValueError("forecast_id does not match content")
    clean["forecast_id"] = computed
    return clean


def append_forecasts(path, records):
    """Atomically append validated records; exact retries are idempotent."""
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    existing = []
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            for number, line in enumerate(fh, 1):
                if line.strip():
                    try:
                        existing.append(validate_forecast(json.loads(line)))
                    except (ValueError, json.JSONDecodeError) as exc:
                        raise ValueError(f"invalid forecast ledger line {number}: {exc}") from exc
    ids = {row["forecast_id"] for row in existing}
    slots = {(row["event_slug"], row["captured_at"]): row["forecast_id"] for row in existing}
    added = []
    for raw in records:
        row = validate_forecast(raw)
        if row["forecast_id"] in ids:
            continue
        slot = (row["event_slug"], row["captured_at"])
        if slot in slots and slots[slot] != row["forecast_id"]:
            raise ValueError(f"conflicting forecast for {slot[0]} at {slot[1]}")
        ids.add(row["forecast_id"])
        slots[slot] = row["forecast_id"]
        added.append(row)
    if not added:
        return 0
    fd, temporary = tempfile.mkstemp(prefix=".paper-", suffix=".jsonl", dir=directory, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            for row in existing + added:
                fh.write(_canonical(row) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return len(added)


def _metrics(probabilities, observed_index):
    probability = max(probabilities[observed_index], EPS)
    log_loss = -math.log(probability)
    forecast_cdf = 0.0
    rps = 0.0
    for index, value in enumerate(probabilities[:-1]):
        forecast_cdf += value
        observed_cdf = 1.0 if observed_index <= index else 0.0
        rps += (forecast_cdf - observed_cdf) ** 2
    rps /= max(1, len(probabilities) - 1)
    return {"log_loss": log_loss, "rps": rps, "p_observed": probabilities[observed_index]}


def score_forecast(record, outcome_label):
    row = validate_forecast(record)
    labels = [bucket["label"] for bucket in row["buckets"]]
    if outcome_label not in labels:
        raise ValueError(f"outcome {outcome_label!r} is not a forecast bucket")
    observed = labels.index(outcome_label)
    out = {"forecast_id": row["forecast_id"], "event_slug": row["event_slug"],
           "captured_at": row["captured_at"], "weather_date": row["weather_date"],
           "outcome_label": outcome_label, "observed_index": observed}
    for source, key in SOURCES.items():
        out[source] = _metrics([bucket[key] for bucket in row["buckets"]], observed)
    return out


def _log_pool(model, market, lam):
    values = [(max(p, EPS) ** lam) * (max(q, EPS) ** (1.0 - lam))
              for p, q in zip(model, market)]
    total = sum(values)
    return [value / total for value in values]


def score_history(records, outcomes, tail_threshold=0.05):
    """Score every settled forecast and estimate lambda on observed history."""
    validated = [validate_forecast(record) for record in records]
    scored = []
    lambda_rows = []
    tail = {"n_buckets": 0, "observed": 0, "expected_model": 0.0,
            "expected_shrunk": 0.0, "expected_market": 0.0}
    for row in validated:
        outcome = outcomes.get(row["event_slug"])
        if outcome is None:
            continue
        item = score_forecast(row, outcome)
        scored.append(item)
        labels = [bucket["label"] for bucket in row["buckets"]]
        observed = labels.index(outcome)
        model = [bucket["p_model"] for bucket in row["buckets"]]
        market = [bucket["p_market"] for bucket in row["buckets"]]
        lambda_rows.append((model, market, observed))
        for index, bucket in enumerate(row["buckets"]):
            if bucket["p_market"] <= tail_threshold:
                tail["n_buckets"] += 1
                tail["observed"] += int(index == observed)
                tail["expected_model"] += bucket["p_model"]
                tail["expected_shrunk"] += bucket["p_shrunk"]
                tail["expected_market"] += bucket["p_market"]
    aggregate = {}
    for source in SOURCES:
        aggregate[source] = {
            "mean_log_loss": (sum(item[source]["log_loss"] for item in scored) / len(scored)
                              if scored else None),
            "mean_rps": (sum(item[source]["rps"] for item in scored) / len(scored)
                         if scored else None),
        }
    grid = []
    for step in range(21):
        lam = step / 20.0
        losses, rps_values = [], []
        for model, market, observed in lambda_rows:
            metrics = _metrics(_log_pool(model, market, lam), observed)
            losses.append(metrics["log_loss"])
            rps_values.append(metrics["rps"])
        grid.append({"lambda": lam,
                     "mean_log_loss": sum(losses) / len(losses) if losses else None,
                     "mean_rps": sum(rps_values) / len(rps_values) if rps_values else None})
    usable = [item for item in grid if item["mean_log_loss"] is not None]
    best_log = min(usable, key=lambda item: (item["mean_log_loss"], item["lambda"])) if usable else None
    best_rps = min(usable, key=lambda item: (item["mean_rps"], item["lambda"])) if usable else None
    return {
        "schema_version": SCHEMA_VERSION,
        "n_city_days": len(scored),
        "unsettled": len(validated) - len(scored),
        "aggregate": aggregate,
        "cheap_tail": tail,
        "lambda_selection": {
            "best_lambda_log_loss": best_log["lambda"] if best_log else None,
            "best_lambda_rps": best_rps["lambda"] if best_rps else None,
            "grid": grid,
        },
        "scores": scored,
    }


def read_jsonl(path):
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def _load_outcomes(path):
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh) if path.endswith(".json") else None
    if isinstance(data, dict):
        return data
    rows = data if isinstance(data, list) else read_jsonl(path)
    return {row["event_slug"]: row["outcome_label"] for row in rows
            if row.get("status", "final") == "final"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    capture = commands.add_parser("capture", help="append report paper_forecasts to JSONL")
    capture.add_argument("report")
    capture.add_argument("ledger")
    score = commands.add_parser("score", help="score a forecast ledger against outcomes")
    score.add_argument("ledger")
    score.add_argument("outcomes")
    score.add_argument("--output")
    args = parser.parse_args(argv)
    if args.command == "capture":
        with open(args.report, encoding="utf-8") as fh:
            report = json.load(fh)
        added = append_forecasts(args.ledger, report.get("paper_forecasts") or [])
        result = {"added": added, "ledger": args.ledger}
    else:
        result = score_history(read_jsonl(args.ledger), _load_outcomes(args.outcomes))
    rendered = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)
    if getattr(args, "output", None):
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(rendered + "\n")
    print(rendered)


if __name__ == "__main__":
    main()
