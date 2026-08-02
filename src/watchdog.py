#!/usr/bin/env python3
"""Quake watchdog: recent big quakes + market gaps. Stdlib only."""
import json, math, re, time, urllib.request, urllib.parse
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

def chance_combos(rows, max_n=4, min_ev=0.15, min_p=0.40, max_cost=0.90):
    """«Шанс-комбо»: равные доли в 2-4 взаимоисключающих бакетах одного рынка.
    Платим sum(ask) за $1 выплаты, выигрываем если исход попал в набор.
    Жадный набор по ценности p/ask; шаг фиксируется при P>=min_p и EV>=min_ev."""
    cand = [r for r in rows if r.get("ask") and 0.001 <= r["ask"] <= 0.9 and r["p"] >= 0.03]
    cand.sort(key=lambda r: -r["p"]/r["ask"])
    steps, S, cost, P, Plo, Phi = [], [], 0.0, 0.0, 0.0, 0.0
    for r in cand:
        if len(S) >= max_n: break
        if cost + r["ask"] > max_cost: continue
        if (P + r["p"])/(cost + r["ask"]) - 1 < min_ev: break
        S.append((r["bucket"], r["ask"], r.get("tid"), r["p"])); cost += r["ask"]; P += r["p"]
        Plo += r.get("pLo", r["p"]); Phi += r.get("pHi", r["p"])
        if len(S) >= 2 and P >= min_p:
            pairs = sorted(S, key=lambda x: (int(re.search(r"-?\d+", x[0]).group()) if re.search(r"-?\d+", x[0]) else 0, 1 if (">" in x[0] or "+" in x[0] or "higher" in x[0] or "above" in x[0]) else -1 if ("<" in x[0] or "≤" in x[0] or "below" in x[0]) else 0))
            steps.append(dict(stake=kelly_stake(P, min(Plo, Phi), cost), buckets=[b for b, _, _, _ in pairs], asks=[round(a, 3) for _, a, _, _ in pairs], tids=[t for _, _, t, _ in pairs], leg_p=[round(pp, 3) for _, _, _, pp in pairs], cost=round(cost, 3), p_win=round(P, 3),
                p_rng=[round(min(Plo, Phi), 2), round(max(Plo, Phi), 2)],
                ret=round(1/cost - 1, 2), ev=round(P/cost - 1, 2)))
    return steps

def quake_scan():
    """Контур №2: рынки числа землетрясений против Пуассона (USGS)."""
    now_ts = datetime.now(timezone.utc).timestamp()
    rates = {}
    for mag in ("5.5", "6.5", "7.0"):
        c = get(f"https://earthquake.usgs.gov/fdsnws/event/1/count?format=geojson&starttime=2025-08-01&endtime=2026-08-01&minmagnitude={mag}")
        rates[mag] = c["count"]/365.0
    d = get("https://gamma-api.polymarket.com/public-search?q=or%20above%20earthquakes&limit_per_type=12&events_status=active")
    out = []
    for e in d.get("events", []):
        slug = e.get("slug","")
        if not slug.startswith("how-many") or "earthquake" not in slug: continue
        mm = re.search(r"(\d)pt(\d)", slug)
        if not mm: continue
        mag = f"{mm.group(1)}.{mm.group(2)}"
        if mag not in rates: continue
        full = get(f"https://gamma-api.polymarket.com/events?slug={slug}")[0]
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
        feats = get(f"https://earthquake.usgs.gov/fdsnws/event/1/query?format=geojson&starttime={iso0}&minmagnitude={mag}&limit=1000").get("features", [])
        n_obs = len(feats)
        borderline = sum(1 for f in feats if abs(f["properties"].get("mag", 0) - float(mag)) < 0.1)
        t_rem = max(0.0, (t1 - now_ts)/86400.0)
        lam = rates[mag] * t_rem
        vol = float(full.get("volume") or 0)
        volpen = 1 if vol < 10000 else 0
        qasks = [m.get("bestAsk") for m in full["markets"] if q_bucket(m.get("groupItemTitle"))]
        q_sum_ask = round(sum(qasks), 3) if (len(qasks) >= 3 and all(a is not None for a in qasks)) else None
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
            if ba is not None and 0.02 <= ba <= 0.25 and p >= 2*ba and p >= 0.08:
                robust = pLo >= 1.5*ba and pHi >= 1.5*ba
                conf = max(1, min(5, 3 + (1 if robust else 0) - volpen))
                (picks if conf >= 4 else watch).append(dict(side="YES", bucket=m.get("groupItemTitle"), cost=ba,
                    p=round(p,3), mid=round(mid,3), ev=round(p*(1/ba-1)-(1-p),2), conf=conf,
                    stake=kelly_stake(p, min(pLo, pHi), ba)))
            if bb is not None and mid >= 0.25 and (mid-p) >= 0.15:
                noask = 1-bb
                robust = (mid-pLo >= 0.10) and (mid-pHi >= 0.10)
                conf = max(1, min(5, 3 + (1 if robust else 0) - volpen))
                (picks if conf >= 4 else watch).append(dict(side="NO", bucket=m.get("groupItemTitle"), cost=round(noask,3),
                    p=round(p,3), mid=round(mid,3), ev=round((1-p)*(1/noask-1)-p,2), conf=conf,
                    stake=kelly_stake(1-p, 1-max(pLo, pHi), noask)))
        out.append(dict(title=full["title"], n_obs=n_obs, borderline=borderline, t_rem_days=round(t_rem,1),
                        lam_rem=round(lam,2), vol=int(vol), picks=picks, watch=watch[:4],
                        combos=chance_combos(qrows)[-2:] if vol >= 500 else [], sum_ask=q_sum_ask,
                        link=f"https://polymarket.com/event/{slug}"))
    return out


# ================= контур №3: крипта против опционов Deribit =================
DMON = {m: i+1 for i, m in enumerate(["JAN","FEB","MAR","APR","MAY","JUN","JUL","AUG","SEP","OCT","NOV","DEC"])}
MONTHS_LOW = ["january","february","march","april","may","june","july","august","september","october","november","december"]

def norm_cdf(x): return 0.5*(1+math.erf(x/math.sqrt(2)))

def load_surface(cur):
    rows = get(f"https://www.deribit.com/api/v2/public/get_book_summary_by_currency?currency={cur}&kind=option")["result"]
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

def crypto_scan():
    """Рынки BTC/ETH above $K против риск-нейтральных вероятностей опционов."""
    now = datetime.now(timezone.utc)
    out = []
    for cur, pref in (("BTC","bitcoin"), ("ETH","ethereum")):
        try: surf = load_surface(cur)
        except Exception as e:
            out.append(dict(error=f"deribit {cur}: {str(e)[:60]}")); continue
        for dd in range(0, 8):
            d = now + timedelta(days=dd)
            slug = f"{pref}-above-on-{MONTHS_LOW[d.month-1]}-{d.day}-{d.year}"
            try: evs = get(f"https://gamma-api.polymarket.com/events?slug={slug}")
            except Exception: continue
            if not evs or evs[0].get("closed"): continue
            ev = evs[0]
            t_res = datetime(d.year, d.month, d.day, 16 if 3 < d.month < 11 else 17, 0, tzinfo=timezone.utc)
            if t_res <= now: continue
            vol = float(ev.get("volume") or 0)
            if vol < 500: continue
            volpen = 1 if vol < 10000 else 0
            picks, watch, klist = [], [], []
            for m in ev["markets"]:
                t = (m.get("groupItemTitle") or "").replace(",", "").replace("$", "")
                if not re.match(r"^\d+$", t): continue
                K = float(t)
                bb, ba = m.get("bestBid"), m.get("bestAsk")
                if bb is None or ba is None: continue
                klist.append((K, bb, ba))
                mid = (bb+ba)/2
                p = prob_above(surf, K, t_res)
                if p is None: continue
                pa = prob_above(surf, K, t_res, 0.9); pb = prob_above(surf, K, t_res, 1.1)
                if pa is None or pb is None: continue
                lo, hi = min(pa, pb), max(pa, pb)
                row = dict(strike=int(K), p=round(p,3), mid=round(mid,3))
                if 0.02 <= ba <= 0.25 and p >= 2*ba and p >= 0.08:
                    conf = max(1, min(5, 3 + (1 if lo >= 1.5*ba else 0) - volpen))
                    (picks if conf >= 4 else watch).append(dict(row, side="YES", cost=ba,
                        ev=round(p*(1/ba-1)-(1-p),2), conf=conf, stake=kelly_stake(p, lo, ba)))
                if mid >= 0.25 and (mid-p) >= 0.15:
                    noask = 1-bb
                    conf = max(1, min(5, 3 + (1 if (mid-hi) >= 0.10 else 0) - volpen))
                    (picks if conf >= 4 else watch).append(dict(row, side="NO", cost=round(noask,3),
                        ev=round((1-p)*(1/noask-1)-p,2), conf=conf, stake=kelly_stake(1-p, 1-hi, noask)))
                if ba > 0.25 and (p-mid) >= 0.15:
                    conf = max(1, min(5, 3 + (1 if (lo-mid) >= 0.10 else 0) - volpen))
                    (picks if conf >= 4 else watch).append(dict(row, side="YES", cost=ba,
                        ev=round(p*(1/ba-1)-(1-p),2), conf=conf, stake=kelly_stake(p, lo, ba)))
            # арбитраж на монотонности страйков: YES K1 + NO K2 (K1<K2) платит >= $1 всегда
            arbs = []
            for (k1, b1, a1), (k2, b2, a2) in zip(sorted(klist), sorted(klist)[1:]):
                c = a1 + (1 - b2)
                if c < 0.995:
                    arbs.append(dict(k1=int(k1), k2=int(k2), cost=round(c, 3), profit=round(1-c, 3)))
            if picks or watch or arbs:
                out.append(dict(title=ev["title"], date=d.strftime("%Y-%m-%d"), vol=int(vol),
                                picks=picks, watch=watch[:3], arbs=arbs,
                                link=f"https://polymarket.com/event/{slug}"))
    return out

def main():
    now = datetime.now(timezone.utc)
    since = (now - timedelta(hours=7)).strftime("%Y-%m-%dT%H:%M:%S")
    recent = get(f"https://earthquake.usgs.gov/fdsnws/event/1/query?format=geojson&starttime={since}&minmagnitude=6.5").get("features", [])
    recent_big = [dict(mag=f["properties"].get("mag"), place=f["properties"].get("place"),
                       time=datetime.fromtimestamp(f["properties"]["time"]/1000, tz=timezone.utc).strftime("%H:%M UTC"))
                  for f in recent]
    try: markets = quake_scan()
    except Exception as e: markets = [{"error": str(e)[:100]}]
    try: crypto = crypto_scan()
    except Exception as e: crypto = [{"error": str(e)[:100]}]
    print(json.dumps(dict(generated=now.strftime("%Y-%m-%d %H:%M UTC"), bankroll=BANKROLL,
                          recent_m65_last7h=recent_big, markets=markets, crypto=crypto),
                     ensure_ascii=False, indent=1))

main()
