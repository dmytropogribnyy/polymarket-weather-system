"""Settlement integrity: accept only unambiguous final Polymarket evidence."""
import json
import os
import tempfile
import unittest

from tests import support  # noqa: F401
from tests.test_paper_eval import forecast
import settlement as st
import wx_daily as wx


DESC = ("This market will resolve to the temperature reported by Weather Underground "
        "for station ZUUU (Chengdu) in degrees Celsius on August 4, 2026.")


def snapshot(event="event-a"):
    row = forecast(event=event)
    row["resolution_fingerprint"] = wx.resolution_fingerprint(DESC)
    return row


def event(winner="30°C", closed=True, description=DESC, ambiguous=False):
    labels = ("29°C or below", "30°C", "31°C or higher")
    markets = []
    for index, label in enumerate(labels):
        yes = 0.999 if ambiguous and label == winner else (1.0 if label == winner else 0.0)
        markets.append({
            "id": f"market-{index}",
            "groupItemTitle": label,
            "conditionId": f"condition-{index}",
            "closed": closed,
            "acceptingOrders": not closed,
            "outcomes": json.dumps(["Yes", "No"]),
            "outcomePrices": json.dumps([str(yes), str(1.0 - yes)]),
        })
    return {"id": "gamma-event-1", "slug": "event-a", "closed": closed,
            "description": description, "markets": markets,
            "closedTime": "2026-08-04T18:00:00Z" if closed else None}


class TestFinalEvidence(unittest.TestCase):
    def test_exactly_one_binary_winner_is_final(self):
        result = st.build_settlement([snapshot()], event(),
                                     captured_at="2026-08-04T18:05:00Z")
        self.assertEqual(result["status"], "final")
        self.assertEqual(result["outcome_label"], "30°C")
        self.assertEqual(result["source_url"],
                         "https://gamma-api.polymarket.com/events?slug=event-a")
        self.assertEqual(len(result["settlement_id"]), 64)
        self.assertEqual(len(result["evidence_sha256"]), 64)

    def test_open_event_is_pending_not_guessed(self):
        with self.assertRaisesRegex(st.PendingSettlement, "not closed"):
            st.build_settlement([snapshot()], event(closed=False))

    def test_999_price_is_not_final_resolution_evidence(self):
        with self.assertRaisesRegex(st.PendingSettlement, "binary"):
            st.build_settlement([snapshot()], event(ambiguous=True))

    def test_changed_resolution_rules_fail_closed(self):
        changed = DESC.replace("ZUUU", "ZUCK")
        with self.assertRaisesRegex(ValueError, "fingerprint"):
            st.build_settlement([snapshot()], event(description=changed))

    def test_missing_or_extra_bucket_fails_closed(self):
        raw = event()
        raw["markets"].pop()
        with self.assertRaisesRegex(ValueError, "bucket set"):
            st.build_settlement([snapshot()], raw)

    def test_multiple_forecasts_must_share_contract_and_bucket_schema(self):
        a = snapshot()
        b = snapshot()
        b["captured_at"] = "2026-08-03T13:00:00Z"
        b["resolution_fingerprint"] = "different"
        with self.assertRaisesRegex(ValueError, "forecast contracts"):
            st.build_settlement([a, b], event())

        b = snapshot()
        b["captured_at"] = "2026-08-03T13:00:00Z"
        b["buckets"][0]["hi"] = 29.6
        b["buckets"][1]["lo"] = 29.6
        with self.assertRaisesRegex(ValueError, "bucket schemas"):
            st.build_settlement([a, b], event())

    def test_market_identity_is_required_for_auditable_evidence(self):
        raw = event()
        raw["markets"][0]["id"] = ""
        with self.assertRaisesRegex(ValueError, "market id"):
            st.build_settlement([snapshot()], raw)

    def test_missing_accepting_orders_flag_fails_closed(self):
        raw = event()
        raw["markets"][0].pop("acceptingOrders")
        with self.assertRaisesRegex(ValueError, "acceptingOrders"):
            st.build_settlement([snapshot()], raw)


class TestSettlementLedger(unittest.TestCase):
    def test_exact_retry_is_idempotent_and_conflicting_winner_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "settlements.jsonl")
            first = st.build_settlement([snapshot()], event())
            self.assertEqual(st.append_settlements(path, [first]), 1)
            self.assertEqual(st.append_settlements(path, [first]), 0)
            same_evidence_later = st.build_settlement(
                [snapshot()], event(), captured_at="2026-08-04T18:10:00Z")
            self.assertEqual(st.append_settlements(path, [same_evidence_later]), 0)
            other = st.build_settlement([snapshot()], event(winner="31°C or higher"))
            with self.assertRaisesRegex(ValueError, "conflicting final settlement"):
                st.append_settlements(path, [other])

    def test_batch_settles_final_and_reports_pending(self):
        rows = [snapshot("event-a"), snapshot("event-b")]

        def fetch(url):
            if "event-a" in url:
                return [event()]
            pending = event(closed=False)
            pending["slug"] = "event-b"
            return [pending]

        result = st.collect_settlements(rows, fetch=fetch,
                                        captured_at="2026-08-04T18:05:00Z")
        self.assertEqual([row["event_slug"] for row in result["final"]], ["event-a"])
        self.assertEqual(result["pending"][0]["event_slug"], "event-b")


if __name__ == "__main__":
    unittest.main()
