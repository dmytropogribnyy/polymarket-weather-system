"""Paper-evaluation: immutable forecasts and proper city-day scores."""
import json
import math
import os
import tempfile
import unittest

from tests import support  # noqa: F401  (adds src/ to sys.path)
import paper_eval as pe


def forecast(event="event-a", captured="2026-08-03T12:00:00Z",
             model=(0.2, 0.5, 0.3), shrunk=(0.25, 0.5, 0.25),
             market=(0.4, 0.4, 0.2)):
    labels = ("29°C or below", "30°C", "31°C or higher")
    ranges = ((-999.0, 29.5), (29.5, 30.5), (30.5, 999.0))
    return {
        "schema_version": 1,
        "captured_at": captured,
        "event_slug": event,
        "city_slug": "chengdu",
        "city": "Чэнду",
        "weather_date": "2026-08-04",
        "lead": 1,
        "kind": "max",
        "unit": "C",
        "station": "ZUUU",
        "tier": "A",
        "resolution_fingerprint": "abc123",
        "buckets": [
            {"label": label, "lo": lo, "hi": hi,
             "p_model": model[i], "p_shrunk": shrunk[i], "p_market": market[i]}
            for i, (label, (lo, hi)) in enumerate(zip(labels, ranges))
        ],
    }


class TestValidation(unittest.TestCase):
    def test_accepts_complete_normalized_distribution(self):
        clean = pe.validate_forecast(forecast())
        self.assertEqual(clean["event_slug"], "event-a")
        self.assertEqual(len(clean["forecast_id"]), 64)

    def test_rejects_probability_mass_or_coverage_gaps(self):
        bad_mass = forecast(model=(0.2, 0.2, 0.2))
        with self.assertRaisesRegex(ValueError, "sum"):
            pe.validate_forecast(bad_mass)
        bad_range = forecast()
        bad_range["buckets"][1]["lo"] = 29.6
        with self.assertRaisesRegex(ValueError, "coverage"):
            pe.validate_forecast(bad_range)


class TestScoring(unittest.TestCase):
    def test_log_loss_and_normalized_rps(self):
        scored = pe.score_forecast(forecast(), "30°C")
        self.assertAlmostEqual(scored["model"]["log_loss"], -math.log(0.5), places=12)
        # CDF errors: (0.2 - 0)^2 + (0.7 - 1)^2, normalized by K-1.
        self.assertAlmostEqual(scored["model"]["rps"], 0.065, places=12)
        self.assertEqual(scored["observed_index"], 1)

    def test_history_compares_market_model_shrinkage_and_selects_lambda(self):
        records = [
            forecast("event-a", model=(0.05, 0.90, 0.05),
                     shrunk=(0.2, 0.6, 0.2), market=(0.45, 0.10, 0.45)),
            forecast("event-b", captured="2026-08-04T12:00:00Z",
                     model=(0.90, 0.05, 0.05),
                     shrunk=(0.6, 0.2, 0.2), market=(0.10, 0.45, 0.45)),
        ]
        out = pe.score_history(records, {"event-a": "30°C", "event-b": "29°C or below"})
        self.assertEqual(out["n_city_days"], 2)
        self.assertLess(out["aggregate"]["model"]["mean_log_loss"],
                        out["aggregate"]["market"]["mean_log_loss"])
        self.assertEqual(out["lambda_selection"]["best_lambda_log_loss"], 1.0)

    def test_tail_summary_uses_all_cheap_buckets_not_only_bets(self):
        record = forecast(model=(0.04, 0.91, 0.05), shrunk=(0.03, 0.94, 0.03),
                          market=(0.02, 0.95, 0.03))
        out = pe.score_history([record], {"event-a": "29°C or below"}, tail_threshold=0.05)
        tail = out["cheap_tail"]
        self.assertEqual(tail["n_buckets"], 2)
        self.assertEqual(tail["observed"], 1)
        self.assertAlmostEqual(tail["expected_model"], 0.09)


class TestLedger(unittest.TestCase):
    def test_append_is_idempotent_but_same_event_time_cannot_change(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "forecasts.jsonl")
            first = forecast()
            self.assertEqual(pe.append_forecasts(path, [first]), 1)
            self.assertEqual(pe.append_forecasts(path, [first]), 0)
            changed = forecast(model=(0.1, 0.6, 0.3))
            with self.assertRaisesRegex(ValueError, "conflicting"):
                pe.append_forecasts(path, [changed])
            with open(path, encoding="utf-8") as fh:
                rows = [json.loads(line) for line in fh if line.strip()]
            self.assertEqual(len(rows), 1)


if __name__ == "__main__":
    unittest.main()
