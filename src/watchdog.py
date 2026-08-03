#!/usr/bin/env python3
"""Quake watchdog: recent big quakes + market gaps. Stdlib only."""
import json, math, re, time, urllib.request, urllib.parse
from collections import namedtuple
from datetime import datetime, timedelta, timezone

def get(url, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent":"wx-daily/1.0"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode())
        except Exception:
            if i == tries-1: raise
            time.sleep(2*(i+1))

MONTH_EN = {m: i+1 for i, m in enumerate(["January","February","March","April","May","June",
                                          "July","August","September","October","November","December"])}

def q_et_utc(y, mo, d, h, mi):
    off = 4 if 3 < mo < 11 else 5
    return datetime(y, mo, d, h, mi, tzinfo=timezone.utc).timestamp() + off*3600
def q_bucket(t):
    t = (t or "").strip()
    m = re.match(r"^≤(\d+)$", t)
    if m: return (-1, int(m.group(1)))
    m = re.match(r"^>(\d+)$", t)
    if m: return (int(m.group(1))+1, 10**6)
    m = re.match(r"^<(\d+)$", t)
    if m: return (-1, int(m.group(1))-1)
    m = re.match(r"^(\d+)\+$", t)
    if m: return (int(m.group(1)), 10**6)
    m = re.match(r"^(\d+)[–-](\d+)$", t)
    if m: return (int(m.group(1)), int(m.group(2)))
    m = re.match(r"^(\d+)$", t)
    if m: return (int(m.group(1)), int(m.group(1)))
    return None
def q_prange(lo, hi, n_obs, lam):
    lo = max(lo, n_obs)
    if hi < n_obs: return 0.0
    def pmf(k):
        return math.exp(-lam + k*math.log(lam) - math.lgamma(k+1)) if lam > 0 else (1.0 if k == 0 else 0.0)
    m_lo = lo - n_obs
    if hi >= 10**5:
        return max(0.0, 1.0 - sum(pmf(m) for m in range(0, m_lo)))
    return sum(pmf(k - n_obs) for k in range(lo, hi+1))

BANKROLL = 100.0  # банкролл Дмитрия, $ — обновляется по мере роста счёта
DAY_LIMIT = 15.0  # дневной лимит, $ — фаза проверки; после 30 ставок с подтверждённой точностью поднять до 25

def fee(price, mp):
    """Комиссия тейкера, $/акцию, по ставке КОНКРЕТНОГО рынка."""
    return mp.fee_rate*price*(1-price)

def allin(price, mp):
    """Полная цена входа: цена + комиссия этого рынка."""
    return price + fee(price, mp)

# ---------- торговые параметры КОНКРЕТНОГО рынка (fail-closed) ----------
# Те же правила, что в src/wx_daily.py. Код продублирован намеренно: сторож
# запускается отдельным файлом и не может импортировать соседний модуль.
# min_notional — минимальный размер ордера в USDC (Gamma `orderMinSize`);
# min_shares   — минимальное число акций за ордер (CLOB `minimum_order_size`).
MarketParams = namedtuple("MarketParams", "fee_rate tick min_notional min_shares source")

FEE_RATE_MAX = 0.20    # санитарный потолок ставки комиссии
TICK_MAX = 0.10        # шаг цены крупнее 10¢ — данные битые
MIN_ORDER_MAX = 100.0  # минимальный ордер дороже $100 — данные битые
CLOB_MARKET_URL = "https://clob.polymarket.com/markets/"
PARAM_FAILS = []       # рынки, снятые из-за неподтверждённых параметров

def _num(src, *keys):
    for k in keys:
        v = src.get(k)
        if v in (None, ""): continue
        try: return float(v)
        except (TypeError, ValueError): return None
    return None

def _fee_rate(v):
    """taker_base_fee: >1 — базисные пункты (500 → 0.05), 0..1 — уже доля."""
    if v is None: return None
    return v/10000.0 if v > 1 else float(v)

def _fee_rate_canonical(m):
    """Каноническое расписание комиссий: feesEnabled + feeSchedule (rate, exponent, takerOnly).
    Возвращает (ставка, is_canonical). Если feesEnabled отсутствует — (None, False).
    Если feesEnabled=True, а расписание не читается или содержит неподдерживаемые
    значения — (None, True) → fail-closed.
    
    Поддерживаемая модель: exponent=2 (квадратичная кривая rate*price*(1-price)),
    takerOnly=True (одинаковая комиссия тейкера/мейкера не поддерживается)."""
    fees_enabled = m.get("feesEnabled")
    if fees_enabled is None: return None, False
    if not fees_enabled: return 0.0, True
    schedule = m.get("feeSchedule") or {}
    rate = _num(schedule, "rate")
    if rate is None: return None, True
    # Проверяем exponent: если присутствует, обязан быть 2 (квадратичная кривая)
    exponent = schedule.get("exponent")
    if exponent is not None and exponent != 2: return None, True
    # Проверяем takerOnly: если присутствует, обязан быть True
    taker_only = schedule.get("takerOnly")
    if taker_only is not None and not taker_only: return None, True
    return float(rate), True

def parse_market_params(m):
    """Ничего не подставляем по умолчанию: нет поля или значение вне
    санитарных границ — None, и рынок не торгуется."""
    if not isinstance(m, dict): return None
    canonical_rate, is_canonical = _fee_rate_canonical(m)
    if is_canonical:
        if canonical_rate is None: return None
        legacy = _fee_rate(_num(m, "taker_base_fee", "takerBaseFee", "tbf",
                                "feeRateBps", "fee_rate_bps"))
        if legacy is not None and abs(legacy - canonical_rate) > 1e-9: return None
        fee_rate = canonical_rate
    else:
        fee_rate = _fee_rate(_num(m, "taker_base_fee", "takerBaseFee", "tbf",
                                  "feeRateBps", "fee_rate_bps"))
    tick = _num(m, "minimum_tick_size", "orderPriceMinTickSize", "mts", "tickSize")
    min_notional = _num(m, "orderMinSize", "minimum_order_size", "mos", "minimumOrderSize")
    if fee_rate is None or tick is None or min_notional is None: return None
    if not (0.0 <= fee_rate <= FEE_RATE_MAX): return None
    if not (0.0 < tick <= TICK_MAX): return None
    if not (0.0 < min_notional <= MIN_ORDER_MAX): return None
    return MarketParams(fee_rate=fee_rate, tick=tick, min_notional=min_notional,
                        min_shares=0.0, source="market")

def market_params(m, fetch=None):
    """Нотионал (USDC) и шаг/комиссия из Gamma; min_shares (акции) из CLOB."""
    p = parse_market_params(m)
    if p is None:
        gamma_notional = _num(m, "orderMinSize", "minimum_order_size", "mos", "minimumOrderSize")
        if gamma_notional is None or not (0.0 < gamma_notional <= MIN_ORDER_MAX): return None
        cid = (m or {}).get("conditionId") or (m or {}).get("condition_id")
        if not cid: return None
        try: raw = (fetch or get)(CLOB_MARKET_URL + str(cid))
        except Exception: return None
        if not isinstance(raw, dict): return None
        canonical_rate, is_canonical = _fee_rate_canonical(m)
        fee_rate = canonical_rate if is_canonical else \
                   (_fee_rate(_num(raw, "taker_base_fee", "takerBaseFee")) or
                    _fee_rate(_num(m, "taker_base_fee", "takerBaseFee")))
        tick = _num(raw, "minimum_tick_size", "orderPriceMinTickSize") or \
               _num(m, "minimum_tick_size", "orderPriceMinTickSize")
        if fee_rate is None or tick is None: return None
        if not (0.0 <= fee_rate <= FEE_RATE_MAX): return None
        if not (0.0 < tick <= TICK_MAX): return None
        clob_shares = _num(raw, "minimum_order_size", "min_order_size") or 0.0
        p = MarketParams(fee_rate=fee_rate, tick=tick, min_notional=gamma_notional,
                         min_shares=clob_shares, source="clob")
    else:
        cid = (m or {}).get("conditionId") or (m or {}).get("condition_id")
        if cid:
            try:
                raw = (fetch or get)(CLOB_MARKET_URL + str(cid))
                if isinstance(raw, dict):
                    clob_shares = _num(raw, "minimum_order_size", "min_order_size") or 0.0
                    if clob_shares > p.min_shares:
                        p = p._replace(min_shares=clob_shares)
            except Exception: pass
    return p

def event_params(markets, fetch=None):
    """Параметры обязаны быть у КАЖДОГО торгуемого бакета, иначе None.
    При расхождении берём худший вариант."""
    markets = list(markets or [])
    if not markets: return None
    ps = []
    for m in markets:
        p = market_params(m, fetch)
        if p is None: return None
        ps.append(p)
    return MarketParams(fee_rate=max(p.fee_rate for p in ps),
                        tick=max(p.tick for p in ps),
                        min_notional=max(p.min_notional for p in ps),
                        min_shares=max(p.min_shares for p in ps),
                        source="event")

def _token_ids(m):
    try:
        ti = (m or {}).get("clobTokenIds")
        ti = json.loads(ti) if isinstance(ti, str) else ti
        return list(ti) if ti else [None, None]
    except Exception:
        return [None, None]

def check_arb_legs(legs, mp, fetch=None):
    """Связка засчитывается ТОЛЬКО как исполнимая: полные цены с комиссиями
    ЭТОГО рынка, реальные уровни стакана и минимальный ордер на каждой ноге.
    «Сумма асков ниже единицы» гарантией не является.
    legs: [(token_id, котируемая цена)]."""
    fetch = fetch or get
    sets, cost, leg_data = None, 0.0, []
    for tid, _quoted in legs:
        if not tid:
            return dict(ok=False, why="нет идентификатора книги", exec_sets=0, exec_profit=0.0)
        try:
            book = fetch(f"https://clob.polymarket.com/book?token_id={tid}")
            asks = sorted((float(a["price"]), float(a["size"])) for a in book.get("asks", []))
            # Валидируем метаданные книги
            book_min_order = _num(book, "min_order_size", "minimum_order_size")
            book_tick = _num(book, "tick_size", "minimum_tick_size")
            if book_min_order is None or book_tick is None:
                return dict(ok=False, why="книга без метаданных min_order_size/tick_size",
                           exec_sets=0, exec_profit=0.0)
            if book_min_order is None or book_min_order <= 0 or book_min_order > MIN_ORDER_MAX:
                return dict(ok=False, why=f"некорректный book min_order_size={book_min_order} или нулевой",
                           exec_sets=0, exec_profit=0.0)
            if book_tick <= 0 or book_tick > TICK_MAX:
                return dict(ok=False, why=f"некорректный book tick_size={book_tick}",
                           exec_sets=0, exec_profit=0.0)
            # Проверяем совместимость mp.tick и book_tick
            if mp.tick and book_tick:
                if abs(mp.tick - book_tick) > 1e-9:
                    return dict(ok=False, why=f"несовместимые тики: Gamma tick={mp.tick} vs книга tick_size={book_tick}",
                               exec_sets=0, exec_profit=0.0)
        except Exception:
            return dict(ok=False, why="книга недоступна", exec_sets=0, exec_profit=0.0)
        if not asks:
            return dict(ok=False, why="пустая книга", exec_sets=0, exec_profit=0.0)
        price, size = asks[0]
        # Проверяем, что цена совместима с book_tick
        price_tick_mismatch = abs(price - round(price / book_tick) * book_tick)
        if price_tick_mismatch > 1e-9:
            return dict(ok=False, why=f"цена {price} не кратна книжному tick_size={book_tick}",
                       exec_sets=0, exec_profit=0.0)
        cost += allin(price, mp)
        sets = size if sets is None else min(sets, size)
        leg_data.append(dict(price=price, size=size, book_min_shares=book_min_order))
    sets = int(math.floor(sets or 0))
    res = dict(exec_sets=sets, exec_cost=round(cost, 3), exec_profit=0.0)
    if sets <= 0:
        return dict(res, ok=False, why="в книге нет объёма")
    if cost >= 1.0:
        return dict(res, ok=False, why=f"полная цена комплекта {cost:.3f} ≥ $1 — прибыли нет")
    # Проверяем минимум на каждой ноге: как USDC notional, так и shares
    for leg in leg_data:
        notional = allin(leg["price"], mp) * sets
        if notional + 1e-9 < mp.min_notional:
            return dict(res, ok=False, why=f"объёма не хватает на минимальный ордер ${mp.min_notional:g} по каждой ноге")
        if sets + 1e-9 < leg["book_min_shares"]:
            return dict(res, ok=False, why=f"объём {sets} акций < минимум книги {leg['book_min_shares']:g} акций на одной из ног")
    return dict(res, ok=True, why=None, exec_profit=round((1.0-cost)*sets, 2))

def kelly_stake(p_base, p_cons, cost, bankroll=None, cap=None, frac=0.25):
    """Рекомендуемый размер: четверть Келли по осторожной вероятности
    p_use = (базовая + стрессовая)/2. 0 = не ставить. Минимум сделки $1."""
    bankroll = BANKROLL if bankroll is None else bankroll
    cap = DAY_LIMIT if cap is None else cap
    if not (0 < cost < 1) or p_base is None: return 0.0
    p_use = p_base if p_cons is None else 0.5*(p_base + p_cons)
    b = (1-cost)/cost
    f = p_use - (1-p_use)/b
    if f <= 0: return 0.0
    s = min(bankroll*f*frac, cap)
    return 0.0 if s < 0.5 else round(max(s, 1.0), 2)

def chance_combos(rows, mp, max_n=4, min_ev=0.15, min_p=0.40, max_cost=0.90):
    """«Шанс-комбо»: равные доли в 2-4 взаимоисключающих бакетах одного рынка.
    Платим sum(ask) за $1 выплаты, выигрываем если исход попал в набор.
    Жадный набор по ценности p/ask; шаг фиксируется при P>=min_p и EV>=min_ev."""
    cand = [r for r in rows if r.get("ask") and 0.03 <= r["ask"] <= 0.9 and r["p"] >= 0.03]
    cand.sort(key=lambda r: -r["p"]/allin(r["ask"], mp))
    steps, S, cost, P, Plo, Phi = [], [], 0.0, 0.0, 0.0, 0.0
    for r in cand:
        if len(S) >= max_n: break
        ca = allin(r["ask"], mp)
        if cost + ca > max_cost: continue
        if (P + r["p"])/(cost + ca) - 1 < min_ev: break
        S.append((r["bucket"], r["ask"], r.get("tid"), r["p"])); cost += ca; P += r["p"]
        Plo += r.get("pLo", r["p"]); Phi += r.get("pHi", r["p"])
        if len(S) >= 2 and P >= min_p:
            pairs = sorted(S, key=lambda x: (int(re.search(r"-?\d+", x[0]).group()) if re.search(r"-?\d+", x[0]) else 0, 1 if (">" in x[0] or "+" in x[0] or "higher" in x[0] or "above" in x[0]) else -1 if ("<" in x[0] or "≤" in x[0] or "below" in x[0]) else 0))
            steps.append(dict(stake=kelly_stake(P, min(Plo, Phi), cost), buckets=[b for b, _, _, _ in pairs], asks=[round(a, 3) for _, a, _, _ in pairs], tids=[t for _, _, t, _ in pairs], leg_p=[round(pp, 3) for _, _, _, pp in pairs], cost=round(cost, 3), p_win=round(P, 3),
                p_rng=[round(min(Plo, Phi), 2), round(max(Plo, Phi), 2)],
                ret=round(1/cost - 1, 2), ev=round(P/cost - 1, 2)))
    return steps

def quake_scan(fetch=None):
    """Контур №2: рынки числа землетрясений против Пуассона (USGS)."""
    fetch = fetch or get
    now_ts = datetime.now(timezone.utc).timestamp()
    rates = {}
    for mag in ("5.5", "6.5", "7.0"):
        c = fetch(f"https://earthquake.usgs.gov/fdsnws/event/1/count?format=geojson&starttime=2025-08-01&endtime=2026-08-01&minmagnitude={mag}")
        rates[mag] = c["count"]/365.0
    d = fetch("https://gamma-api.polymarket.com/public-search?q=or%20above%20earthquakes&limit_per_type=12&events_status=active")
    out = []
    for e in d.get("events", []):
        slug = e.get("slug","")
        if not slug.startswith("how-many") or "earthquake" not in slug: continue
        mm = re.search(r"(\d)pt(\d)", slug)
        if not mm: continue
        mag = f"{mm.group(1)}.{mm.group(2)}"
        if mag not in rates: continue
        full = fetch(f"https://gamma-api.polymarket.com/events?slug={slug}")[0]
        if full.get("closed"): continue
        w = re.search(r"between (\w+) (\d+), (\d+),? 12:00 AM ET,? and (\w+) (\d+), (\d+),? 11:59 PM ET", full["description"])
        if w:
            t0 = q_et_utc(int(w.group(3)), MONTH_EN[w.group(1)], int(w.group(2)), 0, 0)
            t1 = q_et_utc(int(w.group(6)), MONTH_EN[w.group(4)], int(w.group(5)), 23, 59)
        elif "in-2026" in slug:
            t0 = q_et_utc(2026,1,1,0,0); t1 = q_et_utc(2026,12,31,23,59)
        else: continue
        if now_ts >= t1: continue
        iso0 = datetime.fromtimestamp(t0, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        feats = fetch(f"https://earthquake.usgs.gov/fdsnws/event/1/query?format=geojson&starttime={iso0}&minmagnitude={mag}&limit=1000").get("features", [])
        n_obs = len(feats)
        borderline = sum(1 for f in feats if abs(f["properties"].get("mag", 0) - float(mag)) < 0.1)
        t_rem = max(0.0, (t1 - now_ts)/86400.0)
        lam = rates[mag] * t_rem
        vol = float(full.get("volume") or 0)
        volpen = 1 if vol < 10000 else 0
        qmarkets = [m for m in full["markets"] if q_bucket(m.get("groupItemTitle"))]
        mp = event_params(qmarkets, fetch)   # свои параметры рынка, не погодная константа
        if mp is None:
            PARAM_FAILS.append(f"{slug}: торговые параметры рынка не подтверждены"); continue
        qasks = [m.get("bestAsk") for m in qmarkets]
        ok_asks = len(qasks) >= 3 and all(a is not None for a in qasks)
        q_sum_ask = round(sum(qasks), 3) if ok_asks else None
        q_sum_allin = round(sum(allin(a, mp) for a in qasks), 3) if ok_asks else None
        # «сумма асков < $1» — только кандидат; арбитраж засчитывается лишь после
        # полных цен с комиссиями рынка, уровней книг и минимального ордера.
        q_arb = (check_arb_legs([(_token_ids(m)[0], m.get("bestAsk")) for m in qmarkets], mp, fetch)
                 if (q_sum_allin is not None and q_sum_allin < 0.995) else None)
        picks, watch, qrows = [], [], []
        for m in full["markets"]:
            rng = q_bucket(m.get("groupItemTitle"))
            if not rng: continue
            bb, ba = m.get("bestBid"), m.get("bestAsk")
            pr = m.get("outcomePrices"); pr = json.loads(pr) if isinstance(pr, str) else pr
            mid = (bb+ba)/2 if (bb is not None and ba is not None) else (float(pr[0]) if pr else None)
            if mid is None or vol < 500: continue
            p   = q_prange(*rng, n_obs, lam)
            pLo = q_prange(*rng, n_obs, lam*0.7)
            pHi = q_prange(*rng, n_obs, lam*1.4)
            qrows.append(dict(bucket=m.get("groupItemTitle"), p=p, pLo=pLo, pHi=pHi, ask=ba))
            if ba is not None and 0.03 <= ba <= 0.25 and p >= 2*ba and p >= 0.08:
                c = allin(ba, mp)
                robust = pLo >= 1.5*c and pHi >= 1.5*c
                conf = max(1, min(5, 3 + (1 if robust else 0) - volpen))
                (picks if conf >= 4 else watch).append(dict(side="YES", bucket=m.get("groupItemTitle"), cost=round(c,3),
                    p=round(p,3), mid=round(mid,3), ev=round(p*(1/c-1)-(1-p),2), conf=conf,
                    stake=kelly_stake(p, min(pLo, pHi), c)))
            if bb is not None and mid >= 0.25 and (mid-p) >= 0.15:
                c = allin(1-bb, mp)
                robust = (mid-pLo >= 0.10) and (mid-pHi >= 0.10)
                conf = max(1, min(5, 3 + (1 if robust else 0) - volpen))
                (picks if conf >= 4 else watch).append(dict(side="NO", bucket=m.get("groupItemTitle"), cost=round(c,3),
                    p=round(p,3), mid=round(mid,3), ev=round((1-p)*(1/c-1)-p,2), conf=conf,
                    stake=kelly_stake(1-p, 1-max(pLo, pHi), c)))
        out.append(dict(title=full["title"], n_obs=n_obs, borderline=borderline, t_rem_days=round(t_rem,1),
                        lam_rem=round(lam,2), vol=int(vol), picks=picks, watch=watch[:4],
                        combos=chance_combos(qrows, mp)[-2:] if vol >= 500 else [],
                        sum_ask=q_sum_ask, sum_allin=q_sum_allin, arb=q_arb,
                        link=f"https://polymarket.com/event/{slug}"))
    return out


# ================= контур №3: крипта против опционов Deribit =================
DMON = {m: i+1 for i, m in enumerate(["JAN","FEB","MAR","APR","MAY","JUN","JUL","AUG","SEP","OCT","NOV","DEC"])}
MONTHS_LOW = ["january","february","march","april","may","june","july","august","september","october","november","december"]

def norm_cdf(x): return 0.5*(1+math.erf(x/math.sqrt(2)))

def load_surface(cur, fetch=None):
    rows = (fetch or get)(f"https://www.deribit.com/api/v2/public/get_book_summary_by_currency?currency={cur}&kind=option")["result"]
    surf = {}
    for r in rows:
        parts = r["instrument_name"].split("-")
        m = re.match(r"^(\d+)([A-Z]{3})(\d{2})$", parts[1])
        iv = r.get("mark_iv")
        if not m or iv is None or iv <= 0: continue
        exp = datetime(2000+int(m.group(3)), DMON[m.group(2)], int(m.group(1)), 8, 0, tzinfo=timezone.utc)
        e = surf.setdefault(exp, {"F": r.get("underlying_price"), "iv": {}})
        e["iv"].setdefault(float(parts[2]), []).append(iv)
    for e in surf.values():
        e["iv"] = {k: sum(v)/len(v) for k, v in e["iv"].items()}
    return dict(sorted(surf.items()))

def iv_at(strikes_iv, K):
    ks = sorted(strikes_iv)
    if not ks: return None
    if K <= ks[0]: return strikes_iv[ks[0]]
    if K >= ks[-1]: return strikes_iv[ks[-1]]
    for a, b in zip(ks, ks[1:]):
        if a <= K <= b:
            w = (K-a)/(b-a)
            return strikes_iv[a]*(1-w) + strikes_iv[b]*w

def prob_above(surf, K, t_res, iv_mult=1.0):
    now = datetime.now(timezone.utc)
    exps = [e for e in surf if e > now]
    if not exps: return None
    before = [e for e in exps if e <= t_res]; after = [e for e in exps if e >= t_res]
    T = (t_res-now).total_seconds()/(365*86400)
    if T <= 0: return None
    def w_of(exp):
        iv = iv_at(surf[exp]["iv"], K)
        if iv is None: return None
        iv = iv*iv_mult/100.0
        Te = (exp-now).total_seconds()/(365*86400)
        return iv*iv*Te, Te
    if before and after and before[-1] != after[0]:
        a, b = w_of(before[-1]), w_of(after[0])
        if not a or not b: return None
        w = a[0] + (b[0]-a[0])*(T-a[1])/(b[1]-a[1])
    else:
        exp = after[0] if after else before[-1]
        r = w_of(exp)
        if not r: return None
        w = r[0]*T/r[1]
    F = surf[after[0] if after else before[-1]]["F"]
    if not F: return None
    s = math.sqrt(max(w, 1e-9))
    return norm_cdf((math.log(F/K) - 0.5*w)/s)

def crypto_scan(fetch=None):
    """Рынки BTC/ETH above $K против риск-нейтральных вероятностей опционов."""
    fetch = fetch or get
    now = datetime.now(timezone.utc)
    out = []
    for cur, pref in (("BTC","bitcoin"), ("ETH","ethereum")):
        try: surf = load_surface(cur, fetch)
        except Exception as e:
            out.append(dict(error=f"deribit {cur}: {str(e)[:60]}")); continue
        for dd in range(0, 8):
            d = now + timedelta(days=dd)
            slug = f"{pref}-above-on-{MONTHS_LOW[d.month-1]}-{d.day}-{d.year}"
            try: evs = fetch(f"https://gamma-api.polymarket.com/events?slug={slug}")
            except Exception: continue
            if not evs or evs[0].get("closed"): continue
            ev = evs[0]
            t_res = datetime(d.year, d.month, d.day, 16 if 3 < d.month < 11 else 17, 0, tzinfo=timezone.utc)
            if t_res <= now: continue
            vol = float(ev.get("volume") or 0)
            if vol < 500: continue
            volpen = 1 if vol < 10000 else 0
            kmarkets = [m for m in ev["markets"]
                        if re.match(r"^\d+$", (m.get("groupItemTitle") or "").replace(",", "").replace("$", ""))]
            mp = event_params(kmarkets, fetch)   # комиссии крипты — СВОИ, не погодная константа
            if mp is None:
                PARAM_FAILS.append(f"{slug}: торговые параметры рынка не подтверждены"); continue
            picks, watch, klist = [], [], []
            for m in kmarkets:
                t = (m.get("groupItemTitle") or "").replace(",", "").replace("$", "")
                K = float(t)
                bb, ba = m.get("bestBid"), m.get("bestAsk")
                if bb is None or ba is None: continue
                klist.append((K, bb, ba, _token_ids(m)))
                mid = (bb+ba)/2
                p = prob_above(surf, K, t_res)
                if p is None: continue
                pa = prob_above(surf, K, t_res, 0.9); pb = prob_above(surf, K, t_res, 1.1)
                if pa is None or pb is None: continue
                lo, hi = min(pa, pb), max(pa, pb)
                row = dict(strike=int(K), p=round(p,3), mid=round(mid,3))
                if 0.03 <= ba <= 0.25 and p >= 2*ba and p >= 0.08:
                    c = allin(ba, mp)
                    conf = max(1, min(5, 3 + (1 if lo >= 1.5*c else 0) - volpen))
                    (picks if conf >= 4 else watch).append(dict(row, side="YES", cost=round(c,3),
                        ev=round(p*(1/c-1)-(1-p),2), conf=conf, stake=kelly_stake(p, lo, c)))
                if mid >= 0.25 and (mid-p) >= 0.15:
                    c = allin(1-bb, mp)
                    conf = max(1, min(5, 3 + (1 if (mid-hi) >= 0.10 else 0) - volpen))
                    (picks if conf >= 4 else watch).append(dict(row, side="NO", cost=round(c,3),
                        ev=round((1-p)*(1/c-1)-p,2), conf=conf, stake=kelly_stake(1-p, 1-hi, c)))
                if ba > 0.25 and (p-mid) >= 0.15:
                    c = allin(ba, mp)
                    conf = max(1, min(5, 3 + (1 if (lo-mid) >= 0.10 else 0) - volpen))
                    (picks if conf >= 4 else watch).append(dict(row, side="YES", cost=round(c,3),
                        ev=round(p*(1/c-1)-(1-p),2), conf=conf, stake=kelly_stake(p, lo, c)))
            # арбитраж на монотонности страйков: YES K1 + NO K2 (K1<K2) платит >= $1 всегда
            arbs = []
            ks = sorted(klist)
            for (k1, b1, a1, t1), (k2, b2, a2, t2) in zip(ks, ks[1:]):
                c = allin(a1, mp) + allin(1 - b2, mp)   # полные цены обеих ног
                if c >= 1.0: continue
                arb = check_arb_legs([(t1[0], a1), (t2[1], 1 - b2)], mp, fetch)
                arb.update(k1=int(k1), k2=int(k2), cost=round(c, 3))
                if arb["ok"]:                            # только исполнимая связка считается связкой
                    arbs.append(arb)
            if picks or watch or arbs:
                out.append(dict(title=ev["title"], date=d.strftime("%Y-%m-%d"), vol=int(vol),
                                picks=picks, watch=watch[:3], arbs=arbs,
                                link=f"https://polymarket.com/event/{slug}"))
    return out

def main(fetch=None):
    fetch = fetch or get
    now = datetime.now(timezone.utc)
    since = (now - timedelta(hours=7)).strftime("%Y-%m-%dT%H:%M:%S")
    recent = fetch(f"https://earthquake.usgs.gov/fdsnws/event/1/query?format=geojson&starttime={since}&minmagnitude=6.5").get("features", [])
    recent_big = [dict(mag=f["properties"].get("mag"), place=f["properties"].get("place"),
                       time=datetime.fromtimestamp(f["properties"]["time"]/1000, tz=timezone.utc).strftime("%H:%M UTC"))
                  for f in recent]
    try: markets = quake_scan(fetch)
    except Exception as e: markets = [{"error": str(e)[:100]}]
    try: crypto = crypto_scan(fetch)
    except Exception as e: crypto = [{"error": str(e)[:100]}]
    print(json.dumps(dict(generated=now.strftime("%Y-%m-%d %H:%M UTC"), bankroll=BANKROLL,
                          recent_m65_last7h=recent_big, markets=markets, crypto=crypto,
                          param_checks=PARAM_FAILS),
                     ensure_ascii=False, indent=1))

if __name__ == "__main__":
    main()
