#!/usr/bin/env python3
"""Fail-closed Polymarket settlement collection for paper evaluation.

Only public Gamma data is read.  A city-day becomes final only when the event
and every constituent market are closed, the saved resolution contract and
bucket set still match, and exactly one YES price is the binary value 1 while
all other YES prices are 0.
"""
import argparse
import hashlib
import json
import os
import tempfile
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from paper_eval import read_jsonl, validate_forecast
from wx_daily import resolution_fingerprint


SCHEMA_VERSION = 1
GAMMA_EVENTS = "https://gamma-api.polymarket.com/events?slug="


class PendingSettlement(ValueError):
    """The API evidence is not yet sufficient to call a final outcome."""


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def _hash(value):
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _parse_array(value, field):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid {field}") from exc
    if not isinstance(value, list):
        raise ValueError(f"invalid {field}")
    return value


def _binary_prices(market):
    outcomes = _parse_array(market.get("outcomes"), "outcomes")
    prices = _parse_array(market.get("outcomePrices"), "outcomePrices")
    if len(outcomes) != 2 or [str(x).strip().lower() for x in outcomes] != ["yes", "no"]:
        raise ValueError("market outcomes are not canonical YES/NO")
    if len(prices) != 2:
        raise ValueError("market outcomePrices are not binary")
    try:
        yes, no = float(prices[0]), float(prices[1])
    except (TypeError, ValueError) as exc:
        raise ValueError("market outcomePrices are not numeric") from exc
    if (yes, no) not in ((1.0, 0.0), (0.0, 1.0)):
        raise PendingSettlement("outcomePrices are not exact binary resolution evidence")
    return yes, no


def _without_id(record):
    return {key: value for key, value in record.items() if key != "settlement_id"}


def validate_settlement(record):
    clean = json.loads(_canonical(record))
    if clean.get("schema_version") != SCHEMA_VERSION or clean.get("status") != "final":
        raise ValueError("unsupported settlement schema or status")
    for key in ("event_slug", "outcome_label", "captured_at", "settled_at",
                "source_url", "resolution_fingerprint", "evidence_sha256"):
        if not isinstance(clean.get(key), str) or not clean[key].strip():
            raise ValueError(f"missing settlement field: {key}")
    ids = clean.get("forecast_ids")
    if not isinstance(ids, list) or not ids or any(not isinstance(item, str) for item in ids):
        raise ValueError("settlement has no forecast_ids")
    evidence = clean.get("evidence")
    if not isinstance(evidence, dict) or _hash(evidence) != clean["evidence_sha256"]:
        raise ValueError("settlement evidence hash mismatch")
    computed = _hash(_without_id(clean))
    supplied = clean.get("settlement_id")
    if supplied is not None and supplied != computed:
        raise ValueError("settlement_id does not match content")
    clean["settlement_id"] = computed
    return clean


def build_settlement(forecasts, event, captured_at=None):
    """Build one final record from all archived forecasts of the same event."""
    rows = [validate_forecast(row) for row in forecasts]
    if not rows:
        raise ValueError("no forecasts for settlement")
    event_slugs = {row["event_slug"] for row in rows}
    if len(event_slugs) != 1:
        raise ValueError("forecasts belong to different events")
    event_slug = next(iter(event_slugs))
    if event.get("slug") != event_slug:
        raise ValueError("Gamma event slug does not match forecast")
    fingerprints = {row["resolution_fingerprint"] for row in rows}
    schemas = {tuple((bucket["label"], bucket["lo"], bucket["hi"])
                     for bucket in row["buckets"]) for row in rows}
    if len(fingerprints) != 1 or len(schemas) != 1:
        raise ValueError("forecast contracts or bucket schemas disagree")
    fingerprint = next(iter(fingerprints))
    labels = tuple(item[0] for item in next(iter(schemas)))
    if event.get("closed") is not True:
        raise PendingSettlement("event is not closed")
    description = event.get("description")
    if not isinstance(description, str) or resolution_fingerprint(description) != fingerprint:
        raise ValueError("resolution fingerprint changed or is unavailable")
    markets = event.get("markets")
    if not isinstance(markets, list):
        raise ValueError("Gamma event has no markets")
    by_label = {}
    for market in markets:
        label = market.get("groupItemTitle")
        if label in by_label:
            raise ValueError("duplicate Gamma bucket label")
        by_label[label] = market
    if set(by_label) != set(labels):
        raise ValueError("Gamma bucket set does not match forecast bucket set")
    winner = []
    evidence_markets = []
    condition_ids = []
    market_ids = []
    for label in labels:
        market = by_label[label]
        if market.get("closed") is not True:
            raise PendingSettlement(f"market {label} is not closed")
        accepting_orders = market.get("acceptingOrders")
        if accepting_orders is True:
            raise PendingSettlement(f"market {label} still accepts orders")
        if accepting_orders is not False:
            raise ValueError(f"market {label} has no final acceptingOrders flag")
        condition_id = market.get("conditionId") or market.get("condition_id")
        if not isinstance(condition_id, str) or not condition_id:
            raise ValueError(f"market {label} has no conditionId")
        market_id = market.get("id")
        if market_id in (None, ""):
            raise ValueError(f"market id is missing for {label}")
        condition_ids.append(condition_id)
        market_ids.append(str(market_id))
        yes, no = _binary_prices(market)
        if yes == 1.0:
            winner.append(label)
        evidence_markets.append({
            "label": label,
            "market_id": str(market_id),
            "condition_id": condition_id,
            "closed": True,
            "accepting_orders": False,
            "outcome_prices": [yes, no],
        })
    if len(set(condition_ids)) != len(condition_ids):
        raise ValueError("conditionIds are not unique")
    if len(set(market_ids)) != len(market_ids):
        raise ValueError("market ids are not unique")
    if len(winner) != 1:
        raise PendingSettlement(f"expected one final YES winner, found {len(winner)}")
    now = captured_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    evidence = {
        "event_id": str(event.get("id") or ""),
        "event_slug": event_slug,
        "event_closed": True,
        "resolution_fingerprint": fingerprint,
        "markets": evidence_markets,
    }
    record = {
        "schema_version": SCHEMA_VERSION,
        "status": "final",
        "event_slug": event_slug,
        "outcome_label": winner[0],
        "weather_date": rows[0]["weather_date"],
        "captured_at": now,
        "settled_at": event.get("closedTime") or event.get("closed_time") or now,
        "source_url": GAMMA_EVENTS + urllib.parse.quote(event_slug),
        "resolution_fingerprint": fingerprint,
        "forecast_ids": sorted(row["forecast_id"] for row in rows),
        "evidence": evidence,
        "evidence_sha256": _hash(evidence),
    }
    record["settlement_id"] = _hash(record)
    return validate_settlement(record)


def append_settlements(path, records):
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    existing = []
    if os.path.exists(path):
        for number, row in enumerate(read_jsonl(path), 1):
            try:
                existing.append(validate_settlement(row))
            except ValueError as exc:
                raise ValueError(f"invalid settlement ledger line {number}: {exc}") from exc
    by_id = {row["settlement_id"] for row in existing}
    by_event = {row["event_slug"]: row for row in existing}
    added = []
    for raw in records:
        row = validate_settlement(raw)
        if row["settlement_id"] in by_id:
            continue
        previous = by_event.get(row["event_slug"])
        if previous is not None:
            semantic_keys = ("outcome_label", "weather_date", "resolution_fingerprint",
                             "forecast_ids", "evidence_sha256")
            if all(previous[key] == row[key] for key in semantic_keys):
                continue
            raise ValueError("conflicting final settlement for " + row["event_slug"])
        by_id.add(row["settlement_id"])
        by_event[row["event_slug"]] = row
        added.append(row)
    if not added:
        return 0
    fd, temporary = tempfile.mkstemp(prefix=".settlement-", suffix=".jsonl",
                                     dir=directory, text=True)
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


def collect_settlements(forecasts, fetch, captured_at=None):
    grouped = {}
    for raw in forecasts:
        row = validate_forecast(raw)
        grouped.setdefault(row["event_slug"], []).append(row)
    result = {"final": [], "pending": [], "rejected": []}
    for event_slug in sorted(grouped):
        url = GAMMA_EVENTS + urllib.parse.quote(event_slug)
        try:
            events = fetch(url)
            if not isinstance(events, list) or len(events) != 1:
                raise ValueError("Gamma did not return exactly one event")
            result["final"].append(build_settlement(grouped[event_slug], events[0], captured_at))
        except PendingSettlement as exc:
            result["pending"].append({"event_slug": event_slug, "reason": str(exc)})
        except Exception as exc:
            result["rejected"].append({"event_slug": event_slug, "reason": str(exc)})
    return result


def get(url):
    request = urllib.request.Request(url, headers={"User-Agent": "wx-settlement/1.0"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("forecasts", help="paper_forecasts.jsonl")
    parser.add_argument("settlements", help="append-only settlements.jsonl")
    args = parser.parse_args(argv)
    result = collect_settlements(read_jsonl(args.forecasts), fetch=get)
    added = append_settlements(args.settlements, result["final"])
    print(json.dumps({"added": added, "final": len(result["final"]),
                      "pending": result["pending"], "rejected": result["rejected"]},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
