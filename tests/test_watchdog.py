"""Сторож (`src/watchdog.py`) — те же правила, что и у дневного сканера.

Проверяем три вещи: комиссия берётся из параметров КОНКРЕТНОГО рынка,
рынок без подтверждённых параметров не торгуется, и «связка» засчитывается
только после проверки книг и минимального ордера.
"""
import unittest

from tests.support import FakeFetch, book, market

import watchdog as wd


class FeeIsPerMarketTest(unittest.TestCase):
    def test_fee_uses_market_rate_not_a_constant(self):
        cheap = wd.MarketParams(fee_rate=0.02, tick=0.01, min_notional=1.0,
                                min_shares=0.0, source="market")
        rich = wd.MarketParams(fee_rate=0.10, tick=0.01, min_notional=1.0,
                               min_shares=0.0, source="market")
        self.assertAlmostEqual(wd.fee(0.5, cheap), 0.02*0.25)
        self.assertAlmostEqual(wd.fee(0.5, rich), 0.10*0.25)
        self.assertGreater(wd.allin(0.5, rich), wd.allin(0.5, cheap))

    def test_no_hard_coded_fee_constant_left(self):
        with open(wd.__file__, encoding="utf-8") as fh:
            src = fh.read()
        self.assertNotIn("0.05*a*(1-a)", src)
        self.assertNotIn("def fee(a)", src)


class ParamsFailClosedTest(unittest.TestCase):
    def test_event_without_params_is_not_tradable(self):
        m = market()
        m.pop("taker_base_fee")
        m.pop("conditionId")
        self.assertIsNone(wd.event_params([m], FakeFetch()))

    def test_bps_form_is_understood(self):
        p = wd.event_params([market(taker_base_fee=500)], FakeFetch())
        self.assertAlmostEqual(p.fee_rate, 0.05)

    def test_insane_values_are_rejected(self):
        self.assertIsNone(wd.parse_market_params(market(taker_base_fee=9000)))
        self.assertIsNone(wd.parse_market_params(market(minimum_tick_size=0.5)))
        self.assertIsNone(wd.parse_market_params(market(minimum_order_size=1000)))

    def test_clob_fallback_is_used_when_gamma_is_incomplete(self):
        m = market()
        m.pop("taker_base_fee")
        f = FakeFetch({"clob.polymarket.com/markets/":
                       dict(taker_base_fee=0.05, minimum_tick_size=0.01,
                            minimum_order_size=1.0)})
        p = wd.market_params(m, f)
        self.assertIsNotNone(p)
        self.assertAlmostEqual(p.fee_rate, 0.05)


class ExecutableArbTest(unittest.TestCase):
    MP = wd.MarketParams(fee_rate=0.05, tick=0.01, min_notional=1.0,
                         min_shares=0.0, source="event")

    def test_cheap_quotes_without_a_book_are_not_arbitrage(self):
        f = FakeFetch({"book?token_id=a": Exception("нет книги")})
        r = wd.check_arb_legs([("a", 0.40), ("b", 0.50)], self.MP, f)
        self.assertFalse(r["ok"])
        self.assertEqual(r["why"], "книга недоступна")

    def test_empty_book_is_not_arbitrage(self):
        f = FakeFetch({"book?token_id=a": book([])})
        r = wd.check_arb_legs([("a", 0.40), ("b", 0.50)], self.MP, f)
        self.assertFalse(r["ok"])
        self.assertEqual(r["why"], "пустая книга")

    def test_volume_below_minimum_order_is_not_arbitrage(self):
        f = FakeFetch({"book?token_id=a": book([(0.40, 1)]),
                       "book?token_id=b": book([(0.50, 1)])})
        r = wd.check_arb_legs([("a", 0.40), ("b", 0.50)], self.MP, f)
        self.assertFalse(r["ok"])
        self.assertIn("минимальный ордер", r["why"])

    def test_fees_can_kill_a_paper_arbitrage(self):
        # 0.49 + 0.49 = 0.98 «на бумаге», но с комиссией 5% комплект дороже $1
        f = FakeFetch({"book?token_id=a": book([(0.49, 500)]),
                       "book?token_id=b": book([(0.49, 500)])})
        rich = wd.MarketParams(fee_rate=0.10, tick=0.01, min_notional=1.0,
                               min_shares=0.0, source="event")
        r = wd.check_arb_legs([("a", 0.49), ("b", 0.49)], rich, f)
        self.assertFalse(r["ok"])
        self.assertIn("прибыли нет", r["why"])

    def test_executable_arbitrage_is_accepted(self):
        f = FakeFetch({"book?token_id=a": book([(0.40, 50)]),
                       "book?token_id=b": book([(0.50, 40)])})
        r = wd.check_arb_legs([("a", 0.40), ("b", 0.50)], self.MP, f)
        self.assertTrue(r["ok"])
        self.assertEqual(r["exec_sets"], 40)
        self.assertGreater(r["exec_profit"], 0)

    def test_arb_rejects_missing_book_metadata(self):
        # Книга без min_order_size или tick_size → NO BET
        bad_book = {"asks": [{"price": "0.40", "size": "50"}]}  # отсутствуют метаданные
        f = FakeFetch({"book?token_id=a": bad_book,
                       "book?token_id=b": book([(0.50, 40)])})
        r = wd.check_arb_legs([("a", 0.40), ("b", 0.50)], self.MP, f)
        self.assertFalse(r["ok"])
        self.assertIn("метаданных", r["why"])

    def test_arb_rejects_invalid_book_metadata(self):
        # Книга с некорректными метаданными → NO BET
        invalid_book = {"asks": [{"price": "0.40", "size": "50"}],
                       "min_order_size": "999", "tick_size": "0.01"}
        f = FakeFetch({"book?token_id=a": invalid_book,
                       "book?token_id=b": book([(0.50, 40)])})
        r = wd.check_arb_legs([("a", 0.40), ("b", 0.50)], self.MP, f)
        self.assertFalse(r["ok"])
        self.assertIn("некорректный", r["why"])

    def test_arb_enforces_book_minimum_shares_per_leg(self):
        """Арбитраж: объём в акциях обязан покрывать минимум книги (min_order_size) по каждой ноге.
        
        Пример: книга требует минимум 10 акций, но на двух ногах только 3 акции глубины.
        USDC-нотионал покрыт (3 × $0.35 × 1.00875 ≈ $1.06 ≥ минимум $1), 
        комплект прибыльный (cost < $1),
        но book.min_order_size требует ≥10 акций на каждой ноге → NO BET."""
        # Используем цены 0.35 на каждой ноге: 0.35 + 0.35 = 0.70 (прибыльно)
        # allin(0.35) ≈ 0.35 * 1.00875 ≈ 0.353 → 3 * 0.353 ≈ $1.06 (нотионал покрыт)
        # Но min_order_size=10, а глубина только 3 акции
        f = FakeFetch({"book?token_id=a": book([(0.35, 3)], min_order_size=10),
                       "book?token_id=b": book([(0.35, 3)], min_order_size=10)})
        r = wd.check_arb_legs([("a", 0.35), ("b", 0.35)], self.MP, f)
        self.assertFalse(r["ok"], "арбитраж с объёмом 3 акции должен быть отклонён (min=10)")
        self.assertIn("акций", r["why"].lower())


if __name__ == "__main__":
    unittest.main()
