"""Блокер 3: вердикт BET только по исполнимой экономике, без «первых шести»."""
import unittest

from tests.support import FakeFetch, book, combo_step  # noqa: F401
import wx_daily as w

MP = w.MarketParams(fee_rate=0.05, tick=0.01, min_notional=1.0, min_shares=0.0, source="test")


def deep_books(*tids):
    """Глубокие стаканы для указанных токенов с обязательными метаданными."""
    routes = {}
    for t in tids:
        b = book([(0.10, 100000), (0.11, 100000)])
        b["min_order_size"] = "1"
        b["tick_size"] = "0.01"
        routes[f"token_id={t}"] = b
    return FakeFetch(routes)


def wx_combo(city="Чэнду", date="2026-08-03", stake=4.0, tids=("a", "b"), **kw):
    step = combo_step(stake=stake, asks=(0.10, 0.10), tids=list(tids),
                      leg_p=(0.45, 0.35), cost=0.209)
    step.update(city=city, date=date, lead=1, vol=50000, tier="A", mp=MP,
                link="https://polymarket.com/event/x")
    step.update(kw)
    return step


class TestApproveCombo(unittest.TestCase):
    def test_missing_exec_is_never_approved(self):
        self.assertFalse(w.approve_combo(None, 5.0)[0])
        self.assertFalse(w.approve_combo({}, 5.0)[0])
        self.assertFalse(w.approve_combo(dict(ok=True, lots=[], ev_final=1.0, total_usd=2.0, stake=4.0), 5.0)[0])

    def test_requires_two_executable_legs(self):
        ex = dict(ok=True, lots=[dict(bucket="30°C", usd=2.0, p=0.5, payout=20)],
                  ev_final=1.5, total_usd=2.0, stake=4.0)
        ok, why = w.approve_combo(ex, 5.0)
        self.assertFalse(ok)
        self.assertIn("ног", why)

    def test_requires_fee_inclusive_ev_threshold(self):
        lots = [dict(bucket="a", usd=1.0, p=0.3, payout=9.5), dict(bucket="b", usd=1.0, p=0.3, payout=9.5)]
        ok, _ = w.approve_combo(dict(ok=True, lots=lots, ev_final=0.09, total_usd=2.0, stake=4.0), 5.0)
        self.assertFalse(ok)
        ok, _ = w.approve_combo(dict(ok=True, lots=lots, ev_final=0.10, total_usd=2.0, stake=4.0), 5.0)
        self.assertTrue(ok)

    def test_must_fit_remaining_budget_and_stake(self):
        lots = [dict(bucket="a", usd=2.0, p=0.3, payout=19), dict(bucket="b", usd=2.0, p=0.3, payout=19)]
        ex = dict(ok=True, lots=lots, ev_final=0.5, total_usd=4.0, stake=4.0)
        self.assertFalse(w.approve_combo(ex, 3.0)[0])
        self.assertTrue(w.approve_combo(ex, 4.0)[0])
        self.assertFalse(w.approve_combo(dict(ex, stake=3.0), 10.0)[0])


class TestPlanWeather(unittest.TestCase):
    def test_bet_only_after_lots_are_calculated(self):
        c = wx_combo()
        alloc = w.BudgetAllocator()
        approved = w.plan_weather([c], [], alloc, fetch=deep_books("a", "b"))
        self.assertIs(approved["max"], c)
        self.assertIn("exec", c)
        self.assertTrue(c["exec"]["ok"])
        self.assertTrue(c["exec_ok"])
        self.assertLessEqual(c["exec"]["total_usd"], 5.0)

    def test_max_min_and_singles_share_one_budget(self):
        """Максимум, минимум и одиночная ставка одной даты не могут потратить $5 трижды."""
        cmax = wx_combo(city="Чэнду", stake=4.0, tids=("a", "b"))
        cmin = wx_combo(city="Токио (мин)", stake=4.0, tids=("c", "d"))
        single = dict(city="Шанхай", date="2026-08-03", stake=3.0, conf=5, ev=0.5)
        alloc = w.BudgetAllocator()
        w.plan_weather([cmax, cmin], [single], alloc, fetch=deep_books("a", "b", "c", "d"))
        spent = sum(r["usd"] for r in alloc.snapshot()["allocations"])
        self.assertLessEqual(spent, 5.0 + 1e-9)
        self.assertEqual(alloc.remaining("2026-08-03"), round(5.0 - spent, 2))

    def test_executed_positions_shrink_the_pot(self):
        c = wx_combo(stake=4.0)
        alloc = w.BudgetAllocator(spent_total=4.5, spent_by_date={"2026-08-03": 4.5})
        approved = w.plan_weather([c], [], alloc, fetch=deep_books("a", "b"))
        self.assertIsNone(approved["max"])
        self.assertFalse(c["exec_ok"])
        self.assertTrue(c["exec_why"])

    def test_all_candidates_are_judged_not_only_first_six(self):
        """Седьмой кандидат обязан получить расчёт или ЯВНЫЙ отказ."""
        combos = [wx_combo(city=f"Город{i}", date="2026-08-03", tids=(f"a{i}", f"b{i}"))
                  for i in range(9)]
        alloc = w.BudgetAllocator()
        tids = [t for c in combos for t in c["tids"]]
        w.plan_weather(combos, [], alloc, fetch=deep_books(*tids))
        for c in combos:
            self.assertIn("exec_ok", c)
            if not c["exec_ok"]:
                self.assertTrue(c["exec_why"], c["city"])

    def test_rejected_candidate_never_gets_budget(self):
        c = wx_combo(stake=4.0, tids=("a", "b"))
        alloc = w.BudgetAllocator()
        # книга есть только у одной ноги: комбо не собирается — денег не выдаём
        f = FakeFetch({"token_id=a": book([(0.10, 100000)]), "token_id=b": book([])})
        approved = w.plan_weather([c], [], alloc, fetch=f)
        self.assertIsNone(approved["max"])
        self.assertEqual(alloc.snapshot()["allocations"], [])

    def test_low_ev_candidate_is_rejected_with_reason(self):
        c = wx_combo(stake=4.0, tids=("a", "b"))
        c["leg_p"] = [0.05, 0.05]
        alloc = w.BudgetAllocator()
        approved = w.plan_weather([c], [], alloc, fetch=deep_books("a", "b"))
        self.assertIsNone(approved["max"])
        self.assertIn("EV", c["exec_why"])


    def test_single_pick_with_stake_below_market_min_is_rejected(self):
        """Одиночная ставка ниже минимального ордера рынка — NO BET, бюджет не тратим."""
        mp_big = w.MarketParams(fee_rate=0.05, tick=0.01, min_notional=5.0,
                                min_shares=0.0, source="test")
        pick = dict(city="Чэнду", date="2026-08-03", stake=2.0, conf=4, ev=0.20, mp=mp_big)
        alloc = w.BudgetAllocator()
        w.plan_weather([], [pick], alloc)
        # ставка 2.0 < min_notional 5.0 → stake=0, бюджет не тронут
        self.assertEqual(pick["stake"], 0.0)
        self.assertIn("budget_block", pick)
        self.assertIn("5", pick["budget_block"])
        self.assertEqual(alloc.snapshot()["allocations"], [])

    def test_single_pick_at_exact_market_min_is_granted(self):
        """Ставка чуть выше минимума рынка — выдаётся после округления акций."""
        # Use min_notional=4.5 to avoid boundary rounding issues with WEATHER_DAY_CAP=5.0
        mp5 = w.MarketParams(fee_rate=0.05, tick=0.01, min_notional=4.5,
                             min_shares=0.0, source="test")
        pick = dict(city="Чэнду", date="2026-08-03", stake=4.6, conf=4, ev=0.20, mp=mp5,
                    token_id="tok-chengdu", ask=0.30)
        alloc = w.BudgetAllocator()
        
        # Provide deep book with metadata
        fetch = FakeFetch({
            "book?token_id=tok-chengdu": dict(
                asks=[{"price": "0.30", "size": "1000"}],
                min_order_size="1",
                tick_size="0.01"
            )
        })
        
        w.plan_weather([], [pick], alloc, fetch=fetch)
        self.assertGreater(pick["stake"], 0.0)

    def test_single_pick_uses_conservative_probability_for_executed_ev(self):
        """A strong base estimate cannot override weak worst-case executed EV."""
        pick = dict(city="Чэнду", date="2026-08-03", side="YES", stake=2.0,
                    conf=5, ev=0.30, mp=MP, token_id="tok-conservative", ask=0.50,
                    p=0.70, pLo=0.52, pHi=0.75, p_cons=0.52)
        alloc = w.BudgetAllocator()
        fetch = FakeFetch({
            "book?token_id=tok-conservative": dict(
                asks=[{"price": "0.50", "size": "1000"}],
                min_order_size="1", tick_size="0.01")
        })

        w.plan_weather([], [pick], alloc, fetch=fetch)

        self.assertEqual(pick["stake"], 0.0)
        self.assertIn("EV", pick["budget_block"])
        self.assertEqual(alloc.snapshot()["allocations"], [])

    def test_single_pick_without_mp_must_fail_closed(self):
        """Одиночная ставка без mp должна быть отклонена (fail-closed)."""
        pick = dict(city="Чэнду", date="2026-08-03", stake=1.5, conf=4, ev=0.20)
        # нет поля mp — должен быть отказ
        alloc = w.BudgetAllocator()
        w.plan_weather([], [pick], alloc)
        self.assertEqual(pick["stake"], 0.0, "missing mp must result in stake=0")
        self.assertIn("budget_block", pick, "missing mp must have budget_block reason")
        self.assertIn("mp отсутствует", pick["budget_block"])


if __name__ == "__main__":
    unittest.main()
