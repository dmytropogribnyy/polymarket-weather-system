#!/usr/bin/env python3
"""Daily Polymarket weather job: recalibrate stations -> screen tomorrow &
day-after -> print JSON report. Self-contained, stdlib only."""
import json, math, re, time, urllib.request, urllib.parse
from datetime import datetime, timedelta, timezone

ST = {  # slug: (icao|None, lat, lon, unit, ru)
 "london":("EGLC",51.5053,0.0553,"C","Лондон"), "paris":("LFPB",48.9694,2.4414,"C","Париж"),
 "milan":("LIMC",45.6306,8.7281,"C","Милан"), "munich":("EDDM",48.3538,11.7861,"C","Мюнхен"),
 "madrid":("LEMD",40.4719,-3.5626,"C","Мадрид"), "warsaw":("EPWA",52.1657,20.9671,"C","Варшава"),
 "amsterdam":("EHAM",52.3105,4.7683,"C","Амстердам"), "nyc":("KLGA",40.7769,-73.874,"F","Нью-Йорк"),
 "chicago":("KORD",41.9786,-87.9048,"F","Чикаго"), "dallas":("KDAL",32.8471,-96.8518,"F","Даллас"),
 "miami":("KMIA",25.7959,-80.287,"F","Майами"), "atlanta":("KATL",33.6407,-84.4277,"F","Атланта"),
 "seattle":("KSEA",47.4502,-122.3088,"F","Сиэтл"), "toronto":("CYYZ",43.6777,-79.6248,"C","Торонто"),
 "seoul":("RKSI",37.4602,126.4407,"C","Сеул"), "tokyo":("RJTT",35.5494,139.7798,"C","Токио"),
 "shanghai":("ZSPD",31.1443,121.8083,"C","Шанхай"), "singapore":("WSSS",1.3644,103.9915,"C","Сингапур"),
 "hong-kong":(None,22.302,114.1741,"C","Гонконг"), "wellington":("NZWN",-41.3272,174.8053,"C","Веллингтон"),
 "sao-paulo":("SBGR",-23.4356,-46.4731,"C","Сан-Паулу"), "buenos-aires":("SAEZ",-34.8222,-58.5358,"C","Буэнос-Айрес"),
 "mexico-city":("MMMX",19.4363,-99.0721,"C","Мехико"),
 "chongqing":("ZUCK",29.719,106.642,"C","Чунцин"), "chengdu":("ZUUU",30.578,103.947,"C","Чэнду"),
 "kuala-lumpur":("WMKK",2.746,101.710,"C","Куала-Лумпур"), "los-angeles":("KLAX",33.9425,-118.408,"F","Лос-Анджелес"),
 "tel-aviv":("LLBG",32.011,34.886,"C","Тель-Авив"), "beijing":("ZBAA",40.080,116.585,"C","Пекин"),
 "taipei":("RCSS",25.069,121.552,"C","Тайбэй"), "helsinki":("EFHK",60.317,24.963,"C","Хельсинки"),
 "lucknow":("VILK",26.761,80.889,"C","Лакхнау"), "jeddah":("OEJN",21.680,39.157,"C","Джидда"),
 "karachi":("OPKC",24.907,67.161,"C","Карачи"), "houston":("KHOU",29.646,-95.279,"F","Хьюстон"),
 "ankara":("LTAC",40.128,32.995,"C","Анкара"), "wuhan":("ZHHH",30.784,114.208,"C","Ухань"),
 "guangzhou":("ZGGG",23.392,113.299,"C","Гуанчжоу"), "denver":("KBKF",39.702,-104.752,"F","Денвер"),
 "istanbul":("LTFM",41.276,28.752,"C","Стамбул"), "qingdao":("ZSQD",36.362,120.088,"C","Циндао"),
 "cape-town":("FACT",-33.965,18.602,"C","Кейптаун"), "manila":("RPLL",14.509,121.020,"C","Манила"),
 "austin":("KAUS",30.1975,-97.6664,"F","Остин"), "busan":("RKPK",35.1795,128.9382,"C","Пусан"),
 "shenzhen":("ZGSZ",22.6393,113.8107,"C","Шэньчжэнь"), "san-francisco":("KSFO",37.6213,-122.379,"F","Сан-Франциско"),
 "moscow":("UUWW",55.5915,37.2615,"C","Москва")}
REF_BIAS = {"london":-0.06,"paris":1.02,"milan":0.44,"munich":2.52,"madrid":0.48,"warsaw":-0.26,
 "amsterdam":1.32,"nyc":-0.62,"chicago":0.04,"dallas":-0.12,"miami":1.39,"atlanta":0.58,
 "seattle":0.58,"toronto":0.18,"seoul":1.68,"tokyo":-1.98,"shanghai":-0.81,"singapore":1.43,
 "hong-kong":0.0,"wellington":1.03,"sao-paulo":0.17,"buenos-aires":1.15,"mexico-city":-0.77,
 "chongqing":2.60,"chengdu":0.25,"kuala-lumpur":0.40,"los-angeles":-6.55,"tel-aviv":-2.54,
 "beijing":0.41,"taipei":1.98,"helsinki":1.60,"lucknow":0.80,"jeddah":-2.15,"karachi":-1.33,
 "houston":0.34,"ankara":0.49,"wuhan":1.65,"guangzhou":2.21,"denver":1.10,"istanbul":0.00,
 "qingdao":0.32,"cape-town":0.82,"manila":1.31,
 "austin":0.27,"busan":-1.47,"shenzhen":0.86,"san-francisco":1.94,"moscow":-0.05}  # 2026-08-01, новые города 2026-08-02
MONTHS = ["january","february","march","april","may","june","july","august","september","october","november","december"]

def get(url, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent":"wx-daily/1.0"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode())
        except Exception:
            if i == tries-1: raise
            time.sleep(2*(i+1))

def phi(x): return 0.5*(1+math.erf(x/math.sqrt(2)))
def f2c(f): return (f-32)*5/9

def daymax(times, vals, date=None, is_min=False):
    out = {}
    for t, v in zip(times, vals):
        if v is None: continue
        d = t[:10]
        if date and d != date: continue
        if d not in out or (v < out[d] if is_min else v > out[d]): out[d] = v
    return out

MIN_SLUGS = ["hong-kong","london","miami","nyc","paris","seoul","shanghai","tokyo"]
REF_BIAS_MIN = {"hong-kong":0.0,"london":1.01,"miami":0.38,"nyc":1.21,"paris":0.38,
                "seoul":0.88,"shanghai":-0.45,"tokyo":0.49}  # 2026-08-01

def calibrate(slug, is_min=False):
    icao, lat, lon, unit, _ = ST[slug]
    if icao is None: return dict(bias=0.0, n=0, std=None, tier="C")
    now = datetime.now(timezone.utc)
    start = (now - timedelta(days=10)).strftime("%Y-%m-%d"); today = now.strftime("%Y-%m-%d")
    h = get("https://historical-forecast-api.open-meteo.com/v1/forecast?"
            f"latitude={lat}&longitude={lon}&hourly=temperature_2m&models=ecmwf_ifs025"
            f"&timezone=auto&start_date={start}&end_date={today}")
    model = daymax(h["hourly"]["time"], h["hourly"]["temperature_2m"], is_min=is_min)
    off = h.get("utc_offset_seconds", 0)
    obs = {}
    for o in get(f"https://aviationweather.gov/api/data/metar?ids={icao}&format=json&hours=336"):
        t, temp = o.get("reportTime"), o.get("temp")
        if t is None or temp is None: continue
        dt = datetime.fromisoformat(t.replace("Z","+00:00").replace(".000","")) + timedelta(seconds=off)
        k = dt.strftime("%Y-%m-%d")
        if k not in obs or (temp < obs[k] if is_min else temp > obs[k]): obs[k] = float(temp)
    cutoff = (now - timedelta(days=1)).strftime("%Y-%m-%d") if is_min else \
             (today if (datetime.now(timezone.utc)+timedelta(seconds=off)).hour >= 19 else \
              (datetime.now(timezone.utc)-timedelta(days=1)).strftime("%Y-%m-%d"))
    diffs = [obs[d]-model[d] for d in sorted(model) if d in obs and d <= cutoff]
    n = len(diffs)
    if n < 2: return dict(bias=0.0, n=n, std=None, tier="C")
    mean = sum(diffs)/n; std = math.sqrt(sum((x-mean)**2 for x in diffs)/n)
    tier = "A" if (n>=6 and std<=0.8 and abs(mean)<=4) else ("B" if (n>=4 and std<=1.5 and abs(mean)<=4) else "C")
    return dict(bias=round(mean,2), n=n, std=round(std,2), tier=tier)

def parse_bucket(t):
    t = (t or "").strip()
    m = re.match(r"^(-?\d+)°[CF] or below$", t)
    if m: return (-999.0, float(m.group(1))+0.5)
    m = re.match(r"^(-?\d+)°[CF] or (higher|above)$", t)
    if m: return (float(m.group(1))-0.5, 999.0)
    m = re.match(r"^(-?\d+)°[CF]$", t)
    if m: return (float(m.group(1))-0.5, float(m.group(1))+0.5)
    m = re.match(r"^(-?\d+)-(-?\d+)°[CF]$", t)
    if m: return (float(m.group(1))-0.5, float(m.group(2))+0.5)
    return None

def bprob(members, lo, hi, unit, bias, sigma):
    if unit == "F":
        lo = f2c(lo) if lo > -900 else -999; hi = f2c(hi) if hi < 900 else 999
    tot = 0.0
    for x in members:
        xc = x + bias
        tot += (1.0 if hi > 900 else phi((hi-xc)/sigma)) - (0.0 if lo < -900 else phi((lo-xc)/sigma))
    return tot/len(members)

def fam_of(k):
    return "ec" if "ecmwf" in k else "ic" if "icon" in k else "gm" if "gem" in k else "gf"

BANKROLL = 100.0  # банкролл Дмитрия, $ — обновляется по мере роста счёта
DAY_LIMIT = 15.0  # дневной лимит, $ — фаза проверки модели; после 30 записанных ставок с подтверждённой точностью поднять до 25

def kelly_stake(p_base, p_cons, cost, bankroll=None, cap=None, frac=0.25, depth=None):
    """Рекомендуемый размер: четверть Келли по осторожной вероятности
    p_use = (базовая + стрессовая)/2 — чем шире расхождение при сдвиге поправки,
    тем меньше ставка. cost — цена за $1 выплаты (ask или сумма ask для комбо).
    0 = не ставить: осторожная оценка не даёт преимущества. Минимум сделки $1."""
    bankroll = BANKROLL if bankroll is None else bankroll
    cap = DAY_LIMIT if cap is None else cap
    if not (0 < cost < 1) or p_base is None: return 0.0
    p_use = p_base if p_cons is None else 0.5*(p_base + p_cons)
    b = (1-cost)/cost                      # выплата на $1 риска
    f = p_use - (1-p_use)/b                # доля Келли
    if f <= 0: return 0.0
    s = bankroll*f*frac
    if depth: s = min(s, depth)            # не больше, чем реально стоит в стакане
    s = min(s, cap)
    return 0.0 if s < 0.5 else round(max(s, 1.0), 2)

SLOPPY = []  # неэффективность книг: sum(ask) по городам
PARSE_FAIL = [0]  # счётчик нераспознанных бакетов (сигнал смены формата)
COMBOS = []  # «шанс-комбо»: наборы бакетов с повышенной вероятностью выигрыша

def chance_combos(rows, max_n=4, min_ev=0.15, min_p=0.40, max_cost=0.90):
    """«Шанс-комбо»: равные доли в 2-4 взаимоисключающих бакетах одного рынка.
    Платим sum(ask) за $1 выплаты, выигрываем если исход попал в набор.
    Жадный набор по ценности p/ask; шаг фиксируется при P>=min_p и EV>=min_ev.
    rows: [{bucket, p, pLo, pHi, ask}]. Возврат: лестница шагов (двойной, тройной...)."""
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

MIN_ORDER = 1.0   # минимальный размер ордера на Polymarket, $

def combo_lots(step, min_order=MIN_ORDER, thin_mult=1.5):
    """Исполнимые лоты комбо с учётом минимума $1 на ордер и реального стакана.
    Для каждой ноги набираем max(целевое число акций, минимум на $1), считая цену
    обходом книги. Нога отсеивается, если средняя цена выходит дороже thin_mult×аск
    (книга слишком тонкая) — покупать её невыгодно."""
    stake = step.get("stake") or 0
    target = (stake/step["cost"]) if step["cost"] else 0
    lots, skipped, total = [], [], 0.0
    for b, ask, tid, pp in zip(step["buckets"], step["asks"], step.get("tids", []), step.get("leg_p", [])):
        if not tid or not ask: skipped.append(dict(bucket=b, why="нет книги")); continue
        try:
            book = get(f"https://clob.polymarket.com/book?token_id={tid}")
            levels = sorted((float(a["price"]), float(a["size"])) for a in book.get("asks", []))
        except Exception:
            skipped.append(dict(bucket=b, why="книга недоступна")); continue
        need, sh, usd, lim = target, 0.0, 0.0, ask
        for price, size in levels:                       # добираем до целевого числа акций
            if sh >= need and usd >= min_order: break
            take = size if (sh + size < need or usd + price*size < min_order) else max(need - sh, (min_order - usd)/price)
            take = min(take, size)
            sh += take; usd += price*take; lim = price
        if usd < min_order or sh <= 0:
            skipped.append(dict(bucket=b, why="в книге нет объёма даже на $1")); continue
        eff = usd/sh
        if eff > thin_mult*ask:
            skipped.append(dict(bucket=b, why=f"тонкая книга: средняя {eff*100:.1f}¢ против аска {ask*100:.1f}¢")); continue
        lots.append(dict(bucket=b, ask=ask, limit=round(lim, 3), shares=round(sh, 1),
                         usd=round(usd, 2), payout=round(sh, 1), p=pp)); total += usd
    return dict(lots=lots, skipped=skipped, total_usd=round(total, 2),
                p_covered=round(sum(l["p"] for l in lots if l.get("p")), 3))

PM_WALLET = ""  # публичный адрес кошелька Polymarket (0x...); пустой = блок портфеля выключен.
                # В публичном репозитории всегда пусто — адрес живёт только в приватном тексте задачи.

def _bucket_of(title):
    m = re.search(r"(-?\d+(?:--?\d+)?°[CF](?: or (?:below|higher|above))?)", title or "")
    return m.group(1) if m else (title or "?")

def portfolio_scan(wallet=None):
    """Портфель через открытый data-api Polymarket (по публичному адресу, без ключей):
    открытые позиции, сгруппированные по событиям, с раскладом «что вернётся при каждом
    исходе»; потрачено сегодня и остаток дневного лимита; выплаты, готовые к забору."""
    wallet = wallet or PM_WALLET
    if not wallet: return None
    pos = get(f"https://data-api.polymarket.com/positions?user={wallet}")
    try: value = round(float(get(f"https://data-api.polymarket.com/value?user={wallet}")[0]["value"]), 2)
    except Exception: value = None
    open_ev, redeem = {}, []
    for p in pos:
        row = dict(bucket=_bucket_of(p.get("title")), outcome=p.get("outcome"),
                   shares=round(p.get("size", 0), 1), avg=round(p.get("avgPrice", 0), 3),
                   cur=round(p.get("curPrice", 0), 3), cost=round(p.get("initialValue", 0), 2),
                   payout=round(p.get("size", 0), 2))
        if p.get("redeemable"):
            won = round(p.get("currentValue", 0), 2)   # проигравшие акции стоят 0 — забирать нечего
            if won > 0.01:
                redeem.append(dict(row, payout=won, event=p.get("eventSlug"), pnl=round(p.get("cashPnl", 0), 2)))
        elif row["shares"] > 0.01:
            open_ev.setdefault(p.get("eventSlug"), []).append(row)
    events = []
    for slug, legs in open_ev.items():
        spent = round(sum(l["cost"] for l in legs), 2)
        # бакеты температуры и землетрясений взаимоисключающие; страйки крипты — НЕТ
        # (BTC выше 120k и выше 130k сыграют одновременно), там таблица исходов была бы ложной
        exclusive = bool(re.match(r"(highest|lowest)-temperature-|how-many-", slug or ""))
        scen = None
        if exclusive:
            scen = []
            for b in [l["bucket"] for l in legs] + ["любой другой исход"]:
                ret = sum(l["payout"] for l in legs
                          if (l["outcome"] == "Yes") == (l["bucket"] == b))
                scen.append(dict(если=b, чистыми=round(ret - spent, 2)))
        events.append(dict(event=slug, spent=spent, legs=legs, scenarios=scen))
    spent_today = 0.0
    try:
        midnight = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        for a in get(f"https://data-api.polymarket.com/activity?user={wallet}&limit=100"):
            if a.get("timestamp", 0) >= midnight and a.get("type") == "TRADE" and a.get("side") == "BUY":
                spent_today += float(a.get("usdcSize") or 0)
    except Exception: pass
    redeem.sort(key=lambda r: -r["payout"])
    return dict(value=value, spent_today=round(spent_today, 2),
                day_left=round(max(0.0, DAY_LIMIT - spent_today), 2),
                events=events, redeemable=redeem[:10], n_redeemable=len(redeem),
                redeem_total=round(sum(r["payout"] for r in redeem), 2))

def mark_held(picks, pf):
    """Флаги на пиках: held — такая позиция уже есть; conflict — уже держим противоположную."""
    if not pf: return
    have = {}
    for e in pf["events"]:
        for l in e["legs"]:
            have[(e["event"], l["bucket"])] = l["outcome"]
    for t in picks:
        slug_ev = t.get("link", "").rsplit("/", 1)[-1]
        o = have.get((slug_ev, t.get("bucket")))
        if o is None: continue
        if (o == "Yes") == (t.get("side") == "YES"): t["held"] = True
        else: t["conflict"] = True

def check_coverage():
    """Есть ли на Polymarket погодные города вне нашего списка (нужно ли обновлять HTML)."""
    try:
        d = get("https://gamma-api.polymarket.com/public-search?q=highest%20temperature&limit_per_type=100&events_status=active")
        seen = set()
        for e in d.get("events", []):
            m = re.match(r"highest-temperature-in-([a-z-]+)-on-", e.get("slug",""))
            if m: seen.add(m.group(1))
        low = get("https://gamma-api.polymarket.com/public-search?q=lowest%20temperature&limit_per_type=50&events_status=active")
        nlow = len({e.get("slug","") for e in low.get("events",[]) if e.get("slug","").startswith("lowest-temperature")})
        return dict(new_cities=sorted(seen - set(ST)), lowest_temp_markets=nlow)
    except Exception as e:
        return dict(new_cities=[], lowest_temp_markets=None, err=str(e)[:80])

def screen(slug, cal, dates, kind="max"):
    icao, lat, lon, unit, ru = ST[slug]
    if kind == "min": ru = ru + " (мин)" 
    q = urllib.parse.urlencode(dict(latitude=lat, longitude=lon, hourly="temperature_2m",
        models="ecmwf_ifs025,gfs025,icon_seamless,gem_global", timezone="auto",
        start_date=dates[0][1], end_date=dates[-1][1]))
    ens = get("https://ensemble-api.open-meteo.com/v1/ensemble?" + q)
    times = ens["hourly"]["time"]
    keys = [k for k in ens["hourly"] if k.startswith("temperature_2m")]
    trades = []
    for lead, ds in dates:
        d = datetime.strptime(ds, "%Y-%m-%d")
        prefix = "lowest" if kind == "min" else "highest"
        eslug = f"{prefix}-temperature-in-{slug}-on-{MONTHS[d.month-1]}-{d.day}-{d.year}"
        evs = get(f"https://gamma-api.polymarket.com/events?slug={eslug}")
        if not evs or evs[0].get("closed"): continue
        ev = evs[0]
        vol = float(ev.get("volume") or 0)
        allasks = [m.get("bestAsk") for m in ev["markets"] if parse_bucket(m.get("groupItemTitle"))]
        if len(allasks) >= 5 and all(a is not None for a in allasks):
            SLOPPY.append(dict(city=ru, date=ds, sum_ask=round(sum(allasks), 3), eslug=eslug))
        if vol < 10000: continue
        volpen = 1 if vol < 30000 else 0
        day = {"all": [], "ec": [], "gf": [], "ic": [], "gm": []}
        for k in keys:
            mx = daymax(times, ens["hourly"][k], ds, is_min=(kind == "min")).get(ds)
            if mx is None: continue
            day["all"].append(mx); day[fam_of(k)].append(mx)
        if len(day["all"]) < 20: continue
        sigma = 0.6 + 0.15*lead
        db = max(0.5, cal["std"] if cal["std"] is not None else 0.5)
        crows = []
        for m in ev["markets"]:
            rng = parse_bucket(m.get("groupItemTitle"))
            if not rng:
                if m.get("groupItemTitle"): PARSE_FAIL[0] += 1
                continue
            bb, ba = m.get("bestBid"), m.get("bestAsk")
            pr = m.get("outcomePrices")
            if isinstance(pr, str):
                try: pr = json.loads(pr)
                except Exception: pr = None
            mid = (bb+ba)/2 if (bb is not None and ba is not None) else (float(pr[0]) if pr else None)
            if mid is None: continue
            p = bprob(day["all"], *rng, unit, cal["bias"], sigma)
            pLo = bprob(day["all"], *rng, unit, cal["bias"]-db, sigma)
            pHi = bprob(day["all"], *rng, unit, cal["bias"]+db, sigma)
            fams = {f: round(bprob(day[f], *rng, unit, cal["bias"], sigma),3)
                    for f in ("ec","gf","ic","gm") if len(day[f]) >= 15}
            fv = list(fams.values())
            tid = None
            try:
                ti = m.get("clobTokenIds")
                ti = json.loads(ti) if isinstance(ti, str) else ti
                tid = ti[0] if ti else None
            except Exception: pass
            base = dict(city=ru, slug=slug, date=ds, lead=lead, bucket=m.get("groupItemTitle"),
                        p=round(p,3), mid=round(mid,3), fams=fams, vol=int(vol), tid=tid,
                        link=f"https://polymarket.com/event/{eslug}")
            crows.append(dict(bucket=m.get("groupItemTitle"), p=p, pLo=pLo, pHi=pHi, ask=ba, tid=tid, pmodel=p))
            if ba is not None and 0.02 <= ba <= 0.25 and p >= 2*ba and p >= 0.08:
                robust = pLo >= 1.5*ba and pHi >= 1.5*ba
                mn = min(fv) if fv else p
                agree = 1 if mn >= 0.5*p else (-1 if mn < 0.25*p else 0)
                spread = ba-bb if bb is not None else ba
                conf = 3 + (1 if robust else 0) + agree - (1 if spread > 0.08 else 0) - (1 if cal["n"] < 3 else 0) - volpen - (1 if lead >= 2 else 0)
                if cal["tier"] == "C": conf = min(conf, 2)
                trades.append(dict(base, side="YES", cost=ba, ev=round(p*(1/ba-1)-(1-p),2),
                                   conf=max(1,min(5,conf)), robust=robust,
                                   stake=kelly_stake(p, min(pLo, pHi), ba)))
            if bb is not None and mid >= 0.25 and (mid-p) >= 0.15:
                noask = 1-bb
                robust = (mid-pHi >= 0.10) and (mid-pLo >= 0.10)
                agr = all(mid-x >= 0.10 for x in fv); ref = any(x >= mid for x in fv)
                agree = 1 if agr else (-1 if ref else 0)
                conf = 3 + (1 if robust else 0) + agree - (1 if cal["n"] < 3 else 0) - volpen - (1 if lead >= 2 else 0)
                if cal["tier"] == "C": conf = min(conf, 2)
                trades.append(dict(base, side="NO", cost=round(noask,3), ev=round((1-p)*(1/noask-1)-p,2),
                                   conf=max(1,min(5,conf)), robust=robust,
                                   stake=kelly_stake(1-p, 1-max(pLo, pHi), noask)))
        for st in chance_combos(crows):
            COMBOS.append(dict(st, city=ru, date=ds, lead=lead, vol=int(vol), tier=cal["tier"],
                               link=f"https://polymarket.com/event/{eslug}"))
    return trades

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
    return phi((math.log(F/K) - 0.5*w)/s)

def crypto_scan():
    """Контур №3: рынки BTC/ETH above $K против риск-нейтральных вероятностей опционов."""
    now = datetime.now(timezone.utc)
    out = []
    for cur, pref in (("BTC","bitcoin"), ("ETH","ethereum")):
        try: surf = load_surface(cur)
        except Exception as e:
            out.append(dict(error=f"deribit {cur}: {str(e)[:60]}")); continue
        for dd in range(0, 8):
            d = now + timedelta(days=dd)
            slug = f"{pref}-above-on-{MONTHS[d.month-1]}-{d.day}-{d.year}"
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
    dates = [(1, (now+timedelta(days=1)).strftime("%Y-%m-%d")), (2, (now+timedelta(days=2)).strftime("%Y-%m-%d"))]
    calib, trades, errors = {}, [], []
    for slug in ST:
        try: calib[slug] = calibrate(slug)
        except Exception as e:
            calib[slug] = dict(bias=REF_BIAS.get(slug,0.0), n=0, std=None, tier="C")
            errors.append(f"calib {slug}: {e}")
    for slug in ST:
        try: trades += screen(slug, calib[slug], dates)
        except Exception as e: errors.append(f"screen {slug}: {e}")
    calib_min = {}
    for slug in MIN_SLUGS:
        try: calib_min[slug] = calibrate(slug, is_min=True)
        except Exception as e:
            calib_min[slug] = dict(bias=REF_BIAS_MIN.get(slug,0.0), n=0, std=None, tier="C")
            errors.append(f"calib_min {slug}: {e}")
    for slug in MIN_SLUGS:
        try: trades += screen(slug, calib_min[slug], dates, kind="min")
        except Exception as e: errors.append(f"screen_min {slug}: {e}")
    drift = {s: round(calib[s]["bias"]-REF_BIAS.get(s,0),2) for s in ST
             if calib[s]["n"] > 0 and abs(calib[s]["bias"]-REF_BIAS.get(s,0)) > 1.0}
    picks = sorted([t for t in trades if t["conf"] >= 4], key=lambda t: -t["conf"]*t["ev"])
    watch = [t for t in trades if t["conf"] == 3]
    # глубина стакана для топ-пиков: сколько $ реально доступно по цене входа (+-0.6c)
    for t in picks[:12]:
        t.pop("tid_checked", None)
        if not t.get("tid"): t["depth_usd"] = None; continue
        try:
            book = get(f"https://clob.polymarket.com/book?token_id={t['tid']}")
            usd = 0.0
            if t["side"] == "YES":
                lim = t["cost"] + 0.006
                for a in book.get("asks", []):
                    if float(a["price"]) <= lim: usd += float(a["price"])*float(a["size"])
            else:
                lim = (1 - t["cost"]) - 0.006
                for b in book.get("bids", []):
                    if float(b["price"]) >= lim: usd += (1-float(b["price"]))*float(b["size"])
            t["depth_usd"] = round(usd, 2)
            if t.get("stake"): t["stake"] = min(t["stake"], round(usd, 2))
        except Exception:
            t["depth_usd"] = None
    for t in trades: t.pop("tid", None)
    sloppy = sorted(SLOPPY, key=lambda x: x["sum_ask"])
    pure_arb = [x for x in sloppy if x["sum_ask"] < 0.99]
    seen_ct, combo_top = {}, []
    for c in sorted(COMBOS, key=lambda c: (-c["p_win"], -c["ev"])):
        k = (c["city"], c["date"])
        if seen_ct.get(k, 0) >= 2 or c["vol"] < 10000: continue
        seen_ct[k] = seen_ct.get(k, 0) + 1; combo_top.append(c)
    # серийная ставка дня: строгие критерии повторяемости
    series = next((c for c in sorted(combo_top, key=lambda c: -(c["p_win"]*c["ev"]))
                   if c["p_win"] >= 0.60 and c["ev"] >= 0.20 and c["tier"] in ("A", "B")
                   and (c["p_rng"][1]-c["p_rng"][0]) <= 0.25 and c["vol"] >= 15000), None)
    # чистый арбитраж: исполняемый объём по стаканам (лучший уровень ask каждого бакета)
    for x in pure_arb[:3]:
        try:
            evx = get(f"https://gamma-api.polymarket.com/events?slug={x['eslug']}")[0]
            sets, cost_eff = None, 0.0
            for m in evx["markets"]:
                if not parse_bucket(m.get("groupItemTitle")): continue
                ti = m.get("clobTokenIds"); ti = json.loads(ti) if isinstance(ti, str) else ti
                book = get(f"https://clob.polymarket.com/book?token_id={ti[0]}")
                asks = sorted((float(a["price"]), float(a["size"])) for a in book.get("asks", []))
                if not asks: sets = 0.0; break
                cost_eff += asks[0][0]
                sets = asks[0][1] if sets is None else min(sets, asks[0][1])
            x["exec_sets"] = int(sets or 0)
            x["exec_cost"] = round(cost_eff, 3)
            x["exec_profit"] = round(max(0.0, 1-cost_eff)*int(sets or 0), 2)
        except Exception as e:
            x["exec_err"] = str(e)[:60]
    # исполнимые лоты (минимум $1 на ордер + обход стакана) для серии и топ-комбо
    for c in combo_top[:6]:
        try: c["exec"] = combo_lots(c)
        except Exception as e: c["exec_err"] = str(e)[:60]
    if series is not None:
        series = next((c for c in combo_top if c is series or (c["city"] == series["city"] and c["date"] == series["date"] and c["buckets"] == series["buckets"])), series)
    for c in combo_top: c.pop("tids", None)
    try:
        portfolio = portfolio_scan()
        mark_held(picks, portfolio)
    except Exception as e:
        portfolio = None; errors.append(f"portfolio: {e}")
    try: quakes = quake_scan()
    except Exception as e:
        quakes = []; errors.append(f"quakes: {e}")
    try: crypto = crypto_scan()
    except Exception as e:
        crypto = []; errors.append(f"crypto: {e}")
    # «Вердикт дня»: по одной самой реальной ставке на категорию — или честный пропуск
    def wx_verdict(cs, ps):
        s = next((c for c in sorted(cs, key=lambda c: -(c["p_win"]*c["ev"]))
                  if c["p_win"] >= 0.60 and c["ev"] >= 0.20 and c["tier"] in ("A", "B")
                  and (c["p_rng"][1]-c["p_rng"][0]) <= 0.25 and c["vol"] >= 15000), None)
        if s: return dict(s, kind="серия-комбо")
        p = next((t for t in ps if t["conf"] >= 5 and t.get("robust")), None)
        if p: return dict({k: v for k, v in p.items() if k not in ("tid",)}, kind="одиночная")
        return None
    def ev_verdict(markets, want_arb_key=None):
        best = None
        for mkt in markets:
            if want_arb_key == "sum" and mkt.get("sum_ask") is not None and mkt["sum_ask"] < 0.99:
                return dict(kind="чистый арбитраж", market=mkt["title"], sum_ask=mkt["sum_ask"], link=mkt["link"])
            if want_arb_key == "arbs" and mkt.get("arbs"):
                return dict(kind="арбитраж-связка", market=mkt["title"], arbs=mkt["arbs"], link=mkt["link"])
            for pk in mkt.get("picks", []):
                if pk["conf"] >= 4 and (best is None or pk["ev"] > best["ev"]):
                    best = dict(pk, kind="одиночная", market=mkt["title"], link=mkt["link"])
        return best
    verdicts = dict(
        max=wx_verdict([c for c in combo_top if "(мин)" not in c["city"]], [t for t in picks if "(мин)" not in t["city"]]),
        min=wx_verdict([c for c in combo_top if "(мин)" in c["city"]], [t for t in picks if "(мин)" in t["city"]]),
        quakes=ev_verdict(quakes, "sum") or ev_verdict(quakes),
        crypto=ev_verdict(crypto, "arbs") or ev_verdict(crypto),
    )
    print(json.dumps(dict(
        generated=now.strftime("%Y-%m-%d %H:%M UTC"),
        bankroll=BANKROLL, day_limit=DAY_LIMIT, min_order=MIN_ORDER,
        portfolio=portfolio,
        verdicts=verdicts,
        calib_json=dict(cal_date=now.strftime("%Y-%m-%d"), cities=calib, cities_min=calib_min),
        picks=picks[:12], watch=watch[:10], chance_combos=combo_top[:10], series_pick=series,
        bias_drift_over_1C=drift, errors=errors,
        pure_arb=pure_arb, most_inefficient=sloppy[:5],
        html_health=dict(coverage=check_coverage(), parse_fails=PARSE_FAIL[0]),
        quakes=quakes, crypto=crypto,
    ), ensure_ascii=False, indent=1))

main()
