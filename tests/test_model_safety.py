"""Блокер 7: безопасность модели.

1. Калибровка и тир считаются ОТДЕЛЬНО для previous_day1 и previous_day2,
   и в торговле используется тир СВОЕГО горизонта.
2. Лог-пул допустим только по полному взаимоисключающему набору исходов;
   пропавший или нераспознанный бакет — стоп, а не нормировка подмножества.
3. Из std² вычитается СРЕДНИЙ ИСТОРИЧЕСКИЙ разброс ансамбля окна калибровки,
   а не разброс сегодняшнего прогноза.
"""
import math
import unittest

from tests.support import FakeFetch  # noqa: F401
import wx_daily as w


def fam(bias=0.0, std=1.0, n=8, se=0.2, spread2=None):
    return dict(bias=bias, std=std, n=n, se=se, spread2=spread2)


class TestPerLeadCalibration(unittest.TestCase):
    def test_tier_is_computed_per_lead(self):
        good = {f: fam(std=0.5, n=8) for f in ("ec", "gf", "ic", "gm")}
        bad = {f: fam(std=3.0, n=2) for f in ("ec", "gf", "ic", "gm")}
        self.assertEqual(w.tier_of(good), "A")
        self.assertEqual(w.tier_of(bad), "C")
        cal = dict(fams={"1": good, "2": bad}, tiers={"1": w.tier_of(good), "2": w.tier_of(bad)})
        self.assertEqual(w.cal_tier(cal, 1), "A")
        self.assertEqual(w.cal_tier(cal, 2), "C")

    def test_missing_lead_calibration_fails_closed(self):
        cal = dict(fams={"1": {}, "2": {}}, tiers={"1": "C"})
        self.assertEqual(w.cal_tier(cal, 2), "C")
        self.assertEqual(w.cal_tier({}, 1), "C")
        self.assertEqual(w.cal_tier(None, 1), "C")

    def test_calibrate_returns_both_leads(self):
        from datetime import datetime, timedelta, timezone
        now = datetime.now(timezone.utc)
        days = [(now - timedelta(days=d)).strftime("%Y-%m-%d") for d in range(12, 2, -1)]
        times = [f"{d}T{h:02d}:00" for d in days for h in range(24)]
        hourly = {"time": times}
        for model, off1, off2 in (("ecmwf_ifs025", 0.5, 2.5), ("gfs_global", 0.5, 2.5),
                                  ("icon_seamless", 0.5, 2.5), ("gem_global", 0.5, 2.5)):
            hourly[f"temperature_2m_previous_day1_{model}"] = [30.0 - off1]*len(times)
            hourly[f"temperature_2m_previous_day2_{model}"] = [30.0 - off2 + (1.2 if (i // 24) % 2 == 0 else -1.2)
                                                              for i in range(len(times))]
        metar = [dict(reportTime=f"{d} 12:00:00", temp=30.0) for d in days]
        f = FakeFetch({"previous-runs-api": dict(hourly=hourly, utc_offset_seconds=0),
                       "aviationweather.gov": metar,
                       "ensemble-api": dict(hourly={"time": times,
                                                    **{f"temperature_2m_ecmwf_ifs025_member{i:02d}": [30.0+0.1*i]*len(times)
                                                       for i in range(10)}})})
        cal = w.calibrate("chengdu", fetch=f)
        self.assertIn("1", cal["fams"])
        self.assertIn("2", cal["fams"])
        self.assertIn("tiers", cal)
        b1 = cal["fams"]["1"]["ec"]["bias"]
        b2 = cal["fams"]["2"]["ec"]["bias"]
        self.assertNotEqual(b1, b2)            # горизонты калибруются раздельно
        self.assertAlmostEqual(b1, 0.5, places=2)
        self.assertAlmostEqual(b2, 2.5, places=2)
        self.assertNotEqual(cal["tiers"]["1"], cal["tiers"]["2"])


class TestCompleteDistribution(unittest.TestCase):
    def test_coverage_requires_full_mutually_exclusive_set(self):
        full = [(-999.0, 29.5), (29.5, 30.5), (30.5, 31.5), (31.5, 999.0)]
        self.assertTrue(w.coverage_ok(full))
        self.assertFalse(w.coverage_ok(full[1:]))                    # нет «или ниже»
        self.assertFalse(w.coverage_ok(full[:-1]))                   # нет «или выше»
        self.assertFalse(w.coverage_ok([full[0], full[1], full[3]]))  # дыра посередине
        self.assertFalse(w.coverage_ok([(-999.0, 30.5), (29.5, 999.0)]))  # наложение
        self.assertFalse(w.coverage_ok([]))

    def test_screen_refuses_incomplete_distribution(self):
        """Нераспознанный бакет = неполное распределение: пул не считаем."""
        times = [f"2026-08-04T{h:02d}:00" for h in range(24)]
        hourly = {"time": times}
        for i, model in enumerate(("ecmwf_ifs025", "gfs025", "icon_seamless", "gem_global")):
            for member in range(8):
                hourly[f"temperature_2m_{model}_member{member:02d}"] = [30.0 + 0.1*member + 0.05*i]*24
        titles = [("29°C or below", 0.10), ("30°C", 0.30), ("31°C", 0.30), ("Somewhere else", 0.35)]
        markets = [dict(groupItemTitle=t, bestBid=a-0.01, bestAsk=a,
                        outcomePrices='["%.2f","%.2f"]' % (a, 1-a),
                        clobTokenIds='["t-%s","t-%s-no"]' % (t[:3], t[:3]), conditionId="0xc",
                        taker_base_fee=500, minimum_tick_size=0.01, minimum_order_size=1.0)
                   for t, a in titles]
        desc = ("Resolves per Weather Underground station ZUUU in degrees Celsius.")
        f = FakeFetch({"ensemble-api": dict(hourly=hourly),
                       "gamma-api.polymarket.com/events": [dict(closed=False, volume=50000,
                                                                description=desc, markets=markets,
                                                                title="Chengdu")]})
        w.POOL_FAILS.clear(); w.RES_SEEN.clear(); w.PARSE_FAIL[0] = 0
        cal = dict(fams={"1": {f_: fam(spread2=0.25) for f_ in ("ec", "gf", "ic", "gm")}, "2": {}},
                   tiers={"1": "A", "2": "C"}, tier="A", bias=0.0, std=1.0, n=8)
        trades = w.screen("chengdu", cal, [(1, "2026-08-04")], fetch=f)
        self.assertEqual(trades, [])
        self.assertTrue(w.POOL_FAILS)


class TestResidualVariance(unittest.TestCase):
    def _day(self, members):
        return {"all": members*4, "ec": list(members), "gf": list(members),
                "ic": list(members), "gm": list(members)}

    def test_subtracts_historical_spread_not_todays(self):
        """std²=1.0, исторический разброс окна 0.09 → τ=sqrt(0.91).

        Сегодняшний ансамбль широкий (дисперсия ≈0.9): вычитание ЕГО разброса
        дало бы τ=0.6 и совсем другую вероятность.
        """
        members = [28.5, 29.0, 29.5, 30.0, 30.5, 31.0, 31.5, 32.0]
        mu = sum(members)/len(members)
        today_var = sum((x-mu)**2 for x in members)/len(members)
        self.assertGreater(today_var, 0.9)
        cal = {"1": {f_: fam(std=1.0, spread2=0.09) for f_ in ("ec", "gf", "ic", "gm")}}
        p, _ = w.fam_prob(self._day(members), (29.5, 30.5), "C", cal, 1)
        tau = math.sqrt(1.0 - 0.09)
        want = sum(w.phi((30.5-x)/tau) - w.phi((29.5-x)/tau) for x in members)/len(members)
        self.assertAlmostEqual(p, want, places=9)
        tau_wrong = math.sqrt(max(0.36, 1.0 - today_var))
        wrong = sum(w.phi((30.5-x)/tau_wrong) - w.phi((29.5-x)/tau_wrong) for x in members)/len(members)
        self.assertNotAlmostEqual(p, wrong, places=3)

    def test_todays_spread_does_not_move_the_kernel(self):
        """Ширина сегодняшнего ансамбля не должна менять ядро — только точки."""
        cal = {"1": {f_: fam(std=1.0, spread2=0.09) for f_ in ("ec", "gf", "ic", "gm")}}
        tight = [30.0, 30.0, 30.0, 30.0, 30.0, 30.0, 30.0, 30.0]
        wide = [30.0]*8
        p_tight, _ = w.fam_prob(self._day(tight), (29.5, 30.5), "C", cal, 1)
        p_wide, _ = w.fam_prob(self._day(wide), (29.5, 30.5), "C", cal, 1)
        self.assertAlmostEqual(p_tight, p_wide, places=12)
        tau = math.sqrt(0.91)
        self.assertAlmostEqual(p_tight, w.phi(0.5/tau) - w.phi(-0.5/tau), places=9)

    def test_missing_history_does_not_shrink_the_kernel(self):
        cal = {"1": {f_: fam(std=1.0, spread2=None) for f_ in ("ec", "gf", "ic", "gm")}}
        members = [29.0, 30.0, 31.0, 30.5, 29.5, 30.2, 29.8, 30.1]
        p, _ = w.fam_prob(self._day(members), (29.5, 30.5), "C", cal, 1)
        want = sum(w.phi((30.5-x)/1.0) - w.phi((29.5-x)/1.0) for x in members)/len(members)
        self.assertAlmostEqual(p, want, places=9)

    def test_kernel_floor_is_kept(self):
        cal = {"1": {f_: fam(std=0.2, spread2=0.0) for f_ in ("ec", "gf", "ic", "gm")}}
        members = [30.0]*8
        p, _ = w.fam_prob(self._day(members), (29.5, 30.5), "C", cal, 1)
        self.assertAlmostEqual(p, w.phi(0.5/0.6) - w.phi(-0.5/0.6), places=9)


if __name__ == "__main__":
    unittest.main()
