"""Блокер 5: торговые параметры КОНКРЕТНОГО рынка, а не общая константа."""
import unittest

from tests.support import FakeFetch, market  # noqa: F401  (побочно кладёт src/ в sys.path)
import wx_daily as w


class TestMarketParams(unittest.TestCase):
    def test_fee_requires_market_params(self):
        """Комиссия больше не берётся из зашитой константы: она — свойство рынка."""
        mp = w.MarketParams(fee_rate=0.05, tick=0.01, min_order=1.0, min_shares=0.0, source="test")
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
        """Нет полей в Gamma — добираем из CLOB по conditionId."""
        thin = market(taker_base_fee=None, minimum_tick_size=None, minimum_order_size=None,
                      conditionId="0xabc")
        f = FakeFetch({"clob.polymarket.com/markets/0xabc":
                       dict(minimum_tick_size=0.01, minimum_order_size=1.0, taker_base_fee=500)})
        mp = w.market_params(thin, f)
        self.assertIsNotNone(mp)
        self.assertAlmostEqual(mp.fee_rate, 0.05, places=12)
        self.assertEqual(mp.min_order, 1.0)

    def test_clob_unreachable_means_no_bet(self):
        thin = market(taker_base_fee=None, minimum_tick_size=None, minimum_order_size=None)
        f = FakeFetch({"clob.polymarket.com": RuntimeError("нет сети")})
        self.assertIsNone(w.market_params(thin, f))

    def test_event_params_strict_and_worst_case(self):
        good = market(taker_base_fee=500, minimum_order_size=1.0, minimum_tick_size=0.01)
        pricier = market(taker_base_fee=700, minimum_order_size=2.0, minimum_tick_size=0.02)
        mp = w.event_params([good, pricier], FakeFetch())
        self.assertAlmostEqual(mp.fee_rate, 0.07, places=12)
        self.assertEqual(mp.min_order, 2.0)
        self.assertEqual(mp.tick, 0.02)
        broken = market(taker_base_fee=None, minimum_tick_size=None, minimum_order_size=None,
                        conditionId=None)
        self.assertIsNone(w.event_params([good, broken], FakeFetch()))
        self.assertIsNone(w.event_params([], FakeFetch()))


if __name__ == "__main__":
    unittest.main()
