"""RED tests for the 5 production-contract gaps identified in review.
These tests exercise actual production code paths and must fail on head 9978499."""
import unittest
from decimal import Decimal

from tests.support import FakeFetch, market
import wx_daily as w


class TestCanonicalFeeScheduleComplete(unittest.TestCase):
    """Item 1: Canonical fee schedule must validate exponent and takerOnly."""
    
    def test_unsupported_exponent_is_no_bet(self):
        """feesEnabled=True with unsupported exponent value must fail closed."""
        m = market(taker_base_fee=None)
        m.update(feesEnabled=True, feeSchedule={"rate": 0.05, "exponent": 3})
        # Currently only reads "rate", ignores exponent → returns MarketParams
        # MUST fail closed on unsupported exponent
        mp = w.parse_market_params(m)
        self.assertIsNone(mp, "unsupported fee exponent must produce NO BET")
    
    def test_taker_only_true_is_supported(self):
        """feesEnabled=True with takerOnly=True should be supported."""
        m = market(taker_base_fee=None)
        m.update(feesEnabled=True, feeSchedule={"rate": 0.05, "takerOnly": True})
        mp = w.parse_market_params(m)
        self.assertIsNotNone(mp, "takerOnly=True is the standard case")
        self.assertAlmostEqual(mp.fee_rate, 0.05, places=12)
    
    def test_taker_only_false_is_no_bet(self):
        """feesEnabled=True with takerOnly=False (maker/taker split) is unsupported."""
        m = market(taker_base_fee=None)
        m.update(feesEnabled=True, feeSchedule={"rate": 0.05, "takerOnly": False})
        mp = w.parse_market_params(m)
        self.assertIsNone(mp, "takerOnly=False requires maker/taker split logic")


class TestActualBookMetadata(unittest.TestCase):
    """Item 2: Book metadata (min_order_size, tick_size) must come from actual book."""
    
    def test_combo_lots_validates_book_min_order_size(self):
        """combo_lots must read min_order_size from each actual book response."""
        mp = w.MarketParams(fee_rate=0.05, tick=0.01, min_notional=1.0,
                            min_shares=0.0, source="test")
        step = dict(buckets=["30°C", "31°C"], asks=[0.30, 0.30],
                    tids=["tok30", "tok31"], leg_p=[0.45, 0.45],
                    cost=0.60, stake=3.0)
        
        def fake_fetch(url):
            if "book?token_id=tok30" in url:
                # Book declares min_order_size=10 shares (CLOB constraint)
                return dict(asks=[{"price": "0.30", "size": "100"}],
                            min_order_size="10", tick_size="0.01")
            if "book?token_id=tok31" in url:
                return dict(asks=[{"price": "0.30", "size": "100"}],
                            min_order_size="10", tick_size="0.01")
            raise RuntimeError(f"unexpected: {url}")
        
        # Currently discards book metadata → uses only mp.min_shares=0.0
        # MUST read and enforce min_order_size=10 from book
        ex = w.combo_lots(step, mp, 10.0, fetch=fake_fetch)
        # With book min_order_size=10 shares @ 0.30 each = ~3.15 USD per leg
        # Two legs = ~6.30 USD minimum; budget_left=10.0 should work
        # But current code ignores book min_order_size, so it passes with smaller lots
        self.assertTrue(ex.get("ok"), "should succeed with sufficient budget")
        # Each leg must have at least 10 shares (the book minimum)
        for lot in ex["lots"]:
            self.assertGreaterEqual(lot["shares"], 10.0,
                                  f"leg {lot['bucket']} must respect book min_order_size=10")
    
    def test_combo_lots_validates_book_tick_size(self):
        """combo_lots must validate tick_size from each actual book."""
        mp = w.MarketParams(fee_rate=0.05, tick=0.01, min_notional=1.0,
                            min_shares=0.0, source="test")
        step = dict(buckets=["30°C"], asks=[0.303],  # Price not on 0.01 tick
                    tids=["tok30"], leg_p=[0.45], cost=0.303, stake=2.0)
        
        def fake_fetch(url):
            if "book?token_id=tok30" in url:
                # Book declares tick_size=0.01, but price 0.303 violates it
                return dict(asks=[{"price": "0.303", "size": "100"}],
                            min_order_size="1", tick_size="0.01")
            raise RuntimeError(f"unexpected: {url}")
        
        ex = w.combo_lots(step, mp, 10.0, fetch=fake_fetch)
        # Currently doesn't validate book tick_size
        # MUST fail closed when book price violates declared tick
        self.assertFalse(ex.get("ok"),
                        "must fail when book price violates declared tick_size")
    
    def test_missing_book_metadata_is_no_bet(self):
        """Missing min_order_size or tick_size in book response must fail closed."""
        mp = w.MarketParams(fee_rate=0.05, tick=0.01, min_notional=1.0,
                            min_shares=0.0, source="test")
        step = dict(buckets=["30°C"], asks=[0.30], tids=["tok30"],
                    leg_p=[0.45], cost=0.30, stake=2.0)
        
        def fake_fetch(url):
            if "book?token_id=tok30" in url:
                # Book response missing required metadata
                return dict(asks=[{"price": "0.30", "size": "100"}])
            raise RuntimeError(f"unexpected: {url}")
        
        ex = w.combo_lots(step, mp, 10.0, fetch=fake_fetch)
        # Currently doesn't check for book metadata presence
        # MUST fail closed when metadata is missing
        self.assertFalse(ex.get("ok"),
                        "must fail when book metadata is missing")


class TestSinglePickExecutableEconomics(unittest.TestCase):
    """Item 3: Single picks must use executable book validation."""
    
    def test_single_pick_validates_actual_book(self):
        """Single picks must fetch and validate actual token book, not just mp."""
        from datetime import datetime, timedelta
        
        # Create a single pick with token and book context
        allocator = w.BudgetAllocator(day_limit=15.0, weather_cap=5.0)
        wdate = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        
        mp = w.MarketParams(fee_rate=0.05, tick=0.01, min_notional=1.0,
                            min_shares=5.0, source="test")
        
        pick = dict(stake=2.0, conf=0.85, ev=0.25, date=wdate, city="test",
                    mp=mp, token_id="tok123", ask=0.30)
        
        book_checked = []
        def fake_fetch(url):
            if "book?token_id=tok123" in url:
                book_checked.append(True)
                # Book has insufficient depth
                return dict(asks=[{"price": "0.30", "size": "1"}],
                            min_order_size="5", tick_size="0.01")
            raise RuntimeError(f"unexpected: {url}")
        
        # Currently plan_weather only checks mp.min_notional, doesn't walk book
        result = w.plan_weather([], [pick], allocator, fetch=fake_fetch)
        
        # MUST have fetched and validated the actual book
        self.assertTrue(book_checked, "single pick must validate actual book")
        # MUST fail when book depth is insufficient for executable lot
        self.assertEqual(pick["stake"], 0.0,
                        "insufficient book depth must result in stake=0")
        self.assertIn("budget_block", pick,
                     "rejection must carry explicit reason")


class TestREDTestsExerciseProduction(unittest.TestCase):
    """Item 4: Tests must exercise actual production code paths."""
    
    def test_exact_decimal_cap_via_combo_lots(self):
        """The Decimal cap comparison must be tested through actual combo_lots call."""
        mp = w.MarketParams(fee_rate=0.05, tick=0.01, min_notional=1.0,
                            min_shares=0.0, source="test")
        
        # Construct a scenario where minimums sum to slightly more than cap
        # Each leg: 0.75 USD minimum × 2 legs = 1.50 USD
        # But after rounding: _cents(1.4902) = 1.49 = cap
        step = dict(buckets=["30°C", "31°C"], asks=[0.30, 0.30],
                    tids=["tok30", "tok31"], leg_p=[0.45, 0.45],
                    cost=0.60, stake=1.50)
        
        def fake_fetch(url):
            if "book?token_id=" in url:
                # Each leg costs 0.7451 USD (min) → rounds to 0.75
                # But Decimal sum is 1.4902, which rounds to 1.49
                return dict(asks=[{"price": "0.30", "size": "2.5"}])
            raise RuntimeError(f"unexpected: {url}")
        
        # cap = _cents(min(stake=1.50, budget=1.49)) = 1.49
        ex = w.combo_lots(step, mp, budget_left=1.49, fetch=fake_fetch)
        
        # The unrounded sum 1.4902 > cap 1.49 (exact Decimal comparison)
        # MUST detect the overrun and reject
        self.assertFalse(ex.get("ok"),
                        "exact Decimal comparison must catch min_total=1.4902 > cap=1.49")
        self.assertIn("превышают", ex.get("reason", ""),
                     "reason must mention cap exceeded")


class TestWebParityIncludesCanonical(unittest.TestCase):
    """Item 4: Web parity must cover canonical fee parsing."""
    
    def test_web_parity_fixture_includes_canonical_fees(self):
        """Parity fixtures must include canonical fee schedule to test web parser."""
        # This is a marker test: the actual parity runner and fixtures
        # must be updated to include feesEnabled/feeSchedule payloads
        # Currently web parseMarketParams only reads taker_base_fee aliases
        self.skipTest("Web parity does not yet include canonical fee fixtures")


if __name__ == "__main__":
    unittest.main()
