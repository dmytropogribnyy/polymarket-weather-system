#!/usr/bin/env python3
"""Daily Polymarket weather job: recalibrate stations -> screen tomorrow &
day-after -> print JSON report. Self-contained, stdlib only."""
import hashlib, json, math, re, time, urllib.request, urllib.parse
from collections import namedtuple
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP

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

def tier_of(fams_lead):
    """Тир доверия по ОДНОМУ горизонту: считается по худшему семейству."""
    if len(fams_lead) < 2: return "C"
    wst = max(v["std"] for v in fams_lead.values())
    mn = min(v["n"] for v in fams_lead.values())
    mb = max(abs(v["bias"]) for v in fams_lead.values())
    if mn >= 6 and wst <= 0.9 and mb <= 4: return "A"
    if mn >= 4 and wst <= 1.5 and mb <= 4: return "B"
    return "C"

def cal_tier(cal, lead):
    """Тир ТОГО горизонта, на котором реально торгуем (1 или 2 суток).
    Горизонты калибруются раздельно, и тир суточного прогноза не даёт права
    торговать двухсуточный."""
    tiers = (cal or {}).get("tiers") or {}
    return tiers.get(str(lead), "C")

def hist_spread2(lat, lon, is_min, cutoff, fetch=None):
    """Средний ИСТОРИЧЕСКИЙ разброс ансамбля по семействам в окне калибровки:
    для каждого прошедшего дня — дисперсия дневных экстремумов членов семейства,
    усреднённая по дням окна. Именно она вычитается из std_f² (см. fam_prob),
    а не разброс сегодняшнего прогноза."""
    q = urllib.parse.urlencode(dict(latitude=lat, longitude=lon, hourly="temperature_2m",
        models="ecmwf_ifs025,gfs025,icon_seamless,gem_global", timezone="auto",
        past_days=10, forecast_days=1))
    ens = (fetch or get)("https://ensemble-api.open-meteo.com/v1/ensemble?" + q)
    times = ens["hourly"]["time"]
    per_fam = {}
    for k in ens["hourly"]:
        if not k.startswith("temperature_2m"): continue
        md = daymax(times, ens["hourly"][k], is_min=is_min)
        for day, v in md.items():
            if day > cutoff: continue
            per_fam.setdefault(fam_of(k), {}).setdefault(day, []).append(v)
    out = {}
    for fam, days in per_fam.items():
        var = []
        for vals in days.values():
            if len(vals) < 8: continue
            mu = sum(vals)/len(vals)
            var.append(sum((x-mu)**2 for x in vals)/len(vals))
        if var: out[fam] = round(sum(var)/len(var), 4)
    return out

def calibrate(slug, is_min=False, fetch=None):
    """Lead-matched калибровка по семействам моделей: прогноз, каким он был за 24ч и 48ч
    до дня (Previous Runs API, previous_day1/2), против факта METAR. Отдельные bias/std/SE
    каждому семейству — поправка ECMWF не переносится на GFS/ICON/GEM (урок Мюнхена 2 авг:
    ECMWF требовал +2.3°, ICON +0.3°, а мы прибавляли +2.5° всем). Тир считается
    ОТДЕЛЬНО для каждого горизонта; в окне калибровки же меряется средний разброс
    ансамбля (`spread2`) — его вычитает fam_prob."""
    fetch = fetch or get
    icao, lat, lon, unit, _ = ST[slug]
    if icao is None:
        return dict(fams={"1": {}, "2": {}}, tiers={"1": "C", "2": "C"}, tier="C",
                    bias=0.0, std=None, n=0)
    now = datetime.now(timezone.utc)
    d = fetch("https://previous-runs-api.open-meteo.com/v1/forecast?"
              f"latitude={lat}&longitude={lon}"
              "&hourly=temperature_2m_previous_day1,temperature_2m_previous_day2"
              "&models=ecmwf_ifs025,gfs_global,icon_seamless,gem_global"  # gfs025 в previous-runs пуст — gfs_global
              "&timezone=auto&past_days=10&forecast_days=1")
    off = d.get("utc_offset_seconds", 0)
    obs = {}
    for o in fetch(f"https://aviationweather.gov/api/data/metar?ids={icao}&format=json&hours=336"):
        t, temp = o.get("reportTime"), o.get("temp")
        if t is None or temp is None: continue
        dt = datetime.fromisoformat(t.replace("Z","+00:00").replace(".000","")) + timedelta(seconds=off)
        k = dt.strftime("%Y-%m-%d")
        if k not in obs or (temp < obs[k] if is_min else temp > obs[k]): obs[k] = float(temp)
    today = now.strftime("%Y-%m-%d")
    cutoff = (now - timedelta(days=1)).strftime("%Y-%m-%d") if is_min else \
             (today if (now+timedelta(seconds=off)).hour >= 19 else \
              (now-timedelta(days=1)).strftime("%Y-%m-%d"))
    try: spreads = hist_spread2(lat, lon, is_min, cutoff, fetch)
    except Exception: spreads = {}
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
                               se=round(std/math.sqrt(n), 2), spread2=spreads.get(fam))
    tiers = {lead: tier_of(fams[lead]) for lead in ("1", "2")}
    f1 = fams["1"]
    return dict(fams=fams, tiers=tiers, tier=tiers["1"],
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

def fee(price, mp):
    """Комиссия тейкера, $/акцию. Ставка НЕ константа: она берётся из
    параметров конкретного рынка (`MarketParams`), поэтому погода и крипта
    больше не делят один зашитый множитель."""
    return mp.fee_rate*price*(1-price)

def allin(price, mp):
    """Полная цена входа за акцию: цена + комиссия конкретного рынка."""
    return price + fee(price, mp)

# ---------- торговые параметры КОНКРЕТНОГО рынка (fail-closed) ----------
# min_notional — минимальный размер ордера в USDC (Gamma `orderMinSize`);
# min_shares   — минимальное число акций за ордер (CLOB `minimum_order_size`).
# Эти два ограничения из РАЗНЫХ источников, нельзя подменять одно другим.
MarketParams = namedtuple("MarketParams", "fee_rate tick min_notional min_shares source")

FEE_RATE_MAX = 0.20    # санитарный потолок ставки комиссии
TICK_MAX = 0.10        # шаг цены крупнее 10¢ — данные битые
MIN_ORDER_MAX = 100.0  # минимальный ордер дороже $100 — данные битые
CLOB_MARKET_URL = "https://clob.polymarket.com/markets/"

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
    if fees_enabled is None:
        return None, False
    if not fees_enabled:
        return 0.0, True                     # явно отключено — ноль валиден
    schedule = m.get("feeSchedule") or {}
    rate = _num(schedule, "rate")
    if rate is None:
        return None, True                    # включено, но rate отсутствует
    # Проверяем exponent: если присутствует, обязан быть 2 (квадратичная кривая)
    exponent = schedule.get("exponent")
    if exponent is not None and exponent != 2:
        return None, True                    # неподдерживаемый exponent
    # Проверяем takerOnly: если присутствует, обязан быть True
    taker_only = schedule.get("takerOnly")
    if taker_only is not None and not taker_only:
        return None, True                    # takerOnly=False не поддерживается
    return float(rate), True

def parse_market_params(m):
    """Комиссия / шаг цены / нотионал КОНКРЕТНОГО рынка (Gamma-данные).
    Ничего не угадываем и ничего не подставляем по умолчанию: нет поля или
    значение вне санитарных границ — None, и рынок не торгуется (fail-closed).

    Комиссия: сначала каноническое поле feesEnabled + feeSchedule.rate;
    при его отсутствии — устаревший taker_base_fee (>1 → б.п., иначе доля).
    Конфликт канонического и устаревшего значений → None (fail-closed).

    min_notional — USDC-нотионал (Gamma `orderMinSize`); min_shares=0.0 —
    заполняется отдельно из CLOB в `market_params` и не смешивается с нотионалом."""
    if not isinstance(m, dict): return None
    canonical_rate, is_canonical = _fee_rate_canonical(m)
    if is_canonical:
        if canonical_rate is None:
            return None                      # feesEnabled=True, но расписания нет
        legacy = _fee_rate(_num(m, "taker_base_fee", "takerBaseFee", "tbf",
                                "feeRateBps", "fee_rate_bps"))
        if legacy is not None and abs(legacy - canonical_rate) > 1e-9:
            return None                      # канонический и устаревший конфликтуют
        fee_rate = canonical_rate
    else:
        fee_rate = _fee_rate(_num(m, "taker_base_fee", "takerBaseFee", "tbf",
                                  "feeRateBps", "fee_rate_bps"))
    tick = _num(m, "minimum_tick_size", "orderPriceMinTickSize", "mts", "tickSize")
    # min_notional — Gamma USDC-нотионал; min_shares заполняется из CLOB отдельно
    min_notional = _num(m, "orderMinSize", "minimum_order_size", "mos", "minimumOrderSize")
    if fee_rate is None or tick is None or min_notional is None: return None
    if not (0.0 <= fee_rate <= FEE_RATE_MAX): return None
    if not (0.0 < tick <= TICK_MAX): return None
    if not (0.0 < min_notional <= MIN_ORDER_MAX): return None
    return MarketParams(fee_rate=fee_rate, tick=tick, min_notional=min_notional,
                        min_shares=0.0, source="market")

def market_params(m, fetch=None):
    """Параметры рынка: нотионал (USDC) и шаг/комиссия из Gamma;
    min_shares (акции) из CLOB по conditionId.
    Два ограничения — из разных источников, смешивать нельзя.
    Не удалось получить обязательные поля — None (сделки нет)."""
    p = parse_market_params(m)
    if p is None:
        # Gamma не дала полных параметров; пробуем CLOB для fee/tick.
        # min_notional обязан прийти из Gamma — из CLOB его не берём.
        gamma_notional = _num(m, "orderMinSize", "minimum_order_size", "mos", "minimumOrderSize")
        if gamma_notional is None or not (0.0 < gamma_notional <= MIN_ORDER_MAX):
            return None
        cid = (m or {}).get("conditionId") or (m or {}).get("condition_id")
        if not cid: return None
        try: raw = (fetch or get)(CLOB_MARKET_URL + str(cid))
        except Exception: return None
        if not isinstance(raw, dict): return None
        canonical_rate, is_canonical = _fee_rate_canonical(m)
        if is_canonical:
            fee_rate = canonical_rate
        else:
            fee_rate = _fee_rate(_num(raw, "taker_base_fee", "takerBaseFee")) or \
                       _fee_rate(_num(m, "taker_base_fee", "takerBaseFee"))
        tick = _num(raw, "minimum_tick_size", "orderPriceMinTickSize") or \
               _num(m, "minimum_tick_size", "orderPriceMinTickSize")
        if fee_rate is None or tick is None: return None
        if not (0.0 <= fee_rate <= FEE_RATE_MAX): return None
        if not (0.0 < tick <= TICK_MAX): return None
        # CLOB minimum_order_size — это акции (shares), не нотионал
        clob_shares = _num(raw, "minimum_order_size", "min_order_size") or 0.0
        p = MarketParams(fee_rate=fee_rate, tick=tick, min_notional=gamma_notional,
                         min_shares=clob_shares, source="clob")
    else:
        # Gamma дала полный набор; дополняем min_shares из CLOB если доступен
        cid = (m or {}).get("conditionId") or (m or {}).get("condition_id")
        if cid:
            try:
                raw = (fetch or get)(CLOB_MARKET_URL + str(cid))
                if isinstance(raw, dict):
                    clob_shares = _num(raw, "minimum_order_size", "min_order_size") or 0.0
                    if clob_shares > p.min_shares:
                        p = p._replace(min_shares=clob_shares)
            except Exception:
                pass  # CLOB min_shares дополнительный; Gamma-параметры уже получены
    return p

def event_params(markets, fetch=None):
    """Параметры события: строгий режим — параметры обязаны быть у КАЖДОГО
    торгуемого бакета, иначе None. При расхождении берём худший вариант
    (дороже комиссия, крупнее шаг, нотионал и число акций)."""
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

LAMBDA = 0.25    # вес СВОЕЙ модели в пуле с рынком на фазе валидации (совет внешней ревизии)
EPS_TICK = 0.001 # минимальный тик цены

def fam_prob(day, rng, unit, fcal, lead, dbias=0.0):
    """P(бакет): равный вес каждому семейству моделей; каждому члену — поправка ЕГО
    семейства. Ядро τ_f² = max(0.36, std_f² − СРЕДНИЙ ИСТОРИЧЕСКИЙ разброс ансамбля
    того же семейства в окне калибровки). Вычитать разброс СЕГОДНЯШНЕГО прогноза
    нельзя: std_f измерен на окне калибровки, и вычитание из него дисперсии другого
    дня даёт то шире, то уже ядро без всякого основания (широкий сегодняшний
    ансамбль механически сжимал бы ядро — ровно наоборот здравому смыслу).
    Нет исторического разброса — не вычитаем ничего (консервативно, ядро шире).
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
        c = fc.get(f)
        b = (c["bias"] if c else fb) + dbias*((c["se"] if c else 0.5))
        if c:
            hist_spread2 = c.get("spread2")
            resid = c["std"]**2 - (hist_spread2 if hist_spread2 is not None else 0.0)
            tau = math.sqrt(max(0.36, resid))
        else:
            tau = 0.6 + 0.15*lead
        tot = 0.0
        for x in xs:
            xc = x + b
            tot += (1.0 if hi > 900 else phi((hi-xc)/tau)) - (0.0 if lo < -900 else phi((lo-xc)/tau))
        ps[f] = tot/len(xs)
    p = sum(ps.values())/len(ps)
    return p, {k: round(v,3) for k,v in ps.items()}

def log_pool(rows):
    """Усадка к рынку: нормализованный лог-пул p^λ·q^(1−λ) по ПОЛНОМУ набору
    взаимоисключающих бакетов. Вызывать только после coverage_ok: нормировать
    неполный поднабор к единице — значит выдумать вероятность.
    rows: [{p,pLo,pHi,mid}] -> [{p,pLo,pHi}]."""
    qn = [max(r["mid"], EPS_TICK) for r in rows]
    qs = sum(qn) or 1.0
    qn = [x/qs for x in qn]
    out = [dict() for _ in rows]
    for key in ("p", "pLo", "pHi"):
        num = [(max(r[key], EPS_TICK)**LAMBDA)*(qq**(1-LAMBDA)) for r, qq in zip(rows, qn)]
        z = sum(num) or 1.0
        for o, v in zip(out, num): o[key] = v/z
    return out

def fam_of(k):
    return "ec" if "ecmwf" in k else "ic" if "icon" in k else "gm" if "gem" in k else "gf"

BANKROLL = 100.0  # банкролл Дмитрия, $ — обновляется по мере роста счёта
DAY_LIMIT = 15.0  # дневной лимит, $ — аварийный потолок
WEATHER_DAY_CAP = 5.0  # фаза валидации: суммарный потолок ПОГОДНЫХ входов одной даты (совет ревизии);
                       # после 30 записанных ставок с подтверждённой калибровкой поднять
MIN_ORDER = 1.0   # запасной минимум ордера, $ — реальный берётся из параметров рынка

CENT = Decimal("0.01")

def _cents(x, rounding=ROUND_HALF_UP):
    return Decimal(str(x)).quantize(CENT, rounding=rounding)

WX_SLUG_RE = re.compile(r"^(?:highest|lowest)-temperature-in-[a-z0-9-]+-on-([a-z]+)-(\d{1,2})-(\d{4})$")

def weather_date_of_slug(slug):
    """Дата РЕЗОЛЮЦИИ (день погоды) из слага события. Именно она — ключ бюджета:
    ставки на один и тот же день погоды делят один потолок, даже если куплены
    в разные UTC-даты."""
    m = WX_SLUG_RE.match((slug or "").strip().lower())
    if not m: return None
    try: mon = MONTHS.index(m.group(1)) + 1
    except ValueError: return None
    try: return datetime(int(m.group(3)), mon, int(m.group(2))).strftime("%Y-%m-%d")
    except ValueError: return None

class BudgetAllocator:
    """ЕДИНЫЙ распределитель погодного бюджета на прогон.

    * ключ — дата резолюции (день погоды), не UTC-дата сделки;
    * максимумы, минимумы, серия и одиночные рекомендации ходят в ОДИН
      экземпляр: остаток нельзя потратить дважды;
    * уже исполненные позиции (`spent_by_date`) и уже выданные в этом прогоне
      рекомендации (`reserved`) вычитаются из потолка;
    * сверх погодного потолка действует общий дневной лимит;
    * дата неизвестна — остаток 0 (fail-closed).
    """

    def __init__(self, day_limit=None, weather_cap=None, spent_total=0.0,
                 spent_by_date=None, min_order=MIN_ORDER):
        self.day_limit = DAY_LIMIT if day_limit is None else float(day_limit)
        self.weather_cap = WEATHER_DAY_CAP if weather_cap is None else float(weather_cap)
        self.spent_total = _cents(spent_total or 0.0)
        self.spent_by_date = {k: _cents(v) for k, v in (spent_by_date or {}).items()}
        self.min_notional = float(min_order)   # минимальный резервируемый USDC за одну рекомендацию
        self.reserved_by_date = {}
        self.reservations = []

    @property
    def reserved_total(self):
        return sum(self.reserved_by_date.values(), Decimal("0"))

    def used(self, wdate):
        return self.spent_by_date.get(wdate, Decimal("0")) + self.reserved_by_date.get(wdate, Decimal("0"))

    def day_left(self):
        return max(Decimal("0"), _cents(self.day_limit) - self.spent_total - self.reserved_total)

    def remaining(self, wdate):
        """Остаток, доступный рекомендации на эту дату погоды, $."""
        if not wdate: return 0.0
        left_date = max(Decimal("0"), _cents(self.weather_cap) - self.used(wdate))
        return float(min(left_date, self.day_left()))

    def reserve(self, wdate, amount, tag=None):
        """Зарезервировать деньги под рекомендацию. Возвращает выданную сумму:
        0, если остатка не хватает даже на минимальный ордер."""
        want = _cents(max(0.0, float(amount or 0.0)), rounding=ROUND_DOWN)
        left = _cents(self.remaining(wdate), rounding=ROUND_DOWN)
        granted = min(want, left)
        if granted < _cents(self.min_notional):
            return 0.0
        self.reserved_by_date[wdate] = self.reserved_by_date.get(wdate, Decimal("0")) + granted
        self.reservations.append(dict(date=wdate, usd=float(granted), tag=tag))
        return float(granted)

    def snapshot(self):
        dates = sorted(set(self.spent_by_date) | set(self.reserved_by_date))
        return dict(day_limit=self.day_limit, weather_cap=self.weather_cap,
                    spent_today=float(self.spent_total),
                    day_left=float(self.day_left()),
                    by_weather_date={d: dict(spent=float(self.spent_by_date.get(d, Decimal("0"))),
                                             allocated=float(self.reserved_by_date.get(d, Decimal("0"))),
                                             left=self.remaining(d)) for d in dates},
                    allocations=list(self.reservations))

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

def chance_combos(rows, mp, max_n=4, min_ev=0.15, min_p=0.40, max_cost=0.90):
    """«Шанс-комбо»: равные доли в 2-4 взаимоисключающих бакетах одного рынка.
    cost — сумма ПОЛНЫХ цен ног (аск + комиссия ЭТОГО рынка). Фаза валидации: ноги
    дешевле 3¢ запрещены (переоценка дешёвых хвостов — главный подозреваемый ревизии).
    rows: [{bucket, p, pLo, pHi, ask}]. Возврат: лестница шагов (двойной, тройной...)."""
    cand = [r for r in rows if r.get("ask") and 0.03 <= r["ask"] <= 0.9 and r["p"] >= 0.03]
    cand.sort(key=lambda r: -r["p"]/allin(r["ask"], mp))   # ценность на ПОЛНЫЙ доллар (с комиссией)
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

COMBO_MIN_EV = 0.10   # порог EV после расчёта исполнимых лотов (с комиссиями)
COMBO_MIN_LEGS = 2    # комбо из одной ноги — не комбо

def _walk_book(levels, mp, target_shares, usd_cap):
    """Обход книги в Decimal: набираем до target_shares акций, но не меньше
    минимального нотионала и минимального числа акций рынка, и не дороже usd_cap.
    Возврат (shares, usd, limit_price) или None, если минимум не набирается.
    Деньги считаются десятичными дробями: нога ровно на $1.00 обязана пройти —
    двоичная 0.9999999999999999 не должна её отбраковывать."""
    min_notional = _cents(mp.min_notional)
    cap = _cents(usd_cap, rounding=ROUND_DOWN)
    if cap < min_notional: return None
    # Минимальное число акций — бо́льшее из требования рынка (CLOB) и целевого числа
    want_sh = Decimal(str(max(target_shares, mp.min_shares)))
    sh, usd, lim = Decimal("0"), Decimal("0"), None
    for price, size in levels:
        p = Decimal(str(price)); size = Decimal(str(size))
        if p <= 0 or size <= 0: continue
        a = p + Decimal(str(mp.fee_rate))*p*(1-p)     # полная цена акции
        if a <= 0: continue
        take = max(want_sh - sh, Decimal("0"))
        if usd < min_notional:                         # USDC-нотионал — обязателен
            take = max(take, (min_notional - usd)/a)
        if take <= 0: break
        take = min(take, size)
        if usd + a*take > cap:                         # бюджет ноги не превышаем
            take = (cap - usd)/a
            if take <= 0: break
        sh += take; usd += a*take; lim = price
        if sh >= want_sh and usd >= min_notional: break
    if sh <= 0 or _cents(usd) < min_notional: return None
    return sh, usd, lim

def combo_lots(step, mp, budget_left, fetch=None, thin_mult=1.5):
    """Исполнимые лоты комбо. Порядок жёсткий и именно такой:

    1. по каждой ноге считаем МИНИМАЛЬНЫЙ исполнимый лот по правилам рынка
       (минимальный ордер, минимальное число акций, обход книги, комиссии);
       ОБЯЗАТЕЛЬНО читаем min_order_size и tick_size из ФАКТИЧЕСКОГО ответа книги;
    2. тонкие ноги (средняя цена дороже thin_mult×аска) выбрасываем;
    3. если минимальных лотов меньше двух — НЕ СТАВИМ;
    4. если сумма минимальных лотов больше запрошенной ставки или больше
       остатка общего бюджета — НЕ СТАВИМ (никакого «добьём как получится»);
    5. и только потом добираем до целевого числа акций внутри потолка
       min(ставка, остаток бюджета).

    Итог: exec.total_usd никогда не превышает ни ставку, ни остаток бюджета."""
    fetch = fetch or get
    stake = float(step.get("stake") or 0.0)
    budget_left = float(budget_left or 0.0)
    cap = _cents(min(stake, budget_left), rounding=ROUND_DOWN)
    target = (stake/step["cost"]) if step.get("cost") else 0.0
    if cap < _cents(mp.min_notional)*COMBO_MIN_LEGS:
        return dict(lots=[], skipped=[], total_usd=0.0, min_usd=None, p_covered=0.0,
                    ev_final=None, stake=round(stake, 2), budget_left=round(budget_left, 2),
                    ok=False, reason=(f"доступно ${float(cap):.2f} — меньше {COMBO_MIN_LEGS} "
                                     f"минимальных ордеров по ${mp.min_notional:g}"))
    legs, skipped = [], []
    for b, ask, tid, pp in zip(step["buckets"], step["asks"], step.get("tids", []), step.get("leg_p", [])):
        if not tid or not ask:
            skipped.append(dict(bucket=b, why="нет книги")); continue
        try:
            book = fetch(f"https://clob.polymarket.com/book?token_id={tid}")
            levels = sorted((float(a["price"]), float(a["size"])) for a in book.get("asks", []))
            # Читаем ОБЯЗАТЕЛЬНЫЕ метаданные из фактической книги
            book_min_shares = _num(book, "min_order_size", "minimum_order_size")
            book_tick = _num(book, "tick_size", "minimum_tick_size")
            if book_min_shares is None or book_tick is None:
                skipped.append(dict(bucket=b, why="книга не содержит обязательные метаданные (min_order_size/tick_size)"))
                continue
            # Валидируем метаданные
            if book_min_shares < 0 or book_min_shares > 10000:
                skipped.append(dict(bucket=b, why=f"книга: min_order_size={book_min_shares} вне санитарных границ"))
                continue
            if book_tick <= 0 or book_tick > TICK_MAX:
                skipped.append(dict(bucket=b, why=f"книга: tick_size={book_tick} вне санитарных границ"))
                continue
            # Проверяем, что цены в levels соответствуют объявленному tick
            for price, size in levels:
                tick_mismatch = abs(price - round(price / book_tick) * book_tick)
                if tick_mismatch > 1e-9:
                    skipped.append(dict(bucket=b, why=f"книга: цена {price} не кратна tick_size={book_tick}"))
                    break
            else:
                # Все цены валидны, используем бо́льшее из CLOB min_shares
                leg_min_shares = max(mp.min_shares, book_min_shares)
                got = _walk_book(levels, mp._replace(min_shares=leg_min_shares), leg_min_shares, cap)
                if got is None:
                    skipped.append(dict(bucket=b, why=f"в книге нет объёма даже на минимальный ордер ${mp.min_notional:g} / {leg_min_shares} акций"))
                    continue
                sh, usd, lim = got
                eff = float(usd/sh)
                if eff > thin_mult*allin(ask, mp):
                    skipped.append(dict(bucket=b, why=f"тонкая книга: средняя {eff*100:.1f}¢ против аска {ask*100:.1f}¢"))
                    continue
                legs.append(dict(bucket=b, ask=ask, tid=tid, p=pp, levels=levels,
                                 min_shares=sh, min_usd=usd, limit=lim, book_min_shares=leg_min_shares))
        except Exception:
            skipped.append(dict(bucket=b, why="книга недоступна"))
            continue
    base = dict(lots=[], skipped=skipped, total_usd=0.0, min_usd=float(sum((l["min_usd"] for l in legs), Decimal("0"))),
                p_covered=0.0, ev_final=None, stake=round(stake, 2),
                budget_left=round(budget_left, 2), ok=False)
    if len(legs) < COMBO_MIN_LEGS:
        return dict(base, reason=f"исполнимых ног {len(legs)} < {COMBO_MIN_LEGS}")
    min_total = sum((l["min_usd"] for l in legs), Decimal("0"))
    # Точное сравнение в Decimal: не используем _cents() — округление может скрыть
    # реальное превышение потолка (1.4902 округляется к 1.49 = cap, хотя 1.4902 > 1.49).
    if min_total > cap:
        return dict(base, reason=(f"минимальные лоты ${float(_cents(min_total)):.2f} превышают "
                                  f"доступное ${float(cap):.2f} (ставка ${stake:.2f}, "
                                  f"остаток бюджета ${budget_left:.2f})"))
    lots, running = [], Decimal("0")
    for i, l in enumerate(legs):
        rest_min = sum((x["min_usd"] for x in legs[i+1:]), Decimal("0"))
        allow = cap - running - rest_min
        leg_mp = mp._replace(min_shares=l["book_min_shares"])
        got = _walk_book(l["levels"], leg_mp, target, allow)
        if got is None:                                  # минимум уже проверен выше
            sh, usd, lim = l["min_shares"], l["min_usd"], l["limit"]
        else:
            sh, usd, lim = got
        running += usd
        lots.append(dict(bucket=l["bucket"], ask=l["ask"], limit=round(lim, 3) if lim is not None else None,
                         shares=round(float(sh), 1), usd=float(_cents(usd)),
                         payout=round(float(sh), 1), p=l["p"]))
    total = _cents(running)
    exp_pay = sum((l["p"] or 0)*l["payout"] for l in lots)
    ev_final = round(exp_pay/float(total) - 1, 4) if total > 0 else None
    return dict(lots=lots, skipped=skipped, total_usd=float(total),
                min_usd=float(_cents(min_total)),
                p_covered=round(sum(l["p"] for l in lots if l.get("p")), 3),
                ev_final=ev_final, stake=round(stake, 2),
                budget_left=round(budget_left, 2), ok=True, reason=None)

def approve_combo(ex, budget_left, min_ev=COMBO_MIN_EV, min_legs=COMBO_MIN_LEGS):
    """Вердикт BET для комбо разрешён ТОЛЬКО по исполнимой экономике:
    лоты рассчитаны, ног не меньше двух, EV с комиссиями ≥ порога, и вся сумма
    влезает в остаток общего бюджета. Нет расчёта — нет ставки."""
    if not ex: return False, "исполнимые лоты не рассчитаны"
    if ex.get("err"): return False, f"ошибка расчёта лотов: {ex['err']}"
    if not ex.get("ok"): return False, ex.get("reason") or "лоты не собраны"
    lots = ex.get("lots") or []
    if len(lots) < min_legs: return False, f"исполнимых ног {len(lots)} < {min_legs}"
    ev = ex.get("ev_final")
    if ev is None: return False, "EV после исполнения не посчитан"
    if ev < min_ev: return False, f"EV после исполнения {ev:.2f} < {min_ev:.2f}"
    total = ex.get("total_usd") or 0.0
    if total <= 0: return False, "нулевой размер"
    if _cents(total) > _cents(budget_left, rounding=ROUND_DOWN):
        return False, f"сумма ${total:.2f} больше остатка бюджета ${budget_left:.2f}"
    if _cents(total) > _cents(ex.get("stake") or 0.0):
        return False, f"сумма ${total:.2f} больше запрошенной ставки ${ex.get('stake', 0):.2f}"
    return True, "ok"

def _token_ids(m):
    try:
        ti = (m or {}).get("clobTokenIds")
        ti = json.loads(ti) if isinstance(ti, str) else ti
        return list(ti) if ti else [None, None]
    except Exception:
        return [None, None]

def check_arb_legs(legs, mp, fetch=None):
    """Арбитраж засчитывается ТОЛЬКО как исполнимый: полные цены с комиссиями
    ЭТОГО рынка, реальные уровни стакана и минимальный ордер на каждой ноге.
    «Сумма асков ниже единицы» сама по себе не является гарантией — без книги и
    без комиссий это не арбитраж, а картинка.
    legs: [(token_id, котируемая цена)]."""
    fetch = fetch or get
    sets, cost, lots = None, 0.0, []
    for tid, _quoted in legs:
        if not tid:
            return dict(ok=False, why="нет идентификатора книги", exec_sets=0, exec_profit=0.0)
        try:
            book = fetch(f"https://clob.polymarket.com/book?token_id={tid}")
            asks = sorted((float(a["price"]), float(a["size"])) for a in book.get("asks", []))
        except Exception:
            return dict(ok=False, why="книга недоступна", exec_sets=0, exec_profit=0.0)
        if not asks:
            return dict(ok=False, why="пустая книга", exec_sets=0, exec_profit=0.0)
        price, size = asks[0]
        cost += allin(price, mp)
        sets = size if sets is None else min(sets, size)
        lots.append((price, size))
    sets = int(math.floor(sets or 0))
    res = dict(exec_sets=sets, exec_cost=round(cost, 3), exec_profit=0.0)
    if sets <= 0:
        return dict(res, ok=False, why="в книге нет объёма")
    if cost >= 1.0:
        return dict(res, ok=False, why=f"полная цена комплекта {cost:.3f} ≥ $1 — прибыли нет")
    if any(allin(pr, mp)*sets + 1e-9 < mp.min_notional for pr, _ in lots):
        return dict(res, ok=False, why=f"объёма не хватает на минимальный ордер ${mp.min_notional:g} по каждой ноге")
    return dict(res, ok=True, why=None, exec_profit=round((1.0-cost)*sets, 2))

def single_lot(pick, mp, budget_left, fetch=None):
    """Исполнимый лот для одиночной рекомендации. Проверяет реальную книгу,
    минимальное число акций, минимальный нотионал и fee-inclusive economics.
    Возвращает dict(ok, shares, usd, reason)."""
    fetch = fetch or get
    token_id = pick.get("token_id")
    ask = pick.get("ask")
    if not token_id or not ask:
        return dict(ok=False, shares=0.0, usd=0.0,
                   reason="нет token_id или ask для одиночной рекомендации")
    try:
        book = fetch(f"https://clob.polymarket.com/book?token_id={token_id}")
        levels = sorted((float(a["price"]), float(a["size"])) for a in book.get("asks", []))
        book_min_shares = _num(book, "min_order_size", "minimum_order_size")
        book_tick = _num(book, "tick_size", "minimum_tick_size")
        if book_min_shares is None or book_tick is None:
            return dict(ok=False, shares=0.0, usd=0.0,
                       reason="книга не содержит обязательные метаданные")
        if book_min_shares < 0 or book_min_shares > 10000:
            return dict(ok=False, shares=0.0, usd=0.0,
                       reason=f"book min_order_size={book_min_shares} вне границ")
        if book_tick <= 0 or book_tick > TICK_MAX:
            return dict(ok=False, shares=0.0, usd=0.0,
                       reason=f"book tick_size={book_tick} вне границ")
    except Exception as e:
        return dict(ok=False, shares=0.0, usd=0.0,
                   reason=f"книга недоступна: {str(e)[:40]}")
    
    # Используем бо́льшее из двух минимумов акций
    leg_min_shares = max(mp.min_shares, book_min_shares)
    cap = _cents(min(pick.get("stake", 0), budget_left), rounding=ROUND_DOWN)
    
    # Пытаемся набрать минимальный исполнимый лот
    leg_mp = mp._replace(min_shares=leg_min_shares)
    got = _walk_book(levels, leg_mp, leg_min_shares, cap)
    if got is None:
        return dict(ok=False, shares=0.0, usd=0.0,
                   reason=f"в книге нет объёма на минимум ${mp.min_notional:g} / {leg_min_shares} акций")
    
    sh, usd, lim = got
    return dict(ok=True, shares=float(sh), usd=float(_cents(usd)), limit=lim,
               reason=None)


def plan_weather(combos, picks, allocator, fetch=None, min_ev=COMBO_MIN_EV):
    """Единый проход по ВСЕМ погодным кандидатам одного прогона.

    * порядок приоритета детерминированный, ограничения «только первые шесть»
      нет: каждый кандидат либо одобрен, либо ЯВНО отклонён с причиной;
    * комбо получает BET только после расчёта исполнимых лотов;
    * одиночные рекомендации проходят ПОЛНУЮ валидацию книги и исполнимости;
    * бюджет резервируется в общем распределителе сразу — следующий кандидат
      видит уже уменьшенный остаток и не может потратить те же деньги;
    * максимумы, минимумы, серия и одиночные ставки ходят в один распределитель.
    """
    fetch = fetch or get
    approved = {"max": None, "min": None}
    order = sorted(combos, key=lambda c: (-(c.get("p_win", 0)*c.get("ev", 0)), c.get("city", ""), c.get("date", "")))
    for c in order:
        kind = "min" if "(мин)" in (c.get("city") or "") else "max"
        wdate = c.get("date")
        left = allocator.remaining(wdate)
        mp = c.get("mp")
        if mp is None:
            c["exec_ok"] = False; c["exec_why"] = "нет торговых параметров рынка"; continue
        if left < mp.min_notional*COMBO_MIN_LEGS:
            c["exec_ok"] = False
            c["exec_why"] = f"бюджет на {wdate} исчерпан: осталось ${left:.2f}"
            continue
        try:
            c["exec"] = combo_lots(c, mp, left, fetch)
        except Exception as e:
            c["exec_err"] = str(e)[:60]
            c["exec_ok"] = False; c["exec_why"] = f"ошибка расчёта лотов: {c['exec_err']}"; continue
        ok, why = approve_combo(c["exec"], left, min_ev=min_ev)
        c["exec_ok"], c["exec_why"] = ok, why
        if not ok: continue
        if approved[kind] is not None:
            c["exec_ok"] = False; c["exec_why"] = "рекомендация этой категории уже занята лучшим кандидатом"; continue
        granted = allocator.reserve(wdate, c["exec"]["total_usd"], tag=f"{kind}:{c.get('city')}:{wdate}")
        if granted + 1e-9 < c["exec"]["total_usd"]:
            c["exec_ok"] = False
            c["exec_why"] = f"остаток бюджета ${granted:.2f} меньше суммы комбо ${c['exec']['total_usd']:.2f}"
            continue
        c["stake"] = granted
        approved[kind] = c
    for t in sorted(picks, key=lambda t: -t.get("conf", 0)*t.get("ev", 0)):
        want = t.get("stake") or 0.0
        mp_t = t.get("mp")
        wdate = t.get("date")
        
        if mp_t is None:
            # Без mp используем allocator floor
            t_min_notional = allocator.min_notional
            if want < t_min_notional:
                t["stake"] = 0.0
                t["budget_block"] = (f"рекомендуемая ставка ${want:.2f} ниже минимального "
                                    f"ордера ${t_min_notional:.2f} (mp отсутствует)")
                continue
            # Резервируем без валидации книги (fail-open для совместимости)
            granted = allocator.reserve(wdate, want, tag=f"single:{t.get('city')}:{wdate}") if want else 0.0
            t["stake"] = granted
            if granted <= 0: t["budget_block"] = "бюджет даты исчерпан"
        else:
            # С mp выполняем ПОЛНУЮ валидацию через реальную книгу
            t_min_notional = mp_t.min_notional
            if want < t_min_notional:
                t["stake"] = 0.0
                t["budget_block"] = (f"рекомендуемая ставка ${want:.2f} ниже минимального "
                                    f"ордера этого рынка ${t_min_notional:.2f}")
                continue
            
            left = allocator.remaining(wdate)
            if left < t_min_notional:
                t["stake"] = 0.0
                t["budget_block"] = f"бюджет на {wdate} исчерпан: осталось ${left:.2f}"
                continue
            
            # Валидируем исполнимость через реальную книгу
            exec_result = single_lot(t, mp_t, left, fetch)
            if not exec_result.get("ok"):
                t["stake"] = 0.0
                t["budget_block"] = exec_result.get("reason", "неисполнимая книга")
                continue
            
            # Исполнимо — резервируем
            exec_usd = exec_result["usd"]
            granted = allocator.reserve(wdate, exec_usd, tag=f"single:{t.get('city')}:{wdate}")
            if granted + 1e-9 < exec_usd:
                t["stake"] = 0.0
                t["budget_block"] = f"остаток бюджета ${granted:.2f} < исполнимая сумма ${exec_usd:.2f}"
            else:
                t["stake"] = granted
                t["exec"] = exec_result
    return approved

PM_WALLET = ""  # публичный адрес кошелька Polymarket (0x...); пустой = блок портфеля выключен.
                # В публичном репозитории всегда пусто — адрес живёт только в приватном тексте задачи.

def _bucket_of(title):
    m = re.search(r"(-?\d+(?:--?\d+)?°[CF](?: or (?:below|higher|above))?)", title or "")
    return m.group(1) if m else (title or "?")

def portfolio_scan(wallet=None, fetch=None):
    """Портфель через открытый data-api Polymarket (по публичному адресу, без ключей):
    открытые позиции, сгруппированные по событиям, с раскладом «что вернётся при каждом
    исходе»; потрачено сегодня и остаток дневного лимита; выплаты, готовые к забору.
    Отдельно — уже вложенное по КАЖДОМУ дню погоды (`spent_by_weather_date`): это
    вход в общий распределитель бюджета."""
    fetch = fetch or get
    wallet = wallet or PM_WALLET
    if not wallet: return None
    pos = fetch(f"https://data-api.polymarket.com/positions?user={wallet}")
    try: value = round(float(fetch(f"https://data-api.polymarket.com/value?user={wallet}")[0]["value"]), 2)
    except Exception: value = None
    open_ev, redeem, by_wdate_pos = {}, [], {}
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
            wd = weather_date_of_slug(p.get("eventSlug"))
            if wd: by_wdate_pos[wd] = round(by_wdate_pos.get(wd, 0.0) + row["cost"], 2)
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
    spent_today, spent_wx, by_wdate_act = 0.0, 0.0, {}
    try:
        midnight = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        for a in fetch(f"https://data-api.polymarket.com/activity?user={wallet}&limit=100"):
            if a.get("timestamp", 0) >= midnight and a.get("type") == "TRADE" and a.get("side") == "BUY":
                v = float(a.get("usdcSize") or 0)
                spent_today += v
                if "temperature" in (a.get("eventSlug") or ""): spent_wx += v
                wd = weather_date_of_slug(a.get("eventSlug"))
                if wd: by_wdate_act[wd] = round(by_wdate_act.get(wd, 0.0) + v, 2)
    except Exception: pass
    # покупка сегодня и открытая позиция — один и тот же доллар; берём осторожный максимум
    by_wdate = {d: round(max(by_wdate_pos.get(d, 0.0), by_wdate_act.get(d, 0.0)), 2)
                for d in set(by_wdate_pos) | set(by_wdate_act)}
    redeem.sort(key=lambda r: -r["payout"])
    return dict(value=value, spent_today=round(spent_today, 2),
                spent_today_weather=round(spent_wx, 2),
                spent_by_weather_date=by_wdate,
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

def check_coverage(fetch=None):
    """Есть ли на Polymarket погодные города вне нашего списка (нужно ли обновлять HTML)."""
    fetch = fetch or get
    try:
        d = fetch("https://gamma-api.polymarket.com/public-search?q=highest%20temperature&limit_per_type=100&events_status=active")
        seen = set()
        for e in d.get("events", []):
            m = re.match(r"highest-temperature-in-([a-z-]+)-on-", e.get("slug",""))
            if m: seen.add(m.group(1))
        low = fetch("https://gamma-api.polymarket.com/public-search?q=lowest%20temperature&limit_per_type=50&events_status=active")
        nlow = len({e.get("slug","") for e in low.get("events",[]) if e.get("slug","").startswith("lowest-temperature")})
        return dict(new_cities=sorted(seen - set(ST)), lowest_temp_markets=nlow)
    except Exception as e:
        return dict(new_cities=[], lowest_temp_markets=None, err=str(e)[:80])

RES_FAILS = []  # fail-closed: рынки, не прошедшие контракт резолюции
POOL_FAILS = []  # fail-closed: события с неполным распределением исходов
PARAM_FAILS = []  # fail-closed: рынки без подтверждённых торговых параметров
RES_SEEN = {}   # eslug -> отпечаток правил: смена правил внутри прогона = стоп

RES_SOURCES = (
    ("wunderground", ("wunderground", "weather underground")),
    ("noaa", ("noaa", "national weather service", "nws")),
)
ICAO_SET = {v[0] for v in ST.values() if v[0]}
# четырёхбуквенные слова описания, которые НЕ являются кодом станции
STATION_STOP = {"NOAA", "ICAO", "METAR", "THIS", "WILL", "FROM", "DATA", "TIME", "UTC",
                "PLEASE", "MARKET", "YEAR", "DATE", "HIGH", "LOWS", "TEMP", "USDC", "ELSE"}

def resolution_fingerprint(desc):
    """Отпечаток правил резолюции: смена текста правил обязана быть замечена."""
    norm = re.sub(r"\s+", " ", (desc or "")).strip().lower()
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:16]

def parse_resolution(desc):
    """Разбор ПРАВИЛ КОНКРЕТНОГО рынка: источник, станция, единицы.
    Ничего не додумываем — что не написано, то не распознано.

    Единицы извлекаются ТОЛЬКО из нормативного текста резолюции; предложения
    с инструкциями интерфейса (переключение единиц через шестерёнку) не
    являются нормативными и не должны влиять на единицы резолюции."""
    text = desc or ""
    low = text.lower()
    sources = sorted({name for name, keys in RES_SOURCES if any(k in low for k in keys)})
    # Удаляем UI-инструкции перед разбором единиц: фраза «To toggle between X and Y»
    # описывает настройку отображения, а не нормативную единицу резолюции.
    text_norm = re.sub(r"[Tt]o toggle\b[^.!?\n]*[.!?]?", "", text)
    text_norm = re.sub(r"[Cc]lick the gear\b[^.!?\n]*[.!?]?", "", text_norm)
    low_norm = text_norm.lower()
    units = set()
    for m in re.finditer(r"degrees\s+(celsius|fahrenheit)", low_norm): units.add(m.group(1)[0].upper())
    for m in re.finditer(r"°\s*([CF])\b", text_norm): units.add(m.group(1))
    for m in re.finditer(r"\bdeg\s*([CF])\b", text_norm): units.add(m.group(1))
    tokens = {t for t in re.findall(r"\b[A-Z]{4}\b", text)} - STATION_STOP
    known = sorted(tokens & ICAO_SET)
    return dict(sources=sources, units=sorted(units), stations=sorted(tokens),
                known_stations=known, fingerprint=resolution_fingerprint(text))

def check_resolution(eslug, desc, unit, station, seen=None):
    """Fail-closed контракт резолюции. НЕ СТАВИМ, если правила:
    пустые; без распознанного источника; без распознанной станции; станция не
    та, на которой калиброваны наши поправки; единицы не те, в которых считает
    модель; противоречивые (две станции/двое единиц); изменившиеся с прошлого
    наблюдения этого же рынка."""
    seen = RES_SEEN if seen is None else seen
    if not (desc or "").strip():
        return False, dict(reason="правила резолюции пусты", eslug=eslug)
    r = parse_resolution(desc)
    prev = seen.get(eslug)
    seen[eslug] = r["fingerprint"]
    if prev and prev != r["fingerprint"]:
        return False, dict(r, reason="правила резолюции изменились", eslug=eslug)
    if not r["sources"]:
        return False, dict(r, reason="источник резолюции не распознан", eslug=eslug)
    if len(r["sources"]) > 1:
        return False, dict(r, reason=f"противоречивые источники: {', '.join(r['sources'])}", eslug=eslug)
    if not r["units"]:
        return False, dict(r, reason="единицы измерения не распознаны", eslug=eslug)
    if len(r["units"]) > 1:
        return False, dict(r, reason=f"противоречивые единицы: {', '.join(r['units'])}", eslug=eslug)
    if r["units"][0] != unit:
        return False, dict(r, reason=f"рынок в °{r['units'][0]}, модель в °{unit}", eslug=eslug)
    if not r["stations"]:
        return False, dict(r, reason="станция резолюции не распознана", eslug=eslug)
    if len(r["known_stations"]) > 1:
        return False, dict(r, reason=f"противоречивые станции: {', '.join(r['known_stations'])}", eslug=eslug)
    if not station or station not in r["stations"]:
        return False, dict(r, reason=(f"станция рынка {'/'.join(r['stations'])} ≠ наша {station or '—'}"), eslug=eslug)
    return True, dict(r, reason=None, eslug=eslug)

def coverage_ok(ranges):
    """Полное взаимоисключающее распределение исходов: от «или ниже» до «или
    выше», без дыр и наложений. Лог-пул можно считать ТОЛЬКО по такому набору —
    нормировать неполное подмножество к единице значит выдумать вероятность."""
    rs = sorted(ranges)
    if len(rs) < 2: return False
    if rs[0][0] > -900 or rs[-1][1] < 900: return False
    for (lo1, hi1), (lo2, hi2) in zip(rs, rs[1:]):
        if abs(hi1 - lo2) > 1e-9: return False
    return True

def screen(slug, cal, dates, kind="max", fetch=None):
    fetch = fetch or get
    icao, lat, lon, unit, ru = ST[slug]
    if kind == "min": ru = ru + " (мин)"
    q = urllib.parse.urlencode(dict(latitude=lat, longitude=lon, hourly="temperature_2m",
        models="ecmwf_ifs025,gfs025,icon_seamless,gem_global", timezone="auto",
        start_date=dates[0][1], end_date=dates[-1][1]))
    ens = fetch("https://ensemble-api.open-meteo.com/v1/ensemble?" + q)
    times = ens["hourly"]["time"]
    keys = [k for k in ens["hourly"] if k.startswith("temperature_2m")]
    trades = []
    for lead, ds in dates:
        d = datetime.strptime(ds, "%Y-%m-%d")
        prefix = "lowest" if kind == "min" else "highest"
        eslug = f"{prefix}-temperature-in-{slug}-on-{MONTHS[d.month-1]}-{d.day}-{d.year}"
        evs = fetch(f"https://gamma-api.polymarket.com/events?slug={eslug}")
        if not evs or evs[0].get("closed"): continue
        ev = evs[0]
        # fail-closed контракт резолюции: источник, станция и единицы — из правил рынка
        ok_res, det = check_resolution(eslug, ev.get("description"), unit, icao)
        if not ok_res:
            RES_FAILS.append(f"{eslug}: {det['reason']}"); continue
        tier = cal_tier(cal, lead)
        bucket_markets = [m for m in ev["markets"] if parse_bucket(m.get("groupItemTitle"))]
        # торговые параметры КОНКРЕТНОГО рынка: комиссия, шаг цены, минимальный ордер
        mp = event_params(bucket_markets, fetch)
        if mp is None:
            PARAM_FAILS.append(f"{eslug}: торговые параметры рынка не подтверждены"); continue
        vol = float(ev.get("volume") or 0)
        allasks = [m.get("bestAsk") for m in bucket_markets]
        if len(allasks) >= 5 and all(a is not None for a in allasks):
            SLOPPY.append(dict(city=ru, date=ds, sum_ask=round(sum(allasks), 3),
                               sum_allin=round(sum(allin(a, mp) for a in allasks), 3), eslug=eslug))
        if vol < 10000: continue
        volpen = 1 if vol < 30000 else 0
        day = {"all": [], "ec": [], "gf": [], "ic": [], "gm": []}
        for k in keys:
            mx = daymax(times, ens["hourly"][k], ds, is_min=(kind == "min")).get(ds)
            if mx is None: continue
            day["all"].append(mx); day[fam_of(k)].append(mx)
        if len(day["all"]) < 20: continue
        titled = [m for m in ev["markets"] if m.get("groupItemTitle")]
        unparsed = [m for m in titled if not parse_bucket(m.get("groupItemTitle"))]
        if unparsed:                       # формат бакета сменился — распределение неполное
            PARSE_FAIL[0] += len(unparsed)
            POOL_FAILS.append(f"{eslug}: нераспознанные бакеты ({len(unparsed)}) — пул не считаем")
            continue
        rows, incomplete = [], None
        for m in bucket_markets:
            rng = parse_bucket(m.get("groupItemTitle"))
            bb, ba = m.get("bestBid"), m.get("bestAsk")
            pr = m.get("outcomePrices")
            if isinstance(pr, str):
                try: pr = json.loads(pr)
                except Exception: pr = None
            mid = (bb+ba)/2 if (bb is not None and ba is not None) else (float(pr[0]) if pr else None)
            if mid is None:
                incomplete = f"{eslug}: у бакета «{m.get('groupItemTitle')}» нет цены — пул не считаем"; break
            p_raw, fams_p = fam_prob(day, rng, unit, cal["fams"], lead)
            if p_raw is None:
                incomplete = f"{eslug}: нет модельной вероятности бакета «{m.get('groupItemTitle')}»"; break
            pLo_raw, _ = fam_prob(day, rng, unit, cal["fams"], lead, dbias=-1.0)
            pHi_raw, _ = fam_prob(day, rng, unit, cal["fams"], lead, dbias=+1.0)
            tid = None
            try:
                ti = m.get("clobTokenIds")
                ti = json.loads(ti) if isinstance(ti, str) else ti
                tid = ti[0] if ti else None
            except Exception: pass
            rows.append(dict(bucket=m.get("groupItemTitle"), rng=rng, bb=bb, ba=ba, mid=mid, tid=tid,
                             p=p_raw, pLo=pLo_raw, pHi=pHi_raw, fams=fams_p))
        if incomplete:
            POOL_FAILS.append(incomplete); continue
        if len(rows) < 3 or not coverage_ok([r["rng"] for r in rows]):
            POOL_FAILS.append(f"{eslug}: распределение исходов неполное — усадку к рынку не считаем")
            continue
        # усадка к рынку: нормализованный лог-пул p^λ · q^(1−λ) по ПОЛНОМУ набору бакетов
        for r, sh in zip(rows, log_pool(rows)):
            r["pS"], r["pLoS"], r["pHiS"] = sh["p"], sh["pLo"], sh["pHi"]
        crows = []
        for r in rows:
            bb, ba, mid = r["bb"], r["ba"], r["mid"]
            pS, pLoS, pHiS = r["pS"], r["pLoS"], r["pHiS"]
            fv = list(r["fams"].values())
            base = dict(city=ru, slug=slug, date=ds, lead=lead, bucket=r["bucket"],
                        p=round(pS,3), p_model=round(r["p"],3), mid=round(mid,3),
                        fams=r["fams"], vol=int(vol), tid=r["tid"], tier=tier,
                        link=f"https://polymarket.com/event/{eslug}")
            crows.append(dict(bucket=r["bucket"], p=pS, pLo=pLoS, pHi=pHiS, ask=ba,
                              tid=r["tid"], pmodel=r["p"]))
            if ba is not None:
                c = allin(ba, mp)  # полная цена с комиссией ЭТОГО рынка
                if 0.04 <= c <= 0.30 and pS >= 1.8*c and r["p"] >= 2*ba and pS >= 0.05:
                    robust = pLoS >= 1.4*c and pHiS >= 1.4*c
                    mn = min(fv) if fv else r["p"]
                    agree = 1 if mn >= 0.5*r["p"] else (-1 if mn < 0.25*r["p"] else 0)
                    spread = ba-bb if bb is not None else ba
                    conf = 3 + (1 if robust else 0) + agree - (1 if spread > 0.08 else 0) - volpen - (1 if lead >= 2 else 0)
                    if tier == "C": conf = min(conf, 2)
                    trades.append(dict(base, side="YES", cost=round(c,3), ask=ba,
                                       ev=round(pS*(1/c-1)-(1-pS),2),
                                       conf=max(1,min(5,conf)), robust=robust,
                                       stake=kelly_stake(pS, min(pLoS, pHiS), c), mp=mp))
            if bb is not None and mid >= 0.25 and (mid-pS) >= 0.12:
                c = allin(1-bb, mp)
                robust = (mid-pHiS >= 0.08) and (mid-pLoS >= 0.08)
                agr = all(mid-x >= 0.10 for x in fv); ref = any(x >= mid for x in fv)
                agree = 1 if agr else (-1 if ref else 0)
                conf = 3 + (1 if robust else 0) + agree - volpen - (1 if lead >= 2 else 0)
                if tier == "C": conf = min(conf, 2)
                trades.append(dict(base, side="NO", cost=round(c,3), ask=round(1-bb,3),
                                   ev=round((1-pS)*(1/c-1)-pS,2),
                                   conf=max(1,min(5,conf)), robust=robust,
                                   stake=kelly_stake(1-pS, 1-max(pLoS, pHiS), c), mp=mp))
        for st in chance_combos(crows, mp):
            COMBOS.append(dict(st, city=ru, date=ds, lead=lead, vol=int(vol), tier=tier,
                               mp=mp, link=f"https://polymarket.com/event/{eslug}"))
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
                        combos=chance_combos(qrows, mp)[-2:] if vol >= 500 else [], sum_ask=q_sum_ask, sum_allin=q_sum_allin, arb=q_arb,
                        link=f"https://polymarket.com/event/{slug}"))
    return out

# ================= контур №3: крипта против опционов Deribit =================
DMON = {m: i+1 for i, m in enumerate(["JAN","FEB","MAR","APR","MAY","JUN","JUL","AUG","SEP","OCT","NOV","DEC"])}

def load_surface(cur, fetch=None):
    fetch = fetch or get
    rows = fetch(f"https://www.deribit.com/api/v2/public/get_book_summary_by_currency?currency={cur}&kind=option")["result"]
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

def crypto_scan(fetch=None):
    """Контур №3: рынки BTC/ETH above $K против риск-нейтральных вероятностей опционов."""
    fetch = fetch or get
    now = datetime.now(timezone.utc)
    out = []
    for cur, pref in (("BTC","bitcoin"), ("ETH","ethereum")):
        try: surf = load_surface(cur, fetch)
        except Exception as e:
            out.append(dict(error=f"deribit {cur}: {str(e)[:60]}")); continue
        for dd in range(0, 8):
            d = now + timedelta(days=dd)
            slug = f"{pref}-above-on-{MONTHS[d.month-1]}-{d.day}-{d.year}"
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
    dates = [(1, (now+timedelta(days=1)).strftime("%Y-%m-%d")), (2, (now+timedelta(days=2)).strftime("%Y-%m-%d"))]
    calib, trades, errors = {}, [], []
    for slug in ST:
        try: calib[slug] = calibrate(slug, fetch=fetch)
        except Exception as e:
            calib[slug] = dict(fams={"1": {}, "2": {}}, bias=REF_BIAS.get(slug,0.0), n=0, std=None,
                               tier="C", tiers={"1": "C", "2": "C"})
            errors.append(f"calib {slug}: {e}")
    for slug in ST:
        try: trades += screen(slug, calib[slug], dates, fetch=fetch)
        except Exception as e: errors.append(f"screen {slug}: {e}")
    calib_min = {}
    for slug in MIN_SLUGS:
        try: calib_min[slug] = calibrate(slug, is_min=True, fetch=fetch)
        except Exception as e:
            calib_min[slug] = dict(fams={"1": {}, "2": {}}, bias=REF_BIAS_MIN.get(slug,0.0), n=0, std=None,
                                   tier="C", tiers={"1": "C", "2": "C"})
            errors.append(f"calib_min {slug}: {e}")
    for slug in MIN_SLUGS:
        try: trades += screen(slug, calib_min[slug], dates, kind="min", fetch=fetch)
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
            book = fetch(f"https://clob.polymarket.com/book?token_id={t['tid']}")
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
    # «чистый арбитраж» — только исполнимый: комиссии рынка + реальные уровни книг
    for x in pure_arb[:3]:
        try:
            evx = fetch(f"https://gamma-api.polymarket.com/events?slug={x['eslug']}")[0]
            bms = [m for m in evx["markets"] if parse_bucket(m.get("groupItemTitle"))]
            mpx = event_params(bms, fetch)
            if mpx is None:
                x["exec_err"] = "торговые параметры рынка не подтверждены"; x["arb_ok"] = False; continue
            legs = [(_token_ids(m)[0], m.get("bestAsk")) for m in bms]
            res = check_arb_legs(legs, mpx, fetch)
            x.update(exec_sets=res["exec_sets"], exec_cost=res["exec_cost"],
                     exec_profit=res["exec_profit"], arb_ok=res["ok"], arb_why=res["why"])
        except Exception as e:
            x["exec_err"] = str(e)[:60]; x["arb_ok"] = False
    try:
        portfolio = portfolio_scan(fetch=fetch)
        mark_held(picks, portfolio)
    except Exception as e:
        portfolio = None; errors.append(f"portfolio: {e}")
    # ЕДИНЫЙ распределитель бюджета: ключ — дата погоды, а не UTC-дата сделки.
    allocator = BudgetAllocator(spent_total=(portfolio or {}).get("spent_today", 0.0),
                                spent_by_date=(portfolio or {}).get("spent_by_weather_date", {}))
    # один проход по ВСЕМ кандидатам: лоты → вердикт → резерв бюджета
    approved = plan_weather(combo_top, picks[:12], allocator, fetch=fetch)
    # серийная ставка дня: только среди ОДОБРЕННЫХ по исполнимой экономике
    series = next((c for c in sorted([x for x in approved.values() if x], key=lambda c: -(c["p_win"]*c["ev"]))
                   if c["p_win"] >= 0.60 and c["ev"] >= 0.20 and c["tier"] in ("A", "B")
                   and (c["p_rng"][1]-c["p_rng"][0]) <= 0.25 and c["vol"] >= 15000), None)
    for c in combo_top:
        c.pop("tids", None)
        mp = c.pop("mp", None)
        if mp is not None: c["market_params"] = mp._asdict()
    try: quakes = quake_scan(fetch)
    except Exception as e:
        quakes = []; errors.append(f"quakes: {e}")
    try: crypto = crypto_scan(fetch)
    except Exception as e:
        crypto = []; errors.append(f"crypto: {e}")
    # «Вердикт дня»: по одной самой реальной ставке на категорию — или честный пропуск
    def wx_verdict(combo, ps):
        if combo is not None:
            return dict(combo, kind="серия-комбо" if combo is series else "шанс-комбо")
        p = next((t for t in ps if t["conf"] >= 5 and t.get("robust") and (t.get("stake") or 0) > 0), None)
        if p: return dict({k: v for k, v in p.items() if k not in ("tid",)}, kind="одиночная")
        return None
    def ev_verdict(markets, want_arb_key=None):
        best = None
        for mkt in markets:
            if want_arb_key == "sum" and (mkt.get("arb") or {}).get("ok"):
                return dict(kind="исполнимый арбитраж", market=mkt["title"], sum_ask=mkt["sum_ask"],
                            sum_allin=mkt["sum_allin"], exec_sets=mkt["arb"]["exec_sets"],
                            exec_cost=mkt["arb"]["exec_cost"], exec_profit=mkt["arb"]["exec_profit"], link=mkt["link"])
            if want_arb_key == "arbs" and mkt.get("arbs"):
                return dict(kind="арбитраж-связка", market=mkt["title"], arbs=mkt["arbs"], link=mkt["link"])
            for pk in mkt.get("picks", []):
                if pk["conf"] >= 4 and (best is None or pk["ev"] > best["ev"]):
                    best = dict(pk, kind="одиночная", market=mkt["title"], link=mkt["link"])
        return best
    verdicts = dict(
        max=wx_verdict(approved["max"], [t for t in picks if "(мин)" not in t["city"]]),
        min=wx_verdict(approved["min"], [t for t in picks if "(мин)" in t["city"]]),
        quakes=ev_verdict(quakes, "sum") or ev_verdict(quakes),
        crypto=ev_verdict(crypto, "arbs") or ev_verdict(crypto),
    )
    budget = allocator.snapshot()
    budget["rejections"] = [dict(city=c["city"], date=c["date"], buckets=c["buckets"],
                                 why=c.get("exec_why") or "не выбран")
                            for c in combo_top if not c.get("exec_ok")][:10]
    print(json.dumps(dict(
        generated=now.strftime("%Y-%m-%d %H:%M UTC"),
        bankroll=BANKROLL, day_limit=DAY_LIMIT, min_order=MIN_ORDER,
        budget=budget, portfolio=portfolio,
        model_policy=dict(lambda_model=LAMBDA,
                          fee="тейкер: rate·цена·(1−цена) с акции, rate берётся из параметров конкретного рынка",
                          min_leg_ask=0.03, combo_min_ev=COMBO_MIN_EV, combo_min_legs=COMBO_MIN_LEGS,
                          note="фаза валидации: усадка к рынку, дешёвые хвосты запрещены"),
        res_checks=RES_FAILS, pool_checks=POOL_FAILS, param_checks=PARAM_FAILS,
        verdicts=verdicts,
        calib_json=dict(cal_date=now.strftime("%Y-%m-%d"), cities=calib, cities_min=calib_min),
        picks=picks[:12], watch=watch[:10], chance_combos=combo_top[:10], series_pick=series,
        bias_drift_over_1C=drift, errors=errors,
        pure_arb=pure_arb, most_inefficient=sloppy[:5],
        html_health=dict(coverage=check_coverage(fetch), parse_fails=PARSE_FAIL[0]),
        quakes=quakes, crypto=crypto,
    ), ensure_ascii=False, indent=1))

if __name__ == "__main__":
    main()
