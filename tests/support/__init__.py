"""Детерминированные заглушки: НИ ОДИН тест не ходит в сеть.

Все внешние API (Gamma, CLOB, data-api, Open-Meteo, METAR) подменяются
функцией `fetch`, которую производственный код принимает параметром.
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)


def market(**kw):
    """Рынок-бакет Gamma с полными торговыми параметрами."""
    m = dict(groupItemTitle="30°C", bestBid=0.09, bestAsk=0.10,
             outcomePrices=json.dumps(["0.10", "0.90"]),
             clobTokenIds=json.dumps(["tok-30", "tok-30-no"]),
             conditionId="0xcond",
             taker_base_fee=500, minimum_tick_size=0.01, minimum_order_size=1.0)
    m.update(kw)
    return m


def book(levels):
    """Стакан CLOB: [(цена, размер)] -> {"asks": [...]}"""
    return {"asks": [{"price": str(p), "size": str(s)} for p, s in levels],
            "bids": []}


class FakeFetch:
    """Подмена `get`: отдаёт заранее записанные ответы по подстроке URL.

    Любой незарегистрированный URL — исключение: тест, который случайно
    полезет в сеть, обязан упасть.
    """

    def __init__(self, routes=None):
        self.routes = dict(routes or {})
        self.calls = []

    def add(self, key, value):
        self.routes[key] = value
        return self

    def __call__(self, url, *a, **kw):
        self.calls.append(url)
        for key, value in self.routes.items():
            if key in url:
                if isinstance(value, Exception):
                    raise value
                return value(url) if callable(value) else value
        raise AssertionError("тест попытался сходить в сеть: " + url)


def combo_step(stake=4.0, buckets=("30°C", "31°C"), asks=(0.10, 0.20),
               tids=("tok-a", "tok-b"), leg_p=(0.30, 0.40), cost=0.315, **kw):
    step = dict(stake=stake, buckets=list(buckets), asks=list(asks), tids=list(tids),
                leg_p=list(leg_p), cost=cost, p_win=round(sum(leg_p), 3),
                p_rng=[0.55, 0.75], ret=round(1/cost - 1, 2),
                ev=round(sum(leg_p)/cost - 1, 2))
    step.update(kw)
    return step
