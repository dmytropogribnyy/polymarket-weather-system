"""Блокер 2: исполнимый размер комбо (минимальные лоты, потолки, десятичные границы)."""
import unittest

from tests.support import FakeFetch, book, combo_step  # noqa: F401
import wx_daily as w

MP = w.MarketParams(fee_rate=0.05, tick=0.01, min_order=1.0, min_shares=0.0, source="test")


def books(**per_token):
    return FakeFetch({f"token_id={t}": book(levels) for t, levels in per_token.items()})


class TestDecimalBoundary(unittest.TestCase):
    def test_exact_one_dollar_lot_is_executable(self):
        """Аск 10¢ + комиссия = 10.45¢: ровно $1.00 набирается точно.

        Двоичная арифметика даёт здесь 0.9999999999999999 и отбрасывает
        полностью исполнимую ногу — деньги обязаны считаться десятичными.
        """
        a = 0.10 + 0.05*0.10*(1-0.10)                    # полная цена ноги
        shares = 1.0/a                                   # ровно $1.00 по десятичной арифметике
        self.assertLess(shares*a, 1.0)                   # ловушка двоичной дроби
        step = combo_step(stake=4.0, asks=(0.10, 0.10), tids=("a", "b"),
                          leg_p=(0.35, 0.35), cost=0.209)
        f = books(a=[(0.10, shares)], b=[(0.10, shares)])
        ex = w.combo_lots(step, MP, 2.0, f)
        self.assertTrue(ex["ok"], ex.get("reason"))
        self.assertEqual(len(ex["lots"]), 2)
        for lot in ex["lots"]:
            self.assertGreaterEqual(lot["usd"], MP.min_order)

    def test_min_lot_uses_full_price_with_market_fee(self):
        step = combo_step(stake=10.0, asks=(0.10, 0.10), tids=("a", "b"),
                          leg_p=(0.35, 0.35), cost=0.209)
        f = books(a=[(0.10, 1000)], b=[(0.10, 1000)])
        ex = w.combo_lots(step, MP, 2.0, f)
        self.assertTrue(ex["ok"], ex.get("reason"))
        self.assertLessEqual(ex["total_usd"], 2.0)
        self.assertAlmostEqual(ex["min_usd"], 2.0, places=2)


class TestCaps(unittest.TestCase):
    def test_total_never_exceeds_requested_stake(self):
        step = combo_step(stake=2.5, asks=(0.10, 0.20), tids=("a", "b"),
                          leg_p=(0.30, 0.40), cost=0.315)
        f = books(a=[(0.10, 10000)], b=[(0.20, 10000)])
        ex = w.combo_lots(step, MP, 100.0, f)
        self.assertTrue(ex["ok"], ex.get("reason"))
        self.assertLessEqual(ex["total_usd"], 2.5 + 1e-9)

    def test_total_never_exceeds_remaining_budget(self):
        step = combo_step(stake=50.0, asks=(0.10, 0.20), tids=("a", "b"),
                          leg_p=(0.30, 0.40), cost=0.315)
        f = books(a=[(0.10, 10000)], b=[(0.20, 10000)])
        ex = w.combo_lots(step, MP, 3.0, f)
        self.assertTrue(ex["ok"], ex.get("reason"))
        self.assertLessEqual(ex["total_usd"], 3.0 + 1e-9)

    def test_min_lots_over_budget_mean_no_bet(self):
        """Два минимальных ордера по $1 не влезают в остаток $1.50 — НЕ СТАВИМ."""
        step = combo_step(stake=5.0, asks=(0.10, 0.20), tids=("a", "b"),
                          leg_p=(0.30, 0.40), cost=0.315)
        f = books(a=[(0.10, 10000)], b=[(0.20, 10000)])
        ex = w.combo_lots(step, MP, 1.5, f)
        self.assertFalse(ex["ok"])
        self.assertEqual(ex["total_usd"], 0.0)
        self.assertTrue(ex["reason"])

    def test_bigger_market_minimum_is_respected(self):
        big = MP._replace(min_order=5.0)
        step = combo_step(stake=6.0, asks=(0.10, 0.20), tids=("a", "b"),
                          leg_p=(0.30, 0.40), cost=0.315)
        f = books(a=[(0.10, 10000)], b=[(0.20, 10000)])
        ex = w.combo_lots(step, big, 6.0, f)
        self.assertFalse(ex["ok"])
        self.assertIn("$", ex["reason"])


class TestSurvivingLegs(unittest.TestCase):
    def test_single_surviving_leg_is_not_a_combo(self):
        step = combo_step(stake=4.0, asks=(0.10, 0.20), tids=("a", "b"),
                          leg_p=(0.30, 0.40), cost=0.315)
        f = books(a=[(0.10, 10000)], b=[])
        ex = w.combo_lots(step, MP, 5.0, f)
        self.assertFalse(ex["ok"])
        self.assertEqual(ex["total_usd"], 0.0)

    def test_unavailable_book_is_skipped_not_guessed(self):
        step = combo_step(stake=4.0, asks=(0.10, 0.20), tids=("a", "b"),
                          leg_p=(0.30, 0.40), cost=0.315)
        f = FakeFetch({"token_id=a": book([(0.10, 10000)]),
                       "token_id=b": RuntimeError("книга недоступна")})
        ex = w.combo_lots(step, MP, 5.0, f)
        self.assertFalse(ex["ok"])
        self.assertTrue(any(s["bucket"] for s in ex["skipped"]))

    def test_thin_book_leg_is_dropped(self):
        step = combo_step(stake=5.0, asks=(0.10, 0.20), tids=("a", "b"),
                          leg_p=(0.30, 0.40), cost=0.315)
        f = books(a=[(0.10, 10000)], b=[(0.20, 0.5), (0.90, 10000)])
        ex = w.combo_lots(step, MP, 5.0, f)
        self.assertFalse(ex["ok"])
        self.assertTrue(any("тонкая" in s["why"] or "объёма" in s["why"] for s in ex["skipped"]))


if __name__ == "__main__":
    unittest.main()
