"""JS↔Python паритет: одно ядро расчёта на две реализации.

Веб-скринер (web/weather_screener.html) и ночной джоб (src/wx_daily.py) обязаны
давать ОДНИ И ТЕ ЖЕ числа и один и тот же вердикт: вероятность, усадку к рынку,
комиссии конкретного рынка, исполнимые лоты, EV и итоговое BET/NO BET. Здесь
кейсы из tests/parity/parity_cases.json считаются обеими реализациями и
сверяются. Сети нет: книги, параметры рынка и ансамбли лежат в кейсах.

JS-сторона запускается через node; если node недоступен, тест пропускается
явно (skip), а не молча зеленеет.
"""
import json
import math
import os
import shutil
import subprocess
import unittest

from tests.support import ROOT  # noqa: F401  (кладёт src/ в sys.path)
import wx_daily as wx

CASES = os.path.join(ROOT, "tests", "parity", "parity_cases.json")
RUNNER = os.path.join(ROOT, "tests", "parity", "parity_test.js")
HTML = os.path.join(ROOT, "web", "weather_screener.html")


def _r(x, n):
    return None if x is None else round(x, n)


def _mp(o):
    return wx.MarketParams(fee_rate=o["fee_rate"], tick=o["tick"], min_notional=o["min_order"],
                           min_shares=o.get("min_shares") or 0.0, source="case")


def _book_fetch(books):
    """Книги из кейса вместо сети: неизвестный токен = ошибки быть не должно."""
    def fetch(url):
        tid = url.split("token_id=")[-1]
        if tid not in books:
            # Простая ошибка без деталей, как при реальной сети
            raise RuntimeError("book not found")
        book = books[tid]
        # Если book уже в новом формате (с levels, min_order_size, tick_size), используем как есть
        if isinstance(book, dict) and "levels" in book:
            return dict(
                asks=[dict(price=p, size=s) for p, s in book["levels"]],
                min_order_size=str(book.get("min_order_size", 1)),
                tick_size=str(book.get("tick_size", 0.01))
            )
        # Иначе старый формат (просто массив уровней) — добавляем дефолтные метаданные
        return dict(
            asks=[dict(price=p, size=s) for p, s in book],
            min_order_size="1",
            tick_size="0.01"
        )
    return fetch


def py_results(cases):
    out = {}

    out["market_params"] = []
    for c in cases["market_params"]:
        p = wx.event_params(c["markets"])
        out["market_params"].append(dict(
            name=c["name"],
            params=None if p is None else dict(fee_rate=_r(p.fee_rate, 12), tick=_r(p.tick, 12),
                                               min_notional=_r(p.min_notional, 12), min_shares=_r(p.min_shares, 12))))

    out["prices"] = [dict(price=c["price"], fee=_r(wx.fee(c["price"], _mp(c["mp"])), 12),
                          allin=_r(wx.allin(c["price"], _mp(c["mp"])), 12))
                     for c in cases["prices"]]

    out["fam_prob"] = []
    for c in cases["fam_prob"]:
        p, by = wx.fam_prob(c["day"], (c["range"][0], c["range"][1]), c["unit"],
                            {str(c["lead"]): c["fams"]}, c["lead"], c["dbias"])
        out["fam_prob"].append(dict(name=c["name"], p=None if p is None else _r(p, 6),
                                    by_fam={k: _r(v, 3) for k, v in sorted(by.items())}))

    out["log_pool"] = [dict(name=c["name"],
                            rows=[dict(p=_r(x["p"], 9), pLo=_r(x["pLo"], 9), pHi=_r(x["pHi"], 9))
                                  for x in wx.log_pool(c["rows"])])
                       for c in cases["log_pool"]]

    out["coverage"] = [dict(name=c["name"], ok=wx.coverage_ok([tuple(x) for x in c["ranges"]]))
                       for c in cases["coverage"]]

    out["buckets"] = [dict(title=t, rng=(list(wx.parse_bucket(t)) if wx.parse_bucket(t) else None))
                      for t in cases["buckets"]]

    out["resolution"] = []
    for c in cases["resolution"]:
        seen, steps = {}, []
        for s in c["steps"]:
            ok, info = wx.check_resolution(s["eslug"], s["desc"], c["unit"], c["station"], seen)
            steps.append(dict(ok=ok, reason=info.get("reason"), sources=info.get("sources"),
                              units=info.get("units"), stations=info.get("stations"),
                              known_stations=info.get("known_stations")))
        out["resolution"].append(dict(name=c["name"], steps=steps))

    out["kelly"] = [dict(stake=_r(wx.kelly_stake(c["p_base"], c["p_cons"], c["cost"],
                                                 c["bankroll"], c["cap"]), 2))
                    for c in cases["kelly"]]

    def exec_of(step, mp, budget_left, books):
        if not step:
            return None
        ex = wx.combo_lots(step, mp, budget_left, _book_fetch(books))
        return dict(ok=ex["ok"], reason=ex.get("reason"), total_usd=_r(ex["total_usd"], 2),
                    min_usd=None if ex["min_usd"] is None else _r(ex["min_usd"], 2),
                    ev_final=None if ex["ev_final"] is None else _r(ex["ev_final"], 4),
                    p_covered=_r(ex["p_covered"], 3), stake=_r(ex["stake"], 2),
                    budget_left=_r(ex["budget_left"], 2),
                    lots=[dict(bucket=l["bucket"], limit=_r(l["limit"], 3), shares=_r(l["shares"], 1),
                               usd=_r(l["usd"], 2)) for l in ex["lots"]],
                    skipped=[dict(bucket=s["bucket"], why=s["why"]) for s in ex["skipped"]])

    out["combo_lots"] = [dict(name=c["name"],
                              exec=exec_of(c["step"], _mp(c["mp"]), c["budget_left"], c["books"]))
                         for c in cases["combo_lots"]]

    out["arb"] = []
    for c in cases["arb"]:
        res = wx.check_arb_legs([(t, None) for t in c["legs"]], _mp(c["mp"]), _book_fetch(c["books"]))
        out["arb"].append(dict(name=c["name"], ok=res["ok"], why=res.get("why"),
                               exec_sets=res["exec_sets"], exec_cost=_r(res.get("exec_cost"), 3),
                               exec_profit=_r(res.get("exec_profit"), 2)))

    out["chance_combos"] = []
    for c in cases["chance_combos"]:
        steps = wx.chance_combos(c["rows"], _mp(c["mp"]))
        out["chance_combos"].append(dict(name=c["name"], steps=[
            dict(buckets=s["buckets"], cost=_r(s["cost"], 3), p_win=_r(s["p_win"], 3),
                 p_rng=[_r(s["p_rng"][0], 2), _r(s["p_rng"][1], 2)]) for s in steps]))

    out["verdict"] = []
    for c in cases["verdict"]:
        mp = _mp(c["mp"])
        ex = wx.combo_lots(c["step"], mp, c["budget_left"], _book_fetch(c["books"])) if c["step"] else None
        ok, why = wx.approve_combo(ex, c["budget_left"])
        out["verdict"].append(dict(name=c["name"], verdict="BET" if ok else "NO BET", why=why,
                                   total_usd=_r(ex["total_usd"], 2) if (ex and ex["ok"]) else None,
                                   ev_final=_r(ex["ev_final"], 4) if (ex and ex["ok"]) else None))
    return out


class ParityTest(unittest.TestCase):
    """Числа и вердикты страницы обязаны совпадать с ночным джобом."""

    maxDiff = None
    # erf в JS — приближение Абрамовица-Стегуна, в Python — точный math.erf:
    # расхождение вероятностей допускаем только на этом уровне.
    P_TOL = 3e-6
    MONEY_TOL = 1e-6

    @classmethod
    def setUpClass(cls):
        with open(CASES, encoding="utf-8") as f:
            cls.cases = json.load(f)
        cls.node = shutil.which("node")
        cls.js = None
        if cls.node:
            res = subprocess.run([cls.node, RUNNER], capture_output=True, text=True, cwd=ROOT)
            if res.returncode != 0:
                raise AssertionError(f"node parity_test.js упал:\n{res.stderr}")
            cls.js = json.loads(res.stdout)

    def setUp(self):
        if self.js is None:
            self.skipTest("node не найден — паритет JS↔Python не проверить")
        self.py = py_results(self.cases)

    def _num_eq(self, a, b, tol, path):
        if a is None or b is None:
            self.assertEqual(a, b, f"{path}: JS={a} Python={b}")
        else:
            self.assertTrue(math.isclose(a, b, abs_tol=tol),
                            f"{path}: JS={a} Python={b} (допуск {tol})")

    def test_market_params(self):
        for j, p in zip(self.js["market_params"], self.py["market_params"]):
            self.assertEqual(j["name"], p["name"])
            self.assertEqual(j["params"], p["params"], f"параметры рынка: {p['name']}")

    def test_fees_and_allin(self):
        for j, p in zip(self.js["prices"], self.py["prices"]):
            self._num_eq(j["fee"], p["fee"], self.MONEY_TOL, f"комиссия {p['price']}")
            self._num_eq(j["allin"], p["allin"], self.MONEY_TOL, f"полная цена {p['price']}")

    def test_probability(self):
        for j, p in zip(self.js["fam_prob"], self.py["fam_prob"]):
            self.assertEqual(j["name"], p["name"])
            self._num_eq(j["p"], p["p"], self.P_TOL, f"вероятность: {p['name']}")
            self.assertEqual(sorted(j["by_fam"]), sorted(p["by_fam"]), f"семейства: {p['name']}")
            for k in p["by_fam"]:
                self._num_eq(j["by_fam"][k], p["by_fam"][k], 1e-3, f"{p['name']}/{k}")

    def test_shrinkage_to_market(self):
        for j, p in zip(self.js["log_pool"], self.py["log_pool"]):
            self.assertEqual(j["name"], p["name"])
            for i, (jr, pr) in enumerate(zip(j["rows"], p["rows"])):
                for key in ("p", "pLo", "pHi"):
                    self._num_eq(jr[key], pr[key], 1e-9, f"{p['name']}[{i}].{key}")

    def test_coverage_and_buckets(self):
        self.assertEqual([x["ok"] for x in self.js["coverage"]],
                         [x["ok"] for x in self.py["coverage"]])
        self.assertEqual([x["rng"] for x in self.js["buckets"]],
                         [x["rng"] for x in self.py["buckets"]])

    def test_resolution_contract(self):
        for j, p in zip(self.js["resolution"], self.py["resolution"]):
            self.assertEqual(j["name"], p["name"])
            self.assertEqual(j["steps"], p["steps"], f"контракт резолюции: {p['name']}")

    def test_kelly(self):
        for i, (j, p) in enumerate(zip(self.js["kelly"], self.py["kelly"])):
            self._num_eq(j["stake"], p["stake"], self.MONEY_TOL, f"Келли[{i}]")

    def test_executable_lots(self):
        for j, p in zip(self.js["combo_lots"], self.py["combo_lots"]):
            self.assertEqual(j["name"], p["name"])
            je, pe = j["exec"], p["exec"]
            self.assertEqual(je["ok"], pe["ok"], f"лоты: {p['name']}")
            self.assertEqual(je["reason"], pe["reason"], f"причина: {p['name']}")
            self._num_eq(je["total_usd"], pe["total_usd"], self.MONEY_TOL, f"сумма: {p['name']}")
            self._num_eq(je["min_usd"], pe["min_usd"], self.MONEY_TOL, f"минимум: {p['name']}")
            # EV tolerance slightly higher due to share rounding introducing extra rounding step
            self._num_eq(je["ev_final"], pe["ev_final"], 2e-4, f"EV: {p['name']}")
            self.assertEqual([l["bucket"] for l in je["lots"]], [l["bucket"] for l in pe["lots"]])
            for jl, pl in zip(je["lots"], pe["lots"]):
                self._num_eq(jl["usd"], pl["usd"], self.MONEY_TOL, f"{p['name']}/{pl['bucket']}/$")
                self._num_eq(jl["shares"], pl["shares"], 0.05, f"{p['name']}/{pl['bucket']}/акции")
                self._num_eq(jl["limit"], pl["limit"], 1e-9, f"{p['name']}/{pl['bucket']}/лимит")
            self.assertEqual(je["skipped"], pe["skipped"], f"пропуски: {p['name']}")

    def test_arbitrage_is_executable(self):
        for j, p in zip(self.js["arb"], self.py["arb"]):
            self.assertEqual(j["name"], p["name"])
            self.assertEqual((j["ok"], j["why"], j["exec_sets"]), (p["ok"], p["why"], p["exec_sets"]),
                             f"арбитраж: {p['name']}")
            self._num_eq(j["exec_cost"], p["exec_cost"], 1e-3, f"цена связки: {p['name']}")
            self._num_eq(j["exec_profit"], p["exec_profit"], 1e-2, f"профит связки: {p['name']}")

    def test_chance_combos(self):
        for j, p in zip(self.js["chance_combos"], self.py["chance_combos"]):
            self.assertEqual(j["name"], p["name"])
            self.assertEqual([s["buckets"] for s in j["steps"]], [s["buckets"] for s in p["steps"]],
                             f"состав комбо: {p['name']}")
            for js, ps in zip(j["steps"], p["steps"]):
                self._num_eq(js["cost"], ps["cost"], 1e-3, f"{p['name']}/цена")
                self._num_eq(js["p_win"], ps["p_win"], 1e-3, f"{p['name']}/шанс")
                self.assertEqual(js["p_rng"], ps["p_rng"], f"{p['name']}/диапазон")

    def test_final_verdict(self):
        for j, p in zip(self.js["verdict"], self.py["verdict"]):
            self.assertEqual(j["name"], p["name"])
            self.assertEqual(j["verdict"], p["verdict"], f"вердикт: {p['name']}")
            self.assertEqual(j["why"], p["why"], f"обоснование: {p['name']}")
            self._num_eq(j["total_usd"], p["total_usd"], self.MONEY_TOL, f"сумма: {p['name']}")
        # хотя бы один BET и хотя бы один NO BET — иначе кейсы ничего не проверяют
        kinds = {x["verdict"] for x in self.py["verdict"]}
        self.assertEqual(kinds, {"BET", "NO BET"})


class WebClaimsTest(unittest.TestCase):
    """Страницы не имеют права обещать «гарантированный арбитраж» по сумме асков."""

    def test_no_guaranteed_arbitrage_claims(self):
        for name in ("weather_screener.html", "crypto_screener.html", "quake_screener.html"):
            path = os.path.join(ROOT, "web", name)
            with open(path, encoding="utf-8") as f:
                text = f.read()
            for bad in ("гарантированные +", "гарантированный профит", "ГАРАНТИРОВАННАЯ СВЯЗКА",
                        "ЧИСТЫЙ АРБИТРАЖ"):
                self.assertNotIn(bad, text, f"{name}: обещание «{bad}» без комиссий и книг")

    def test_parity_core_markers_present(self):
        with open(HTML, encoding="utf-8") as f:
            text = f.read()
        self.assertIn("/* PARITY-CORE-START", text)
        self.assertIn("/* PARITY-CORE-END */", text)


if __name__ == "__main__":
    unittest.main()
