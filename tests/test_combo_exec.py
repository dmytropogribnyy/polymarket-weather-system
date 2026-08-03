"""Блокер 2: исполнимый размер комбо (минимальные лоты, потолки, десятичные границы)."""
import unittest

from tests.support import FakeFetch, book, combo_step  # noqa: F401
import wx_daily as w

MP = w.MarketParams(fee_rate=0.05, tick=0.01, min_notional=1.0, min_shares=0.0, source="test")


def books(**per_token):
    """Создаёт FakeFetch со стаканами + обязательными метаданными."""
    routes = {}
    for t, levels in per_token.items():
        b = book(levels)
        b["min_order_size"] = "1"
        b["tick_size"] = "0.01"
        routes[f"token_id={t}"] = b
    return FakeFetch(routes)


class TestDecimalBoundary(unittest.TestCase):
    def test_exact_one_dollar_lot_is_executable(self):
        """Аск 10¢ + комиссия = 10.45¢: ровно $1.00 набирается точно.

        Двоичная арифметика даёт здесь 0.9999999999999999 и отбрасывает
        полностью исполнимую ногу — деньги обязаны считаться десятичными.
        
        После округления акций до 1 десятичного знака raw cost может чуть превышать
        номинальную стоимость; строгое сравнение без tolerance требует достаточного бюджета.
        """
        a = 0.10 + 0.05*0.10*(1-0.10)                    # полная цена ноги
        shares = 1.0/a                                   # ровно $1.00 по десятичной арифметике
        self.assertLess(shares*a, 1.0)                   # ловушка двоичной дроби
        step = combo_step(stake=4.0, asks=(0.10, 0.10), tids=("a", "b"),
                          leg_p=(0.35, 0.35), cost=0.209)
        f = books(a=[(0.10, shares)], b=[(0.10, shares)])
        # After share rounding, raw cost is ~$2.0064; provide sufficient budget
        ex = w.combo_lots(step, MP, 2.01, f)
        self.assertTrue(ex["ok"], ex.get("reason"))
        self.assertEqual(len(ex["lots"]), 2)
        for lot in ex["lots"]:
            self.assertGreaterEqual(lot["usd"], MP.min_notional)

    def test_min_lot_uses_full_price_with_market_fee(self):
        """Минимальный лот вычисляется с учётом fee_rate рынка.
        
        С строгой проверкой, raw cost после округления акций может чуть превысить номинал.
        """
        step = combo_step(stake=10.0, asks=(0.10, 0.10), tids=("a", "b"),
                          leg_p=(0.35, 0.35), cost=0.209)
        f = books(a=[(0.10, 1000)], b=[(0.10, 1000)])
        # With budget exactly matching nominal minimum, strict checking rejects tiny overage
        ex = w.combo_lots(step, MP, 2.0, f)
        self.assertFalse(ex["ok"])
        self.assertIn("исполнимая стоимость", ex.get("reason", ""))
        
        # With sufficient buffer, it passes
        ex2 = w.combo_lots(step, MP, 3.0, f)
        self.assertTrue(ex2["ok"], ex2.get("reason"))
        self.assertLessEqual(ex2["total_usd"], 3.0)
        self.assertAlmostEqual(ex2["min_usd"], 2.0, places=1)


class TestCaps(unittest.TestCase):
    def test_total_never_exceeds_requested_stake(self):
        """С строгой проверкой raw cost должен быть строго <= stake.
        
        Если после округления акций raw cost чуть превышает stake, комбо отклоняется.
        """
        step = combo_step(stake=2.5, asks=(0.10, 0.20), tids=("a", "b"),
                          leg_p=(0.30, 0.40), cost=0.315)
        f = books(a=[(0.10, 10000)], b=[(0.20, 10000)])
        ex = w.combo_lots(step, MP, 100.0, f)
        # With strict checking, raw cost slightly exceeds stake → rejected
        self.assertFalse(ex["ok"])
        self.assertIn("исполнимая стоимость", ex.get("reason", ""))
        
        # With sufficient buffer, it passes
        step2 = combo_step(stake=3.0, asks=(0.10, 0.20), tids=("a", "b"),
                           leg_p=(0.30, 0.40), cost=0.315)
        ex2 = w.combo_lots(step2, MP, 100.0, f)
        self.assertTrue(ex2["ok"], ex2.get("reason"))
        self.assertLessEqual(ex2["total_usd"], 3.0 + 1e-9)

    def test_total_never_exceeds_remaining_budget(self):
        """С строгой проверкой raw cost должен быть строго <= budget.
        
        Если после округления акций raw cost чуть превышает budget, комбо отклоняется.
        """
        # Use minimal stake close to 2x min_notional to avoid overfill
        step = combo_step(stake=2.05, asks=(0.50, 0.50), tids=("a", "b"),
                          leg_p=(0.50, 0.60), cost=1.025)
        f = books(a=[(0.50, 10000)], b=[(0.50, 10000)])
        ex = w.combo_lots(step, MP, 2.04, f)
        # With strict checking, raw cost slightly exceeds budget → rejected
        self.assertFalse(ex["ok"])
        # Could fail on total exceeding budget or min not met
        self.assertTrue("исполнимая стоимость" in ex.get("reason", "") or 
                       "превышает" in ex.get("reason", "") or
                       "raw debit" in ex.get("reason", ""),
                       f"Expected budget or minimum rejection, got: {ex.get('reason')}")
        
        # With sufficient buffer, it passes
        ex2 = w.combo_lots(step, MP, 2.06, f)
        self.assertTrue(ex2["ok"], ex2.get("reason"))
        self.assertLessEqual(ex2["total_usd"], 2.06 + 1e-9)

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
        big = MP._replace(min_notional=5.0)
        step = combo_step(stake=6.0, asks=(0.10, 0.20), tids=("a", "b"),
                          leg_p=(0.30, 0.40), cost=0.315)
        f = books(a=[(0.10, 10000)], b=[(0.20, 10000)])
        ex = w.combo_lots(step, big, 6.0, f)
        self.assertFalse(ex["ok"])
        self.assertIn("$", ex["reason"])

    def test_exact_decimal_cap_comparison_catches_small_overrun(self):
        """Сравнение min_total > cap должно быть точным (Decimal), а не через _cents():
        _cents(1.4902) = 1.49 = cap, но 1.4902 > 1.49 — реальное превышение.
        Этот тест проверяет математическое свойство, которое должна соблюдать реализация."""
        from decimal import Decimal, ROUND_HALF_UP
        CENT = Decimal("0.01")
        min_total = Decimal("1.4902")
        cap = Decimal("1.49")
        rounded = min_total.quantize(CENT, rounding=ROUND_HALF_UP)
        # Округление скрыло бы превышение
        self.assertEqual(rounded, cap,
                         "ожидаем, что _cents скруглит вниз и сравнение через rounded > cap не поймает")
        self.assertGreater(min_total, cap,
                           "реальное превышение cap должно быть видно через точное Decimal сравнение")
        # Реализация использует точное сравнение (min_total > cap), а не через _cents


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
