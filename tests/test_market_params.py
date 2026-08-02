"""Блокер 5: торговые параметры КОНКРЕТНОГО рынка, а не общая константа."""
import unittest

from tests.support import FakeFetch, market  # noqa: F401  (побочно кладёт src/ в sys.path)
import wx_daily as w


class TestMarketParams(unittest.TestCase):
    def test_fee_requires_market_params(self):
        """Комиссия больше не берётся из зашитой константы: она — свойство рынка."""
        mp = w.MarketParams(fee_rate=0.05, tick=0.01, min_notional=1.0, min_shares=0.0, source="test")
        self.assertAlmostEqual(w.fee(0.10, mp), 0.05*0.10*0.90, places=12)
        self.assertAlmostEqual(w.allin(0.10, mp), 0.10 + 0.05*0.10*0.90, places=12)
        with self.assertRaises(TypeError):
            w.allin(0.10)

    def test_weather_and_crypto_do_not_share_one_constant(self):
        """Разные рынки — разные комиссии, и полная цена обязана это отражать."""
        wx = w.parse_market_params(market(taker_base_fee=500))
        crypto = w.parse_market_params(market(taker_base_fee=200))
        self.assertIsNotNone(wx)
        self.assertIsNotNone(crypto)
        self.assertNotEqual(wx.fee_rate, crypto.fee_rate)
        self.assertGreater(w.allin(0.5, wx), w.allin(0.5, crypto))

    def test_bps_and_fraction_are_both_understood(self):
        self.assertAlmostEqual(w.parse_market_params(market(taker_base_fee=500)).fee_rate, 0.05, places=12)
        self.assertAlmostEqual(w.parse_market_params(market(taker_base_fee=0.05)).fee_rate, 0.05, places=12)

    def test_missing_or_insane_params_fail_closed(self):
        for bad in (dict(taker_base_fee=None), dict(minimum_tick_size=None),
                    dict(minimum_order_size=None), dict(taker_base_fee=9999999),
                    dict(minimum_tick_size=0.5), dict(minimum_order_size=1000.0)):
            self.assertIsNone(w.parse_market_params(market(**bad)), bad)

    def test_clob_fallback_by_condition_id(self):
        """Нет полей в Gamma — добираем из CLOB по conditionId.
        CLOB minimum_order_size — это акции (min_shares), не нотионал."""
        thin = market(taker_base_fee=None, minimum_tick_size=None, conditionId="0xabc")
        # minimum_order_size в thin — Gamma USDC нотионал (1.0)
        f = FakeFetch({"clob.polymarket.com/markets/0xabc":
                       dict(minimum_tick_size=0.01, minimum_order_size=1.0, taker_base_fee=500)})
        mp = w.market_params(thin, f)
        self.assertIsNotNone(mp)
        self.assertAlmostEqual(mp.fee_rate, 0.05, places=12)
        self.assertEqual(mp.min_notional, 1.0)

    def test_clob_unreachable_means_no_bet(self):
        thin = market(taker_base_fee=None, minimum_tick_size=None, minimum_order_size=None)
        f = FakeFetch({"clob.polymarket.com": RuntimeError("нет сети")})
        self.assertIsNone(w.market_params(thin, f))

    def test_event_params_strict_and_worst_case(self):
        good = market(taker_base_fee=500, minimum_order_size=1.0, minimum_tick_size=0.01)
        pricier = market(taker_base_fee=700, minimum_order_size=2.0, minimum_tick_size=0.02)
        mp = w.event_params([good, pricier], FakeFetch())
        self.assertAlmostEqual(mp.fee_rate, 0.07, places=12)
        self.assertEqual(mp.min_notional, 2.0)
        self.assertEqual(mp.tick, 0.02)
        broken = market(taker_base_fee=None, minimum_tick_size=None, minimum_order_size=None,
                        conditionId=None)
        self.assertIsNone(w.event_params([good, broken], FakeFetch()))
        self.assertIsNone(w.event_params([], FakeFetch()))

    # ── Item 4: canonical fee schedule ────────────────────────────────────────

    def test_canonical_fee_schedule_is_parsed(self):
        """feesEnabled + feeSchedule.rate — каноническое расписание; без taker_base_fee."""
        m = market(taker_base_fee=None)
        m.update(feesEnabled=True, feeSchedule={"rate": 0.05})
        mp = w.parse_market_params(m)
        self.assertIsNotNone(mp, "каноническое расписание должно разбираться")
        self.assertAlmostEqual(mp.fee_rate, 0.05, places=12)

    def test_fees_disabled_gives_zero_rate(self):
        """feesEnabled=False явно разрешает нулевую ставку."""
        m = market(taker_base_fee=None)
        m.update(feesEnabled=False)
        mp = w.parse_market_params(m)
        self.assertIsNotNone(mp)
        self.assertEqual(mp.fee_rate, 0.0)

    def test_fees_enabled_but_no_schedule_is_no_bet(self):
        """feesEnabled=True без расписания — fail-closed."""
        m = market(taker_base_fee=None)
        m.update(feesEnabled=True)  # нет feeSchedule
        self.assertIsNone(w.parse_market_params(m))

    def test_canonical_and_legacy_conflict_is_no_bet(self):
        """feesEnabled+feeSchedule конфликтует с taker_base_fee — fail-closed."""
        m = market(taker_base_fee=500)       # 500 бп = 0.05
        m.update(feesEnabled=True, feeSchedule={"rate": 0.07})   # 0.07 ≠ 0.05
        self.assertIsNone(w.parse_market_params(m))

    def test_canonical_and_legacy_agree_is_ok(self):
        """Оба поля есть и совпадают — рынок торгуется."""
        m = market(taker_base_fee=500)       # 0.05
        m.update(feesEnabled=True, feeSchedule={"rate": 0.05})
        mp = w.parse_market_params(m)
        self.assertIsNotNone(mp)
        self.assertAlmostEqual(mp.fee_rate, 0.05, places=12)

    # ── Item 5: раздельные Gamma-нотионал и CLOB-акции ───────────────────────

    def test_gamma_notional_and_clob_shares_are_separate_fields(self):
        """orderMinSize (Gamma USDC) и CLOB minimum_order_size (акции) хранятся
        раздельно и не смешиваются друг с другом."""
        gamma_market = market(taker_base_fee=500, minimum_tick_size=0.01,
                              minimum_order_size=5.0, conditionId="0xgamma5")
        clob_resp = dict(minimum_tick_size=0.01, minimum_order_size=5, taker_base_fee=500)
        f = FakeFetch({"clob.polymarket.com/markets/0xgamma5": clob_resp})
        mp = w.market_params(gamma_market, f)
        self.assertIsNotNone(mp)
        self.assertEqual(mp.min_notional, 5.0)   # Gamma USDC нотионал
        self.assertEqual(mp.min_shares, 5.0)     # CLOB акции

    def test_notional_and_shares_enforced_separately_at_low_price(self):
        """При цене 0.10 нотионал $5 требует ~47.8 акций — CLOB мин. 5 акций уже выполнен."""
        from decimal import Decimal
        mp = w.MarketParams(fee_rate=0.05, tick=0.01, min_notional=5.0,
                            min_shares=5.0, source="test")
        # Книга с большим объёмом при цене 0.10
        levels = [(0.10, 10000.0)]
        result = w._walk_book(levels, mp, mp.min_shares, Decimal("10.00"))
        self.assertIsNotNone(result)
        sh, usd, _ = result
        self.assertGreaterEqual(float(usd), 5.0)   # нотионал выполнен
        self.assertGreaterEqual(float(sh), 5.0)    # акции выполнены

    def test_notional_binding_above_share_min_at_low_price(self):
        """При малом капе только нотионал $5 не влезает в $4 — NO BET."""
        from decimal import Decimal
        mp = w.MarketParams(fee_rate=0.05, tick=0.01, min_notional=5.0,
                            min_shares=5.0, source="test")
        levels = [(0.10, 10000.0)]
        result = w._walk_book(levels, mp, mp.min_shares, Decimal("4.00"))
        self.assertIsNone(result)  # cap $4 < min_notional $5

    def test_shares_binding_at_high_price(self):
        """При цене 0.90 нотионал $5 ≈ 5.3 акций; CLOB мин. 5 акций.
        Оба ограничения выполняются — исполнение возможно."""
        from decimal import Decimal
        mp = w.MarketParams(fee_rate=0.05, tick=0.01, min_notional=5.0,
                            min_shares=5.0, source="test")
        levels = [(0.90, 10000.0)]
        result = w._walk_book(levels, mp, mp.min_shares, Decimal("10.00"))
        self.assertIsNotNone(result)
        sh, usd, _ = result
        self.assertGreaterEqual(float(usd), 5.0)
        self.assertGreaterEqual(float(sh), 5.0)

    def test_combo_lots_under_5usd_cap_with_5usd_min_notional(self):
        """Два минимальных ордера по $5 не влезают в бюджет $4 — NO BET."""
        from tests.support import combo_step, book, FakeFetch
        mp5 = w.MarketParams(fee_rate=0.05, tick=0.01, min_notional=5.0,
                             min_shares=5.0, source="test")
        step = combo_step(stake=4.0, asks=(0.10, 0.10), tids=("a", "b"),
                          leg_p=(0.45, 0.35), cost=0.209)
        f = FakeFetch({"token_id=a": book([(0.10, 10000)]),
                       "token_id=b": book([(0.10, 10000)])})
        ex = w.combo_lots(step, mp5, budget_left=4.0, fetch=f)
        self.assertFalse(ex["ok"])
        self.assertIn("$", ex["reason"])


if __name__ == "__main__":
    unittest.main()
