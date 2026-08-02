"""Блокер 1: единый распределитель бюджета по ДАТЕ ПОГОДЫ.

Потолок $5 действует на все погодные рекомендации одной даты резолюции —
максимумы, минимумы, серия и одиночные ставки, — включая уже исполненные
позиции и уже выданные в этом прогоне рекомендации.
"""
import unittest

from tests.support import combo_step  # noqa: F401
import wx_daily as w


class TestWeatherDateKey(unittest.TestCase):
    def test_date_comes_from_resolution_not_trade_day(self):
        self.assertEqual(w.weather_date_of_slug("highest-temperature-in-chengdu-on-august-3-2026"),
                         "2026-08-03")
        self.assertEqual(w.weather_date_of_slug("lowest-temperature-in-tokyo-on-december-31-2025"),
                         "2025-12-31")
        self.assertIsNone(w.weather_date_of_slug("bitcoin-above-on-august-3-2026"))
        self.assertIsNone(w.weather_date_of_slug(""))
        self.assertIsNone(w.weather_date_of_slug(None))


class TestBudgetAllocator(unittest.TestCase):
    def test_single_pot_per_weather_date(self):
        a = w.BudgetAllocator()
        self.assertEqual(a.remaining("2026-08-03"), 5.0)
        self.assertEqual(a.reserve("2026-08-03", 3.0, tag="max"), 3.0)
        self.assertEqual(a.remaining("2026-08-03"), 2.0)
        self.assertEqual(a.reserve("2026-08-03", 3.0, tag="min"), 2.0)
        self.assertEqual(a.remaining("2026-08-03"), 0.0)
        self.assertEqual(a.reserve("2026-08-03", 1.0, tag="series"), 0.0)

    def test_other_weather_date_has_its_own_pot(self):
        a = w.BudgetAllocator()
        a.reserve("2026-08-03", 5.0)
        self.assertEqual(a.remaining("2026-08-03"), 0.0)
        self.assertEqual(a.remaining("2026-08-04"), 5.0)

    def test_executed_positions_count_against_the_cap(self):
        a = w.BudgetAllocator(spent_total=4.0, spent_by_date={"2026-08-03": 4.0})
        self.assertEqual(a.remaining("2026-08-03"), 1.0)
        self.assertEqual(a.reserve("2026-08-03", 5.0), 1.0)
        self.assertEqual(a.remaining("2026-08-03"), 0.0)

    def test_overall_daily_cap_also_binds(self):
        a = w.BudgetAllocator(day_limit=15.0, spent_total=13.5)
        self.assertEqual(a.remaining("2026-08-03"), 1.5)
        a2 = w.BudgetAllocator(day_limit=6.0)
        a2.reserve("2026-08-03", 5.0)
        self.assertEqual(a2.remaining("2026-08-04"), 1.0)

    def test_below_minimum_order_is_not_granted(self):
        a = w.BudgetAllocator(spent_by_date={"2026-08-03": 4.5})
        self.assertEqual(a.remaining("2026-08-03"), 0.5)
        self.assertEqual(a.reserve("2026-08-03", 0.5), 0.0)

    def test_unknown_date_fails_closed(self):
        a = w.BudgetAllocator()
        self.assertEqual(a.remaining(None), 0.0)
        self.assertEqual(a.reserve(None, 3.0), 0.0)

    def test_snapshot_reports_allocations(self):
        a = w.BudgetAllocator(spent_total=1.0, spent_by_date={"2026-08-03": 1.0})
        a.reserve("2026-08-03", 2.0, tag="max")
        snap = a.snapshot()
        self.assertEqual(snap["weather_cap"], 5.0)
        self.assertEqual(snap["by_weather_date"]["2026-08-03"]["spent"], 1.0)
        self.assertEqual(snap["by_weather_date"]["2026-08-03"]["allocated"], 2.0)
        self.assertEqual(snap["by_weather_date"]["2026-08-03"]["left"], 2.0)
        self.assertEqual([x["tag"] for x in snap["allocations"]], ["max"])


class TestPortfolioFeedsAllocator(unittest.TestCase):
    def test_spent_grouped_by_weather_date(self):
        from tests.support import FakeFetch
        positions = [dict(title="Chengdu 30°C", outcome="Yes", size=10.0, avgPrice=0.1,
                          curPrice=0.1, initialValue=3.0, eventSlug="highest-temperature-in-chengdu-on-august-3-2026"),
                     dict(title="Tokyo 31°C", outcome="Yes", size=5.0, avgPrice=0.2,
                          curPrice=0.2, initialValue=1.0, eventSlug="highest-temperature-in-tokyo-on-august-4-2026")]
        f = FakeFetch({"data-api.polymarket.com/positions": positions,
                       "data-api.polymarket.com/value": [dict(value="12.5")],
                       "data-api.polymarket.com/activity": []})
        pf = w.portfolio_scan(wallet="0xtest", fetch=f)
        self.assertEqual(pf["spent_by_weather_date"]["2026-08-03"], 3.0)
        self.assertEqual(pf["spent_by_weather_date"]["2026-08-04"], 1.0)
        a = w.BudgetAllocator(spent_total=pf["spent_today"], spent_by_date=pf["spent_by_weather_date"])
        self.assertEqual(a.remaining("2026-08-03"), 2.0)


if __name__ == "__main__":
    unittest.main()
