"""Блокер 4: fail-closed контракт резолюции (источник, станция, единицы)."""
import unittest

from tests.support import FakeFetch  # noqa: F401
import wx_daily as w

VALID = ("This market will resolve to the temperature reported by Weather Underground "
         "for station ZUUU (Chengdu) in degrees Celsius on August 3, 2026.")

# Точная копия живых правил Chengdu, включая UI-подсказку о переключении F/C
LIVE_CHENGDU_WITH_TOGGLE = (
    "This market will resolve to the temperature reported by Weather Underground "
    "for station ZUUU (Chengdu) in degrees Celsius on August 3, 2026. "
    "To toggle between Fahrenheit and Celsius, click the gear icon on the "
    "Weather Underground page."
)


class TestParseResolution(unittest.TestCase):
    def test_valid_rules_are_parsed(self):
        r = w.parse_resolution(VALID)
        self.assertEqual(r["sources"], ["wunderground"])
        self.assertEqual(r["units"], ["C"])
        self.assertIn("ZUUU", r["stations"])
        self.assertEqual(r["known_stations"], ["ZUUU"])

    def test_fingerprint_changes_with_rules(self):
        self.assertNotEqual(w.resolution_fingerprint(VALID),
                            w.resolution_fingerprint(VALID.replace("ZUUU", "ZUCK")))
        self.assertEqual(w.resolution_fingerprint(VALID),
                         w.resolution_fingerprint("  " + VALID.replace(" for", "  for") + " "))


class TestCheckResolution(unittest.TestCase):
    def setUp(self):
        self.seen = {}

    def check(self, desc, unit="C", station="ZUUU", eslug="highest-temperature-in-chengdu-on-august-3-2026"):
        return w.check_resolution(eslug, desc, unit, station, seen=self.seen)

    def test_valid_rules_pass(self):
        ok, det = self.check(VALID)
        self.assertTrue(ok, det.get("reason"))
        self.assertIsNone(det["reason"])

    def test_empty_rules_are_no_bet(self):
        for desc in (None, "", "   ", "\n\t "):
            ok, det = self.check(desc)
            self.assertFalse(ok)
            self.assertIn("пуст", det["reason"])

    def test_unparseable_rules_are_no_bet(self):
        ok, det = self.check("Market resolves per the official data.")
        self.assertFalse(ok)
        self.assertTrue(det["reason"])

    def test_source_mismatch_is_no_bet(self):
        ok, det = self.check(VALID.replace("Weather Underground", "AccuWeather"))
        self.assertFalse(ok)
        self.assertIn("сточник", det["reason"])

    def test_contradictory_sources_are_no_bet(self):
        ok, det = self.check(VALID + " Backup source: NOAA station data.")
        self.assertFalse(ok)
        self.assertIn("ротиворечив", det["reason"])

    def test_station_mismatch_is_no_bet(self):
        ok, det = self.check(VALID.replace("ZUUU", "ZUCK"))
        self.assertFalse(ok)
        self.assertIn("танция", det["reason"])

    def test_missing_station_is_no_bet(self):
        ok, det = self.check("Resolves by Weather Underground in degrees Celsius.")
        self.assertFalse(ok)
        self.assertIn("танция", det["reason"])

    def test_units_mismatch_is_no_bet(self):
        ok, det = self.check(VALID.replace("degrees Celsius", "degrees Fahrenheit"))
        self.assertFalse(ok)
        self.assertIn("F", det["reason"])

    def test_unknown_units_are_no_bet(self):
        ok, det = self.check(VALID.replace("in degrees Celsius", "in kelvins"))
        self.assertFalse(ok)
        self.assertIn("диниц", det["reason"])

    def test_contradictory_units_are_no_bet(self):
        ok, det = self.check(VALID + " Values are published in degrees Fahrenheit.")
        self.assertFalse(ok)
        self.assertIn("ротиворечив", det["reason"])

    def test_live_chengdu_rules_with_ui_toggle_sentence_pass(self):
        """Живые правила Chengdu содержат UI-подсказку 'To toggle between Fahrenheit
        and Celsius, click the gear icon...'.  Эта фраза — настройка отображения,
        а не нормативная единица измерения.  parse_resolution обязан её игнорировать
        и вернуть units=['C'], а check_resolution — не выдать NO BET."""
        r = w.parse_resolution(LIVE_CHENGDU_WITH_TOGGLE)
        self.assertEqual(r["units"], ["C"],
                         "UI-подсказка о Fahrenheit не должна засорять нормативные единицы")
        ok, det = self.check(LIVE_CHENGDU_WITH_TOGGLE)
        self.assertTrue(ok, det.get("reason"))
        self.assertIsNone(det["reason"])

    def test_changed_rules_are_no_bet(self):
        ok, _ = self.check(VALID)
        self.assertTrue(ok)
        ok, det = self.check(VALID + " Updated: resolution source may change.")
        self.assertFalse(ok)
        self.assertIn("изменил", det["reason"])


class TestScreenIsFailClosed(unittest.TestCase):
    """Интеграция: `screen` не торгует рынок с непройденным контрактом."""

    def _fetch(self, description, volume=50000):
        ens_time = [f"2026-08-04T{h:02d}:00" for h in range(24)]
        hourly = {"time": ens_time}
        for i, model in enumerate(("ecmwf_ifs025", "gfs025", "icon_seamless", "gem_global")):
            for member in range(8):
                hourly[f"temperature_2m_{model}_member{member:02d}"] = [30.0 + 0.1*member + 0.05*i]*24
        markets = []
        for t, ask in (("29°C or below", 0.10), ("30°C", 0.30), ("31°C", 0.30), ("32°C or higher", 0.35)):
            markets.append(dict(groupItemTitle=t, bestBid=ask-0.01, bestAsk=ask,
                                outcomePrices='["%.2f", "%.2f"]' % (ask, 1-ask),
                                clobTokenIds='["tok-%s", "tok-%s-no"]' % (t[:2], t[:2]),
                                conditionId="0xc", taker_base_fee=500,
                                minimum_tick_size=0.01, minimum_order_size=1.0))
        event = [dict(closed=False, volume=volume, description=description, markets=markets,
                      title="Highest temperature in Chengdu")]
        return FakeFetch({"ensemble-api": dict(hourly=hourly),
                          "gamma-api.polymarket.com/events": event})

    def _cal(self):
        fam = dict(bias=0.0, std=1.0, n=8, se=0.2, spread2=0.25)
        return dict(fams={"1": {f: dict(fam) for f in ("ec", "gf", "ic", "gm")},
                          "2": {f: dict(fam) for f in ("ec", "gf", "ic", "gm")}},
                    tiers={"1": "A", "2": "A"}, tier="A", bias=0.0, std=1.0, n=8)

    def test_empty_rules_produce_no_trades(self):
        w.RES_FAILS.clear(); w.RES_SEEN.clear()
        trades = w.screen("chengdu", self._cal(), [(1, "2026-08-04")], fetch=self._fetch(""))
        self.assertEqual(trades, [])
        self.assertTrue(w.RES_FAILS)

    def test_valid_rules_pass_the_contract(self):
        w.RES_FAILS.clear(); w.RES_SEEN.clear(); w.POOL_FAILS.clear(); w.PARAM_FAILS.clear()
        w.PAPER_FORECASTS.clear()
        w.screen("chengdu", self._cal(), [(1, "2026-08-04")], fetch=self._fetch(VALID))
        self.assertEqual(w.RES_FAILS, [])
        self.assertEqual(w.PARAM_FAILS, [])
        self.assertEqual(w.POOL_FAILS, [])
        self.assertEqual(len(w.PAPER_FORECASTS), 1)
        snap = w.PAPER_FORECASTS[0]
        self.assertEqual(snap["event_slug"], "highest-temperature-in-chengdu-on-august-4-2026")
        self.assertEqual(snap["resolution_fingerprint"], w.parse_resolution(VALID)["fingerprint"])
        for key in ("p_model", "p_shrunk", "p_market"):
            self.assertAlmostEqual(sum(b[key] for b in snap["buckets"]), 1.0, places=6)

    def test_paper_forecast_is_kept_when_volume_is_too_low_to_trade(self):
        w.PAPER_FORECASTS.clear(); w.RES_SEEN.clear()
        trades = w.screen("chengdu", self._cal(), [(1, "2026-08-04")],
                          fetch=self._fetch(VALID, volume=100))
        self.assertEqual(trades, [])
        self.assertEqual(len(w.PAPER_FORECASTS), 1)

    def test_paper_forecast_is_kept_when_trade_params_fail_closed(self):
        """Trade eligibility must never censor the independent paper dataset."""
        w.PAPER_FORECASTS.clear(); w.RES_SEEN.clear(); w.PARAM_FAILS.clear()
        fetch = self._fetch(VALID)
        event = fetch.routes["gamma-api.polymarket.com/events"][0]
        for market in event["markets"]:
            market["taker_base_fee"] = None
            market["feesEnabled"] = True
            market["feeSchedule"] = {"rate": 0.05, "exponent": 3,
                                     "takerOnly": True}
        trades = w.screen("chengdu", self._cal(), [(1, "2026-08-04")], fetch=fetch)
        self.assertEqual(trades, [])
        self.assertTrue(w.PARAM_FAILS)
        self.assertEqual(len(w.PAPER_FORECASTS), 1)

    def test_station_mismatch_produces_no_trades(self):
        w.RES_FAILS.clear(); w.RES_SEEN.clear()
        desc = VALID.replace("ZUUU", "ZUCK")
        trades = w.screen("chengdu", self._cal(), [(1, "2026-08-04")], fetch=self._fetch(desc))
        self.assertEqual(trades, [])
        self.assertTrue(any("танция" in x for x in w.RES_FAILS))


if __name__ == "__main__":
    unittest.main()
