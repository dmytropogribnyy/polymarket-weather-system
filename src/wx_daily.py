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
REF_BIAS = {  # эталон: поправка ECMWF на горизонте 1 сутки (previous_day1), 2026-08-02
 "london":0.12,"paris":1.13,"milan":1.09,"munich":2.3,"madrid":0.33,"warsaw":-0.08,
 "amsterdam":1.28,"nyc":-0.53,"chicago":-1.23,"dallas":-1.99,"miami":1.61,"atlanta":0.64,
 "seattle":0.48,"toronto":0.06,"seoul":1.74,"tokyo":-1.89,"shanghai":0.07,"singapore":1.76,
 "wellington":0.75,"sao-paulo":0.39,"buenos-aires":0.68,"mexico-city":-0.46,"chongqing":2.48,
 "chengdu":0.0,"kuala-lumpur":1.15,"los-angeles":-7.8,"tel-aviv":-2.43,"beijing":0.8,
 "taipei":2.17,"helsinki":1.82,"lucknow":1.46,"jeddah":-1.54,"karachi":-1.38,"houston":-0.29,
 "ankara":0.56,"wuhan":2.46,"guangzhou":2.5,"denver":1.33,"istanbul":0.31,"qingdao":0.52,
 "cape-town":0.96,"manila":1.84,"austin":-0.56,"busan":-1.94,"shenzhen":0.84,
 "san-francisco":2.33,"moscow":-0.06}  # 2026-08-01, новые города 2026-08-02
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
    """Lead-matched калибровка по семействам моделей: прогноз, каким он был за 24ч и 48ч
    до дня (Previous Runs API, previous_day1/2), против факта METAR. Отдельные bias/std/SE
    каждому семейству — поправка ECMWF не переносится на GFS/ICON/GEM (урок Мюнхена 2 авг:
    ECMWF требовал +2.3°, ICON +0.3°, а мы прибавляли +2.5° всем)."""
    icao, lat, lon, unit, _ = ST[slug]
    if icao is None: return dict(fams={"1": {}, "2": {}}, tier="C", bias=0.0, std=None, n=0)
    now = datetime.now(timezone.utc)
    d = get("https://previous-runs-api.open-meteo.com/v1/forecast?"
            f"latitude={lat}&longitude={lon}"
            "&hourly=temperature_2m_previous_day1,temperature_2m_previous_day2"
            "&models=ecmwf_ifs025,gfs_global,icon_seamless,gem_global"  # gfs025 в previous-runs пуст — gfs_global
            "&timezone=auto&past_days=10&forecast_days=1")
    off = d.get("utc_offset_seconds", 0)
    obs = {}
    for o in get(f"https://aviationweather.gov/api/data/metar?ids={icao}&format=json&hours=336"):
        t, temp = o.get("reportTime"), o.get("temp")
        if t is None or temp is None: continue
        dt = datetime.fromisoformat(t.replace("Z","+00:00").replace(".000","")) + timedelta(seconds=off)
        k = dt.strftime("%Y-%m-%d")
        if k not in obs or (temp < obs[k] if is_min else temp > obs[k]): obs[k] = float(temp)
    today = now.strftime("%Y-%m-%d")
    cutoff = (now - timedelta(days=1)).strftime("%Y-%m-%d") if is_min else \
             (today if (now+timedelta(seconds=off)).hour >= 19 else \
              (now-timedelta(days=1)).strftime("%Y-%m-%d"))
    fams = {"1": {}, "2": {}}
    for k in d.get("hourly", {}):
        if k == "time": continue
        lead = "1" if "previous_day1" in k else "2"
        fam = fam_of(k)
        md = daymax(d["hourly"]["time"], d["hourly"][k], is_min=is_min)
        diffs = [obs[x]-md[x] for x in sorted(md) if x in obs and x <= cutoff]
        n = len(diffs)
        if n < 2: continue
        mean = sum(diffs)/n
        std = math.sqrt(sum((v-mean)**2 for v in diffs)/n)
        fams[lead][fam] = dict(bias=round(mean,2), std=round(std,2), n=n,
                               se=round(std/math.sqrt(n), 2))
    f1 = fams["1"]
    if len(f1) >= 2:
        wst = max(v["std"] for v in f1.values())
        mn = min(v["n"] for v in f1.values())
        mb = max(abs(v["bias"]) for v in f1.values())
        tier = "A" if (mn >= 6 and wst <= 0.9 and mb <= 4) else \
               ("B" if (mn >= 4 and wst <= 1.5 and mb <= 4) else "C")
    else:
        tier = "C"
    return dict(fams=fams, tier=tier,
                bias=f1.get("ec", {}).get("bias", 0.0),
                std=(round(max(v["std"] for v in f1.values()), 2) if f1 else None),
                n=(min(v["n"] for v in f1.values()) if f1 else 0))

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

def fee(a): return 0.05*a*(1-a)   # тейкер-комиссия Polymarket (погода), $/акцию — сверено с реальными сделками
def allin(a): return a + fee(a)    # полная цена входа за акцию

LAMBDA = 0.25    # вес СВОЕЙ модели в пуле с рынком на фазе валидации (совет внешней ревизии)
EPS_TICK = 0.001 # минимальный тик цены

def fam_prob(day, rng, unit, fcal, lead, dbias=0.0):
    """P(бакет): равный вес каждому семейству моделей; каждому члену — поправка ЕГО
    семейства. Ядро τ_f² = max(0.36, std_f² − разброс_ансамбля²): остаточная
    неопределённость сверх выраженной разбросом членов — без двойного счёта.
    dbias=±1 — стресс: сдвиг поправки каждого семейства на ±его SE (не на std!)."""
    lo, hi = rng
    if unit == "F":
        lo = f2c(lo) if lo > -900 else -999; hi = f2c(hi) if hi < 900 else 999
    fc = fcal.get(str(lead), {}) if fcal else {}
    avail = [f for f in ("ec","gf","ic","gm") if len(day.get(f) or []) >= 8]
    if not avail: return None, {}
    biases = [v["bias"] for v in fc.values()]
    fb = sum(biases)/len(biases) if biases else 0.0
    ps = {}
    for f in avail:
        xs = day[f]
        mu = sum(xs)/len(xs)
        s2 = sum((x-mu)**2 for x in xs)/len(xs)
        c = fc.get(f)
        b = (c["bias"] if c else fb) + dbias*((c["se"] if c else 0.5))
        tau = math.sqrt(max(0.36, (c["std"]**2 - s2)) if c else (0.6 + 0.15*lead)**2)
        tot = 0.0
        for x in xs:
            xc = x + b
            tot += (1.0 if hi > 900 else phi((hi-xc)/tau)) - (0.0 if lo < -900 else phi((lo-xc)/tau))
        ps[f] = tot/len(xs)
    p = sum(ps.values())/len(ps)
    return p, {k: round(v,3) for k,v in ps.items()}

def fam_of(k):
    return "ec" if "ecmwf" in k else "ic" if "icon" in k else "gm" if "gem" in k else "gf"

BANKROLL = 100.0  # банкролл Дмитрия, $ — обновляется по мере роста счёта
DAY_LIMIT = 15.0  # дневной лимит, $ — аварийный потолок
WEATHER_DAY_CAP = 5.0  # фаза валидации: суммарный потолок ПОГОДНЫХ входов одной даты (совет ревизии);
                       # после 30 записанных ставок с подтверждённой калибровкой поднять

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
    cost — сумма ПОЛНЫХ цен ног (аск + тейкер-комиссия). Фаза валидации: ноги
    дешевле 3¢ запрещены (переоценка дешёвых хвостов — главный подозреваемый ревизии).
    rows: [{bucket, p, pLo, pHi, ask}]. Возврат: лестница шагов (двойной, тройной...)."""
    cand = [r for r in rows if r.get("ask") and 0.03 <= r["ask"] <= 0.9 and r["p"] >= 0.03]
    cand.sort(key=lambda r: -r["p"]/allin(r["ask"]))   # ценность на ПОЛНЫЙ доллар (с комиссией)
    steps, S, cost, P, Plo, Phi = [], [], 0.0, 0.0, 0.0, 0.0
    for r in cand:
        if len(S) >= max_n: break
        ca = allin(r["ask"])
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
        for price, size in levels:                       # добираем до целевого числа акций; цена ПОЛНАЯ
            if sh >= need and usd >= min_order: break
            take = size if (sh + size < need or usd + allin(price)*size < min_order) else max(need - sh, (min_order - usd)/allin(price))
            take = min(take, size)
            sh += take; usd += allin(price)*take; lim = price
        if usd < min_order or sh <= 0:
            skipped.append(dict(bucket=b, why="в книге нет объёма даже на $1")); continue
        eff = usd/sh
        if eff > thin_mult*allin(ask):
            skipped.append(dict(bucket=b, why=f"тонкая книга: средняя {eff*100:.1f}¢ против аска {ask*100:.1f}¢")); continue
        lots.append(dict(bucket=b, ask=ask, limit=round(lim, 3), shares=round(sh, 1),
                         usd=round(usd, 2), payout=round(sh, 1), p=pp)); total += usd
    exp_pay = sum((l["p"] or 0)*l["payout"] for l in lots)
    return dict(lots=lots, skipped=skipped, total_usd=round(total, 2),
                p_covered=round(sum(l["p"] for l in lots if l.get("p")), 3),
                ev_final=(round(exp_pay/total - 1, 2) if total > 0.5 else None))

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
    spent_today, spent_wx = 0.0, 0.0
    try:
        midnight = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        for a in get(f"https://data-api.polymarket.com/activity?user={wallet}&limit=100"):
            if a.get("timestamp", 0) >= midnight and a.get("type") == "TRADE" and a.get("side") == "BUY":
                v = float(a.get("usdcSize") or 0)
                spent_today += v
                if "temperature" in (a.get("eventSlug") or ""): spent_wx += v
    except Exception: pass
    redeem.sort(key=lambda r: -r["payout"])
    return dict(value=value, spent_today=round(spent_today, 2),
                spent_today_weather=round(spent_wx, 2),
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

RES_FAILS = []  # fail-closed: рынки, не прошедшие проверку источника/единиц резолюции

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
        desc = ev.get("description") or ""
        if desc:  # fail-closed: единицы и источник резолюции должны совпадать с моделью
            um = re.search(r"degrees (Celsius|Fahrenheit)", desc)
            if um and um.group(1)[0] != unit:
                RES_FAILS.append(f"{eslug}: рынок в {um.group(1)}, наша модель в °{unit}"); continue
            if not any(x in desc for x in ("Wunderground", "NOAA", "National Weather Service")):
                RES_FAILS.append(f"{eslug}: неизвестный источник резолюции"); continue
        vol = float(ev.get("volume") or 0)
        allasks = [m.get("bestAsk") for m in ev["markets"] if parse_bucket(m.get("groupItemTitle"))]
        if len(allasks) >= 5 and all(a is not None for a in allasks):
            SLOPPY.append(dict(city=ru, date=ds, sum_ask=round(sum(allasks), 3),
                               sum_allin=round(sum(allin(a) for a in allasks), 3), eslug=eslug))
        if vol < 10000: continue
        volpen = 1 if vol < 30000 else 0
        day = {"all": [], "ec": [], "gf": [], "ic": [], "gm": []}
        for k in keys:
            mx = daymax(times, ens["hourly"][k], ds, is_min=(kind == "min")).get(ds)
            if mx is None: continue
            day["all"].append(mx); day[fam_of(k)].append(mx)
        if len(day["all"]) < 20: continue
        rows = []
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
            p_raw, fams_p = fam_prob(day, rng, unit, cal["fams"], lead)
            if p_raw is None: continue
            pLo_raw, _ = fam_prob(day, rng, unit, cal["fams"], lead, dbias=-1.0)
            pHi_raw, _ = fam_prob(day, rng, unit, cal["fams"], lead, dbias=+1.0)
            tid = None
            try:
                ti = m.get("clobTokenIds")
                ti = json.loads(ti) if isinstance(ti, str) else ti
                tid = ti[0] if ti else None
            except Exception: pass
            rows.append(dict(bucket=m.get("groupItemTitle"), bb=bb, ba=ba, mid=mid, tid=tid,
                             p=p_raw, pLo=pLo_raw, pHi=pHi_raw, fams=fams_p))
        if len(rows) < 3: continue
        # усадка к рынку: нормализованный лог-пул p^λ · q^(1−λ) по бакетам события
        qn = [max(r["mid"], EPS_TICK) for r in rows]
        qs = sum(qn); qn = [x/qs for x in qn]
        for key in ("p", "pLo", "pHi"):
            num = [(max(r[key], EPS_TICK)**LAMBDA)*(qq**(1-LAMBDA)) for r, qq in zip(rows, qn)]
            z = sum(num) or 1.0
            for r, v in zip(rows, num): r[key+"S"] = v/z
        crows = []
        for r in rows:
            bb, ba, mid = r["bb"], r["ba"], r["mid"]
            pS, pLoS, pHiS = r["pS"], r["pLoS"], r["pHiS"]
            fv = list(r["fams"].values())
            base = dict(city=ru, slug=slug, date=ds, lead=lead, bucket=r["bucket"],
                        p=round(pS,3), p_model=round(r["p"],3), mid=round(mid,3),
                        fams=r["fams"], vol=int(vol), tid=r["tid"],
                        link=f"https://polymarket.com/event/{eslug}")
            crows.append(dict(bucket=r["bucket"], p=pS, pLo=pLoS, pHi=pHiS, ask=ba,
                              tid=r["tid"], pmodel=r["p"]))
            if ba is not None:
                c = allin(ba)  # полная цена с тейкер-комиссией
                if 0.04 <= c <= 0.30 and pS >= 1.8*c and r["p"] >= 2*ba and pS >= 0.05:
                    robust = pLoS >= 1.4*c and pHiS >= 1.4*c
                    mn = min(fv) if fv else r["p"]
                    agree = 1 if mn >= 0.5*r["p"] else (-1 if mn < 0.25*r["p"] else 0)
                    spread = ba-bb if bb is not None else ba
                    conf = 3 + (1 if robust else 0) + agree - (1 if spread > 0.08 else 0) - volpen - (1 if lead >= 2 else 0)
                    if cal["tier"] == "C": conf = min(conf, 2)
                    trades.append(dict(base, side="YES", cost=round(c,3), ask=ba,
                                       ev=round(pS*(1/c-1)-(1-pS),2),
                                       conf=max(1,min(5,conf)), robust=robust,
                                       stake=kelly_stake(pS, min(pLoS, pHiS), c)))
            if bb is not None and mid >= 0.25 and (mid-pS) >= 0.12:
                c = allin(1-bb)
                robust = (mid-pHiS >= 0.08) and (mid-pLoS >= 0.08)
                agr = all(mid-x >= 0.10 for x in fv); ref = any(x >= mid for x in fv)
                agree = 1 if agr else (-1 if ref else 0)
                conf = 3 + (1 if robust else 0) + agree - volpen - (1 if lead >= 2 else 0)
                if cal["tier"] == "C": conf = min(conf, 2)
                trades.append(dict(base, side="NO", cost=round(c,3), ask=round(1-bb,3),
                                   ev=round((1-pS)*(1/c-1)-pS,2),
                                   conf=max(1,min(5,conf)), robust=robust,
                                   stake=kelly_stake(1-pS, 1-max(pLoS, pHiS), c)))
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
        ok_asks = len(qasks) >= 3 and all(a is not None for a in qasks)
        q_sum_ask = round(sum(qasks), 3) if ok_asks else None
        q_sum_allin = round(sum(allin(a) for a in qasks), 3) if ok_asks else None
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
                c = allin(ba)
                robust = pLo >= 1.5*c and pHi >= 1.5*c
                conf = max(1, min(5, 3 + (1 if robust else 0) - volpen))
                (picks if conf >= 4 else watch).append(dict(side="YES", bucket=m.get("groupItemTitle"), cost=round(c,3),
                    p=round(p,3), mid=round(mid,3), ev=round(p*(1/c-1)-(1-p),2), conf=conf,
                    stake=kelly_stake(p, min(pLo, pHi), c)))
            if bb is not None and mid >= 0.25 and (mid-p) >= 0.15:
                c = allin(1-bb)
                robust = (mid-pLo >= 0.10) and (mid-pHi >= 0.10)
                conf = max(1, min(5, 3 + (1 if robust else 0) - volpen))
                (picks if conf >= 4 else watch).append(dict(side="NO", bucket=m.get("groupItemTitle"), cost=round(c,3),
                    p=round(p,3), mid=round(mid,3), ev=round((1-p)*(1/c-1)-p,2), conf=conf,
                    stake=kelly_stake(1-p, 1-max(pLo, pHi), c)))
        out.append(dict(title=full["title"], n_obs=n_obs, borderline=borderline, t_rem_days=round(t_rem,1),
                        lam_rem=round(lam,2), vol=int(vol), picks=picks, watch=watch[:4],
                        combos=chance_combos(qrows)[-2:] if vol >= 500 else [], sum_ask=q_sum_ask, sum_allin=q_sum_allin,
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
                if 0.03 <= ba <= 0.25 and p >= 2*ba and p >= 0.08:
                    c = allin(ba)
                    conf = max(1, min(5, 3 + (1 if lo >= 1.5*c else 0) - volpen))
                    (picks if conf >= 4 else watch).append(dict(row, side="YES", cost=round(c,3),
                        ev=round(p*(1/c-1)-(1-p),2), conf=conf, stake=kelly_stake(p, lo, c)))
                if mid >= 0.25 and (mid-p) >= 0.15:
                    c = allin(1-bb)
                    conf = max(1, min(5, 3 + (1 if (mid-hi) >= 0.10 else 0) - volpen))
                    (picks if conf >= 4 else watch).append(dict(row, side="NO", cost=round(c,3),
                        ev=round((1-p)*(1/c-1)-p,2), conf=conf, stake=kelly_stake(1-p, 1-hi, c)))
                if ba > 0.25 and (p-mid) >= 0.15:
                    c = allin(ba)
                    conf = max(1, min(5, 3 + (1 if (lo-mid) >= 0.10 else 0) - volpen))
                    (picks if conf >= 4 else watch).append(dict(row, side="YES", cost=round(c,3),
                        ev=round(p*(1/c-1)-(1-p),2), conf=conf, stake=kelly_stake(p, lo, c)))
            arbs = []
            for (k1, b1, a1), (k2, b2, a2) in zip(sorted(klist), sorted(klist)[1:]):
                c = allin(a1) + allin(1 - b2)   # полные цены обеих ног
                if c < 0.99:
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
            calib[slug] = dict(fams={"1": {}, "2": {}}, bias=REF_BIAS.get(slug,0.0), n=0, std=None, tier="C")
            errors.append(f"calib {slug}: {e}")
    for slug in ST:
        try: trades += screen(slug, calib[slug], dates)
        except Exception as e: errors.append(f"screen {slug}: {e}")
    calib_min = {}
    for slug in MIN_SLUGS:
        try: calib_min[slug] = calibrate(slug, is_min=True)
        except Exception as e:
            calib_min[slug] = dict(fams={"1": {}, "2": {}}, bias=REF_BIAS_MIN.get(slug,0.0), n=0, std=None, tier="C")
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
    sloppy = sorted(SLOPPY, key=lambda x: x.get("sum_allin", x["sum_ask"]))
    pure_arb = [x for x in sloppy if x.get("sum_allin", 1) < 0.995]   # с учётом комиссий
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
                cost_eff += allin(asks[0][0])
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
            if want_arb_key == "sum" and mkt.get("sum_allin") is not None and mkt["sum_allin"] < 0.995:
                return dict(kind="чистый арбитраж", market=mkt["title"], sum_ask=mkt["sum_ask"], sum_allin=mkt["sum_allin"], link=mkt["link"])
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
    # бюджет дня в коде: $15 общий, $5 на погодные входы одной даты (фаза валидации)
    spent = portfolio["spent_today"] if portfolio else 0.0
    spent_wx = (portfolio or {}).get("spent_today_weather", 0.0)
    budget = dict(day_limit=DAY_LIMIT, weather_cap=WEATHER_DAY_CAP,
                  spent_today=round(spent, 2), spent_today_weather=round(spent_wx, 2),
                  day_left=round(max(0.0, DAY_LIMIT - spent), 2),
                  weather_left=round(max(0.0, WEATHER_DAY_CAP - spent_wx), 2))
    for v in (verdicts.get("max"), verdicts.get("min")):
        if v and v.get("stake"): v["stake"] = min(v["stake"], budget["weather_left"])
    if series is not None and series.get("stake"):
        series["stake"] = min(series["stake"], budget["weather_left"])
    print(json.dumps(dict(
        generated=now.strftime("%Y-%m-%d %H:%M UTC"),
        bankroll=BANKROLL, day_limit=DAY_LIMIT, min_order=MIN_ORDER,
        budget=budget, portfolio=portfolio,
        model_policy=dict(lambda_model=LAMBDA, fee="тейкер 0.05·цена·(1−цена) с акции",
                          min_leg_ask=0.03, note="фаза валидации: усадка к рынку, дешёвые хвосты запрещены"),
        res_checks=RES_FAILS,
        verdicts=verdicts,
        calib_json=dict(cal_date=now.strftime("%Y-%m-%d"), cities=calib, cities_min=calib_min),
        picks=picks[:12], watch=watch[:10], chance_combos=combo_top[:10], series_pick=series,
        bias_drift_over_1C=drift, errors=errors,
        pure_arb=pure_arb, most_inefficient=sloppy[:5],
        html_health=dict(coverage=check_coverage(), parse_fails=PARSE_FAIL[0]),
        quakes=quakes, crypto=crypto,
    ), ensure_ascii=False, indent=1))

if __name__ == "__main__":   # импорт модуля тестами не должен ходить в сеть
    main()
