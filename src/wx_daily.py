#!/usr/bin/env python3
"""Daily Polymarket weather job: recalibrate stations -> screen tomorrow &
day-after -> print JSON report. Self-contained, stdlib only."""
import hashlib, json, math, os, re, threading, time, urllib.error, urllib.request, urllib.parse
from collections import namedtuple
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP, ROUND_UP

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

def http_timeout(value=None):
    raw = os.environ.get("WX_HTTP_TIMEOUT", "20") if value is None else value
    try: return max(5.0, min(float(raw), 60.0))
    except (TypeError, ValueError): return 20.0


def get(url, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent":"wx-daily/1.0"})
            with urllib.request.urlopen(req, timeout=http_timeout()) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            # Permanent client errors should fail immediately; retry throttling and
            # transient server failures, respecting Retry-After when available.
            if e.code not in (408, 425, 429, 500, 502, 503, 504) or i == tries-1:
                raise
            retry_after = e.headers.get("Retry-After") if e.headers else None
            try: delay = max(float(retry_after), 0.0)
            except (TypeError, ValueError): delay = 2*(i+1)
            time.sleep(min(delay, 30.0))
        except Exception:
            if i == tries-1: raise
            time.sleep(2*(i+1))


class _Flight:
    def __init__(self):
        self.event = threading.Event()
        self.result = None
        self.error = None


class RunFetcher:
    """Thread-safe, per-run JSON fetcher.

    Slow snapshot endpoints are cached and identical concurrent requests are
    single-flighted.  Volatile execution data (books and portfolio/activity)
    always reaches the network.  A global worker pool plus
    per-host semaphores bounds pressure on public APIs.
    """
    VOLATILE = (
        "clob.polymarket.com/book?",
        "data-api.polymarket.com/positions?",
        "data-api.polymarket.com/value?",
        "data-api.polymarket.com/activity?",
    )
    HOST_LIMITS = {
        "previous-runs-api.open-meteo.com": 3,
        "ensemble-api.open-meteo.com": 3,
        "aviationweather.gov": 2,
        "gamma-api.polymarket.com": 3,
        "clob.polymarket.com": 2,
    }

    def __init__(self, base=None):
        self.base = base or get
        self._cache = {}
        self._flights = {}
        self._semaphores = {}
        self._lock = threading.Lock()
        self._actual_requests = 0
        self._cache_hits = 0
        self._singleflight_hits = 0
        self._active = 0
        self._peak = 0

    def _cacheable(self, url):
        return not any(marker in url for marker in self.VOLATILE)

    def _semaphore(self, url):
        host = urllib.parse.urlsplit(url).netloc.lower()
        with self._lock:
            sem = self._semaphores.get(host)
            if sem is None:
                sem = threading.BoundedSemaphore(self.HOST_LIMITS.get(host, 2))
                self._semaphores[host] = sem
            return sem

    def _network(self, url):
        sem = self._semaphore(url)
        with sem:
            with self._lock:
                self._actual_requests += 1
                self._active += 1
                self._peak = max(self._peak, self._active)
            try:
                return self.base(url)
            finally:
                with self._lock:
                    self._active -= 1

    def __call__(self, url, *args, **kwargs):
        # Production fetchers take just URL.  Keep args in the signature so the
        # wrapper remains drop-in compatible with deterministic test doubles.
        if args or kwargs:
            return self.base(url, *args, **kwargs)
        if not self._cacheable(url):
            return self._network(url)
        with self._lock:
            if url in self._cache:
                self._cache_hits += 1
                return self._cache[url]
            flight = self._flights.get(url)
            if flight is None:
                flight = _Flight()
                self._flights[url] = flight
                owner = True
            else:
                self._singleflight_hits += 1
                owner = False
        if not owner:
            flight.event.wait()
            if flight.error is not None:
                raise flight.error
            return flight.result
        try:
            result = self._network(url)
            flight.result = result
            with self._lock:
                self._cache[url] = result
            return result
        except BaseException as exc:
            flight.error = exc
            raise
        finally:
            with self._lock:
                self._flights.pop(url, None)
            flight.event.set()

    def stats(self):
        with self._lock:
            return dict(actual_requests=self._actual_requests,
                        cache_hits=self._cache_hits,
                        singleflight_hits=self._singleflight_hits,
                        cached_urls=len(self._cache),
                        peak_inflight=self._peak)


def _parallel_map(fn, items, workers):
    """Bounded map with deterministic input-order results."""
    items = list(items)
    workers = max(1, min(int(workers or 1), 8))
    if workers == 1 or len(items) < 2:
        return [fn(item) for item in items]
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="wx") as pool:
        return list(pool.map(fn, items))


def runtime_workers(value=None):
    raw = os.environ.get("WX_WORKERS", "4") if value is None else value
    try: return max(1, min(int(raw), 8))
    except (TypeError, ValueError): return 4

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
    параметров конкретного рынка (`MarketParams`), поэтому рынки с разными
    ставками комиссии не делят один зашитый множитель."""
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
    
    Поддерживаемая модель: exponent=1 (rate*price^1*(1-price)^1),
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
    # Polymarket задаёт степень каждому множителю: p^e*(1-p)^e. Для текущей
    # документированной погодной кривой p*(1-p) канонический exponent равен 1.
    exponent = schedule.get("exponent")
    if exponent is not None and exponent != 1:
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

def market_params(m, fetch=None, enrich_clob=True):
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
    elif enrich_clob:
        # Gamma дала полный набор; необязательно дополняем min_shares из CLOB.
        # Массовый скрин отключает этот N-per-bucket проход: фактическая книга
        # всё равно fail-closed проверяется перед каждым исполнимым лотом.
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

def event_params(markets, fetch=None, enrich_clob=True):
    """Параметры события: строгий режим — параметры обязаны быть у КАЖДОГО
    торгуемого бакета, иначе None. При расхождении берём худший вариант
    (дороже комиссия, крупнее шаг, нотионал и число акций)."""
    markets = list(markets or [])
    if not markets: return None
    ps = []
    for m in markets:
        p = market_params(m, fetch, enrich_clob=enrich_clob)
        if p is None: return None
        ps.append(p)
    return MarketParams(fee_rate=max(p.fee_rate for p in ps),
                        tick=max(p.tick for p in ps),
                        min_notional=max(p.min_notional for p in ps),
                        min_shares=max(p.min_shares for p in ps),
                        source="event")

LAMBDA = 0.25    # вес СВОЕЙ модели в пуле с рынком на фазе валидации (совет внешней ревизии)
EPS_TICK = 0.001 # минимальный тик цены
EPS_MONEY = Decimal("1e-6")  # допуск для сравнений денег (защита от артефактов float→Decimal)

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
    # Validate complete data: all rows must have p, pLo, pHi, mid
    complete = [r for r in rows if r.get("p") is not None and r.get("pLo") is not None 
                and r.get("pHi") is not None and r.get("mid") is not None]
    if len(complete) < len(rows):
        raise ValueError("неполный ансамбль бакетов — log pool требует полных данных по всем бакетам")
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
DAY_LIMIT = 10.0  # две даты погоды × $5; общий аварийный потолок
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
        0, если остатка не хватает даже на минимальный ордер.
        
        Резервирует ТОЧНУЮ запрошенную сумму (или округлённую ВВЕРХ до центов),
        чтобы исполнимая стоимость не превышала зарезервированное."""
        # Округляем вверх до центов, чтобы зарезервированное покрывало исполнимую стоимость
        want = _cents(max(0.0, float(amount or 0.0)), rounding=ROUND_UP)
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
PAPER_FORECASTS = []  # полные city-day распределения; не ставки, а оценочный архив
_STATE_LOCK = threading.RLock()

def _state_append(target, value):
    with _STATE_LOCK:
        target.append(value)

def _state_parse_fail(count):
    with _STATE_LOCK:
        PARSE_FAIL[0] += count

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
SINGLE_MIN_EV = 0.10  # порог EV для одиночной ставки ПОСЛЕ расчёта исполнимых лотов

def _walk_book(levels, mp, target_shares, usd_cap, price_limit=None):
    """Обход книги в Decimal: набираем до target_shares акций, но не меньше
    минимального нотионала и минимального числа акций рынка, и не дороже usd_cap.
    Возврат (shares, usd, limit_price) или None, если минимум не набирается.
    Деньги считаются десятичными дробями: нога ровно на $1.00 обязана пройти —
    двоичная 0.9999999999999999 не должна её отбраковывать.
    price_limit: if set, stop walking when price > price_limit (hard execution ceiling)."""
    # Округлённый минимум для практических расчётов в цикле
    min_notional_rounded = _cents(mp.min_notional)
    # Точный минимум для финальной проверки
    min_notional_exact = Decimal(str(mp.min_notional))
    cap = _cents(usd_cap, rounding=ROUND_DOWN)
    if cap < min_notional_rounded: return None
    # Минимальное число акций — бо́льшее из требования рынка (CLOB) и целевого числа
    want_sh = Decimal(str(max(target_shares, mp.min_shares)))
    sh, usd, lim = Decimal("0"), Decimal("0"), None
    for price, size in levels:
        p = Decimal(str(price)); size = Decimal(str(size))
        if p <= 0 or size <= 0: continue
        # Stop walk if price exceeds limit
        if price_limit is not None and p > Decimal(str(price_limit)) + EPS_MONEY: break
        a = p + Decimal(str(mp.fee_rate))*p*(1-p)     # полная цена акции
        if a <= 0: continue
        take = max(want_sh - sh, Decimal("0"))
        if usd < min_notional_rounded:                 # USDC-нотионал — обязателен
            take = max(take, (min_notional_rounded - usd)/a)
        if take <= 0: break
        take = min(take, size)
        if usd + a*take > cap:                         # бюджет ноги не превышаем
            take = (cap - usd)/a
            if take <= 0: break
        sh += take; usd += a*take; lim = price
        if sh >= want_sh and usd >= min_notional_rounded: break
    # Финальная проверка: точное сравнение RAW usd (не _cents(usd)) против минимума,
    # с малым допуском для артефактов Decimal-арифметики (нога ровно на $1.00 обязана пройти)
    if sh <= 0 or usd + EPS_MONEY < min_notional_exact: return None
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
            # Валидируем метаданные: book_min_shares должен быть строго положительным
            if book_min_shares is None or book_min_shares <= 0 or book_min_shares > 10000:
                skipped.append(dict(bucket=b, why=f"книга: min_order_size={book_min_shares} вне санитарных границ или нулевой"))
                continue
            if book_tick <= 0 or book_tick > TICK_MAX:
                skipped.append(dict(bucket=b, why=f"книга: tick_size={book_tick} вне санитарных границ"))
                continue
            # Проверяем совместимость mp.tick (Gamma) и book_tick (CLOB)
            # Они должны совпадать — разные тики означают несогласованные метаданные
            if mp.tick and book_tick:
                if abs(mp.tick - book_tick) > 1e-9:
                    skipped.append(dict(bucket=b, why=f"несовместимые тики: Gamma tick={mp.tick} vs книга tick_size={book_tick}"))
                    continue
            # Проверяем, что ask совместим с book_tick
            ask_tick_mismatch = abs(ask - round(ask / book_tick) * book_tick)
            if ask_tick_mismatch > 1e-9:
                skipped.append(dict(bucket=b, why=f"ask {ask} не кратен книжному tick_size={book_tick}"))
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
                got = _walk_book(levels, mp._replace(min_shares=leg_min_shares), leg_min_shares, cap, price_limit=None)
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
    base = dict(lots=[], skipped=skipped, total_usd=0.0, 
                min_usd=float(_cents(sum((l["min_usd"] for l in legs), Decimal("0")), rounding=ROUND_UP)),
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
        got = _walk_book(l["levels"], leg_mp, target, allow, price_limit=None)
        if got is None:                                  # минимум уже проверен выше
            sh, usd, lim = l["min_shares"], l["min_usd"], l["limit"]
        else:
            sh, usd, lim = got
        running += usd
        lots.append(dict(bucket=l["bucket"], ask=l["ask"], limit=round(lim, 3) if lim is not None else None,
                         shares_raw=sh, usd_raw=usd, p=l["p"]))
    
    # Normalize shares to executable precision (1 decimal) and recompute costs
    # to ensure returned shares don't exceed cap when executed
    for lot in lots:
        sh_raw = lot["shares_raw"]
        # Round shares to 1 decimal (the precision we report and execute)
        sh_rounded = Decimal(str(round(float(sh_raw), 1)))
        # Recompute cost from rounded shares
        ask = Decimal(str(lot["ask"]))
        full_price = ask + Decimal(str(mp.fee_rate)) * ask * (1 - ask)
        usd_from_rounded = sh_rounded * full_price
        # Store RAW cost for total calculation, rounded cost for display
        lot["shares"] = round(float(sh_rounded), 1)
        lot["usd_raw_rounded"] = usd_from_rounded  # RAW for comparison
        lot["usd"] = float(_cents(usd_from_rounded, rounding=ROUND_UP))  # Conservative ceiling
        lot["payout"] = round(float(sh_rounded), 1)
        del lot["shares_raw"]
        del lot["usd_raw"]
    
    # Re-validate each leg after normalization: raw usd must still meet min_notional
    # (Normalized shares will be less than or equal to raw, so no separate shares check needed)
    min_notional_exact = Decimal(str(mp.min_notional))
    for lot in lots:
        usd_raw = lot["usd_raw_rounded"]
        if usd_raw + EPS_MONEY < min_notional_exact:
            return dict(base, reason=(f"после округления нога «{lot['bucket']}» имеет "
                                     f"raw debit ${float(usd_raw):.4f} < минимум ${mp.min_notional:g}"))
    
    # Recompute total from RAW usd values (before rounding), not from rounded usd
    # This ensures we catch any case where the sum of raw costs exceeds cap
    total_from_rounded = Decimal("0")
    for lot in lots:
        total_from_rounded += lot["usd_raw_rounded"]
    
    # Verify recomputed total doesn't exceed cap - NO TOLERANCE
    # Compare raw Decimal values precisely before any presentation rounding
    if total_from_rounded > cap:
        return dict(base, reason=(f"после округления акций исполнимая стоимость "
                                 f"${float(_cents(total_from_rounded)):.2f} превышает "
                                 f"доступное ${float(cap):.2f}"))
    
    # Clean up temporary fields
    for lot in lots:
        del lot["usd_raw_rounded"]
    
    total = _cents(total_from_rounded, rounding=ROUND_UP)  # Conservative ceiling
    exp_pay = sum((l["p"] or 0)*l["payout"] for l in lots)
    ev_final = round(exp_pay/float(total) - 1, 4) if total > 0 else None
    return dict(lots=lots, skipped=skipped, total_usd=float(total),
                min_usd=float(_cents(min_total, rounding=ROUND_UP)),  # Conservative ceiling
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
            # Проверяем положительность book_min_order
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
        # Проверяем, что ВСЕ цены в книге соответствуют объявленному tick
        for price, size in asks:
            price_tick_mismatch = abs(price - round(price / book_tick) * book_tick)
            if price_tick_mismatch > 1e-9:
                return dict(ok=False, why=f"книга: цена {price} не кратна tick_size={book_tick}",
                           exec_sets=0, exec_profit=0.0)
        price, size = asks[0]
        # Проверяем котируемую цену, если она задана
        if _quoted is not None:
            quoted_tick_mismatch = abs(_quoted - round(_quoted / book_tick) * book_tick)
            if quoted_tick_mismatch > 1e-9:
                return dict(ok=False, why=f"котируемая цена {_quoted} не кратна tick_size={book_tick}",
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

def single_lot(pick, mp, budget_left, fetch=None, probability=None):
    """Исполнимый лот для одиночной рекомендации. Проверяет реальную книгу,
    минимальное число акций, минимальный нотионал и fee-inclusive economics.
    Возвращает dict(ok, shares, usd, limit, ev_final, reason).
    probability: optional model probability for EV calculation."""
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
                       reason="книга без метаданных min_order_size/tick_size")
        if book_min_shares is None or book_min_shares <= 0 or book_min_shares > 10000:
            return dict(ok=False, shares=0.0, usd=0.0,
                       reason=f"book min_order_size={book_min_shares} вне границ или нулевой")
        if book_tick <= 0 or book_tick > TICK_MAX:
            return dict(ok=False, shares=0.0, usd=0.0,
                       reason=f"book tick_size={book_tick} вне границ")
        # Проверяем совместимость mp.tick и book_tick
        if mp.tick and book_tick:
            if abs(mp.tick - book_tick) > 1e-9:
                return dict(ok=False, shares=0.0, usd=0.0,
                           reason=f"несовместимые тики: Gamma tick={mp.tick} vs книга tick_size={book_tick}")
        # Проверяем, что ask совместим с book_tick
        ask_tick_mismatch = abs(ask - round(ask / book_tick) * book_tick)
        if ask_tick_mismatch > 1e-9:
            return dict(ok=False, shares=0.0, usd=0.0,
                       reason=f"цена {ask} несовместима с tick={book_tick}")
    except Exception as e:
        return dict(ok=False, shares=0.0, usd=0.0,
                   reason=f"книга недоступна: {str(e)[:40]}")
    
    # Use ask as the execution price limit - never consume worse levels
    execution_limit = ask
    # Используем бо́льшее из двух минимумов акций
    leg_min_shares = max(mp.min_shares, book_min_shares)
    cap = _cents(min(pick.get("stake", 0), budget_left), rounding=ROUND_DOWN)
    
    # Пытаемся набрать минимальный исполнимый лот
    leg_mp = mp._replace(min_shares=leg_min_shares)
    got = _walk_book(levels, leg_mp, leg_min_shares, cap, price_limit=execution_limit)
    if got is None:
        return dict(ok=False, shares=0.0, usd=0.0,
                   reason=f"в книге нет объёма на минимум ${mp.min_notional:g} / {leg_min_shares:g} акций")
    
    sh, usd, lim = got
    # Normalize shares to executable precision (1 decimal)
    sh_rounded = Decimal(str(round(float(sh), 1)))
    # Recompute cost from normalized shares
    ask_price = Decimal(str(lim))
    full_price = ask_price + Decimal(str(mp.fee_rate)) * ask_price * (1 - ask_price)
    usd_from_rounded = sh_rounded * full_price
    
    # Re-validate post-normalization: raw debit must meet min_notional, 
    # and shares must meet book minimum (which may be stricter than the normalized result)
    min_notional_exact = Decimal(str(mp.min_notional))
    if usd_from_rounded + EPS_MONEY < min_notional_exact:
        return dict(ok=False, shares=0.0, usd=0.0,
                   reason=f"после округления акций raw debit ${float(usd_from_rounded):.4f} < минимум ${mp.min_notional:g}")
    # Book min_order_size is in shares and must be met even after rounding
    if sh_rounded + EPS_MONEY < Decimal(str(book_min_shares)):
        return dict(ok=False, shares=0.0, usd=0.0,
                   reason=f"после округления акций {float(sh_rounded):.1f} < book min_order_size {book_min_shares}")
    # Recheck cap
    if usd_from_rounded > cap + EPS_MONEY:
        return dict(ok=False, shares=0.0, usd=0.0,
                   reason=f"после округления акций стоимость ${float(_cents(usd_from_rounded)):.2f} превышает лимит ${float(cap):.2f}")
    
    # Compute fee-inclusive EV if probability provided
    ev_final = None
    if probability is not None:
        # EV = (probability - full_price) / full_price
        ev_final = float((Decimal(str(probability)) - full_price) / full_price)
        if ev_final < SINGLE_MIN_EV - 1e-9:
            return dict(ok=False, shares=0.0, usd=0.0, ev_final=ev_final,
                       reason=f"EV после исполнения {ev_final*100:.1f}% < порог {SINGLE_MIN_EV*100:.0f}%")
    
    # Return conservative ceiling: ROUND_UP ensures reservation covers executable cost
    return dict(ok=True, shares=float(sh_rounded), usd=float(_cents(usd_from_rounded, rounding=ROUND_UP)), limit=lim,
              ev_final=ev_final, reason=None)


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
        
        # Без mp fail closed — не торгуем
        if mp_t is None:
            t["stake"] = 0.0
            t["budget_block"] = "нет торговых параметров рынка (mp отсутствует)"
            continue
        
        # Проверяем минимальный нотионал
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
        p_cons = t.get("p_cons")
        if p_cons is None and t.get("pLo") is not None and t.get("pHi") is not None:
            p_cons = (min(t["pLo"], t["pHi"]) if t.get("side") == "YES"
                      else 1-max(t["pLo"], t["pHi"]))
        exec_result = single_lot(t, mp_t, left, fetch, probability=p_cons)
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
    return approved

PM_WALLET = ""  # Не хранить адрес владельца в публичном репозитории.

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
    # Явный аргумент удобен для библиотечного вызова; scheduled-задача передаёт
    # публичный адрес через окружение. Ни ключей, ни подписи для data-api не нужно.
    wallet = wallet or os.environ.get("PM_WALLET", "").strip() or PM_WALLET
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
        # Только известные погодные бакеты моделируются как взаимоисключающие;
        # остальные позиции показываются списком без выдуманной таблицы исходов.
        exclusive = bool(re.match(r"(highest|lowest)-temperature-", slug or ""))
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

def reset_run_state():
    """A second in-process run must start clean, just like a new CLI process."""
    with _STATE_LOCK:
        for target in (SLOPPY, COMBOS, PAPER_FORECASTS,
                       RES_FAILS, POOL_FAILS, PARAM_FAILS):
            target.clear()
        RES_SEEN.clear()
        PARSE_FAIL[0] = 0

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

def make_paper_forecast(eslug, slug, city, weather_date, lead, kind, unit,
                        station, tier, resolution, rows, captured_at=None):
    """Зафиксировать полное распределение ДО известного исхода.

    Рынок и модель нормируются отдельно по полному набору бакетов.  Это
    позволяет потом честно сравнить p_model, p_shrunk и рынок proper-scoring
    метриками, даже если сумма сырых midpoint чуть отличается от единицы.
    """
    def normalized(key):
        values = [max(0.0, float(row[key])) for row in rows]
        total = sum(values)
        if total <= 0: raise ValueError(f"нулевая масса {key}")
        return [value / total for value in values]
    model = normalized("p")
    shrunk = normalized("pS")
    market = normalized("mid")
    buckets = []
    for index, row in enumerate(rows):
        buckets.append(dict(label=row["bucket"], lo=row["rng"][0], hi=row["rng"][1],
                            p_model=model[index], p_shrunk=shrunk[index],
                            p_market=market[index]))
    return dict(schema_version=1,
                captured_at=captured_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                event_slug=eslug, city_slug=slug, city=city,
                weather_date=weather_date, lead=lead, kind=kind, unit=unit,
                station=station, tier=tier,
                resolution_fingerprint=resolution["fingerprint"], buckets=buckets)

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
        with _STATE_LOCK:
            ok_res, det = check_resolution(eslug, ev.get("description"), unit, icao)
        if not ok_res:
            _state_append(RES_FAILS, f"{eslug}: {det['reason']}"); continue
        tier = cal_tier(cal, lead)
        bucket_markets = [m for m in ev["markets"] if parse_bucket(m.get("groupItemTitle"))]
        vol = float(ev.get("volume") or 0)
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
            _state_parse_fail(len(unparsed))
            _state_append(POOL_FAILS, f"{eslug}: нераспознанные бакеты ({len(unparsed)}) — пул не считаем")
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
            tid_yes = tid_no = None
            try:
                ti = m.get("clobTokenIds")
                ti = json.loads(ti) if isinstance(ti, str) else ti
                tid_yes = ti[0] if ti else None
                tid_no = ti[1] if ti and len(ti) > 1 else None
            except Exception: pass
            rows.append(dict(bucket=m.get("groupItemTitle"), rng=rng, bb=bb, ba=ba, mid=mid,
                             tid=tid_yes, tidYes=tid_yes, tidNo=tid_no,
                             p=p_raw, pLo=pLo_raw, pHi=pHi_raw, fams=fams_p))
        if incomplete:
            _state_append(POOL_FAILS, incomplete); continue
        if len(rows) < 3 or not coverage_ok([r["rng"] for r in rows]):
            _state_append(POOL_FAILS, f"{eslug}: распределение исходов неполное — усадку к рынку не считаем")
            continue
        # усадка к рынку: нормализованный лог-пул p^λ · q^(1−λ) по ПОЛНОМУ набору бакетов
        for r, sh in zip(rows, log_pool(rows)):
            r["pS"], r["pLoS"], r["pHiS"] = sh["p"], sh["pLo"], sh["pHi"]
        _state_append(PAPER_FORECASTS, make_paper_forecast(
            eslug, slug, ru, ds, lead, kind, unit, icao, tier, det, rows))
        # Ликвидность и торговые параметры запрещают реальную рекомендацию, но
        # не должны создавать survivorship bias в оценке вероятностной модели.
        if vol < 10000: continue
        # Торговые параметры КОНКРЕТНОГО рынка нужны только после того, как
        # независимый бумажный снимок уже сохранён. Торговля остаётся fail-closed.
        mp = event_params(bucket_markets, fetch, enrich_clob=False)
        if mp is None:
            _state_append(PARAM_FAILS, f"{eslug}: торговые параметры рынка не подтверждены"); continue
        allasks = [m.get("bestAsk") for m in bucket_markets]
        if len(allasks) >= 5 and all(a is not None for a in allasks):
            _state_append(SLOPPY, dict(city=ru, date=ds, sum_ask=round(sum(allasks), 3),
                                      sum_allin=round(sum(allin(a, mp) for a in allasks), 3), eslug=eslug))
        crows = []
        for r in rows:
            bb, ba, mid = r["bb"], r["ba"], r["mid"]
            pS, pLoS, pHiS = r["pS"], r["pLoS"], r["pHiS"]
            fv = list(r["fams"].values())
            base = dict(city=ru, slug=slug, date=ds, lead=lead, bucket=r["bucket"],
                        p=round(pS,3), p_model=round(r["p"],3), mid=round(mid,3),
                        pLo=round(pLoS,3), pHi=round(pHiS,3),
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
                                       stake=kelly_stake(pS, min(pLoS, pHiS), c), mp=mp,
                                       token_id=r["tidYes"], p_cons=min(pLoS, pHiS)))
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
                                   stake=kelly_stake(1-pS, 1-max(pLoS, pHiS), c), mp=mp,
                                   token_id=r["tidNo"], p_cons=1-max(pLoS, pHiS)))
        for st in chance_combos(crows, mp):
            _state_append(COMBOS, dict(st, city=ru, date=ds, lead=lead, vol=int(vol), tier=tier,
                                      mp=mp, link=f"https://polymarket.com/event/{eslug}"))
    return trades

def selected_city_slugs(slugs, calibrations, include_tier_c=False):
    """Select the pre-outcome A/B universe used by the daily trading scan.

    Tier C calibration remains in the report, but its expensive ensemble and
    market pass is opt-in.  Selection uses only historical calibration quality,
    never the current outcome or current model edge.
    """
    slugs = list(slugs)
    if include_tier_c:
        return slugs
    selected = []
    for slug in slugs:
        cal = calibrations.get(slug) or {}
        tiers = (cal.get("tiers") or {}).values()
        if cal.get("tier") in ("A", "B") or any(tier in ("A", "B") for tier in tiers):
            selected.append(slug)
    return selected


def selected_weather_dates(dates, calibration, include_tier_c=False):
    if include_tier_c:
        return list(dates)
    return [(lead, value) for lead, value in dates
            if cal_tier(calibration, lead) in ("A", "B")]


def calibration_refresh_plan(slugs, previous, on_date, refresh_days=7,
                             include_tier_c=False):
    """Refresh prior A/B daily and rotate non-traded C cities over a week."""
    slugs = list(slugs)
    previous = previous or {}
    if include_tier_c or any(not isinstance(previous.get(slug), dict) for slug in slugs):
        return slugs, {}
    bucket = on_date.toordinal() % refresh_days
    refresh, carry = [], {}
    for slug in slugs:
        old = previous[slug]
        old_tiers = (old.get("tiers") or {}).values()
        reliable = old.get("tier") in ("A", "B") or any(
            tier in ("A", "B") for tier in old_tiers)
        stable_bucket = int(hashlib.sha256(slug.encode("utf-8")).hexdigest()[:8], 16) % refresh_days
        if reliable or stable_bucket == bucket:
            refresh.append(slug)
        else:
            carry[slug] = dict(old)
    return refresh, carry


def build_report(fetch=None, workers=None, include_tier_c=False,
                 progress=None, prior_report=None):
    started = time.monotonic()
    production_fetcher = None
    if fetch is None:
        production_fetcher = RunFetcher(get)
        fetch = production_fetcher
        workers = runtime_workers(workers)
    else:
        # Offline/injected callers remain deterministic unless they explicitly
        # opt into concurrency.
        workers = runtime_workers(1 if workers is None else workers)
    reset_run_state()
    now = datetime.now(timezone.utc)
    dates = [(1, (now+timedelta(days=1)).strftime("%Y-%m-%d")), (2, (now+timedelta(days=2)).strftime("%Y-%m-%d"))]
    prior_calib_json = (prior_report or {}).get("calib_json") or {}
    prior_max = prior_calib_json.get("cities") or {}
    prior_min = prior_calib_json.get("cities_min") or {}
    prior_date = prior_calib_json.get("cal_date")
    refresh_max, carried_max = calibration_refresh_plan(
        ST, prior_max, now.date(), include_tier_c=include_tier_c)
    refresh_min, carried_min = calibration_refresh_plan(
        MIN_SLUGS, prior_min, now.date(), include_tier_c=include_tier_c)
    for value in list(carried_max.values()) + list(carried_min.values()):
        value["carried_from"] = prior_date
    calib, trades, errors = dict(carried_max), [], []
    stage_times = {}
    progress_lock = threading.Lock()
    progress_counts = {}

    def begin_stage(name, total=None):
        progress_counts[name] = 0
        if progress:
            progress(dict(stage=name, completed=0, total=total))
        return time.monotonic()

    def finish_item(name, total):
        if not progress: return
        with progress_lock:
            progress_counts[name] += 1
            completed = progress_counts[name]
        progress(dict(stage=name, completed=completed, total=total))

    def finish_stage(name, stage_started):
        stage_times[name] = round(time.monotonic()-stage_started, 2)

    def calibrate_max(slug):
        try:
            return slug, calibrate(slug, fetch=fetch), None
        except Exception as e:
            fallback = dict(fams={"1": {}, "2": {}}, bias=REF_BIAS.get(slug,0.0), n=0, std=None,
                            tier="C", tiers={"1": "C", "2": "C"})
            return slug, fallback, f"calib {slug}: {e}"
        finally:
            finish_item("calibration_max", len(refresh_max))

    stage_started = begin_stage("calibration_max", len(refresh_max))
    for slug, value, error in _parallel_map(calibrate_max, refresh_max, workers):
        calib[slug] = value
        if error: errors.append(error)
    finish_stage("calibration_max", stage_started)

    screen_max_slugs = selected_city_slugs(ST, calib, include_tier_c)

    def screen_max(slug):
        try:
            scoped_dates = selected_weather_dates(dates, calib[slug], include_tier_c)
            return screen(slug, calib[slug], scoped_dates, fetch=fetch), None
        except Exception as e:
            return [], f"screen {slug}: {e}"
        finally:
            finish_item("weather_max", len(screen_max_slugs))

    stage_started = begin_stage("weather_max", len(screen_max_slugs))
    for rows, error in _parallel_map(screen_max, screen_max_slugs, workers):
        trades += rows
        if error: errors.append(error)
    finish_stage("weather_max", stage_started)

    calib_min = dict(carried_min)

    def calibrate_min(slug):
        try:
            return slug, calibrate(slug, is_min=True, fetch=fetch), None
        except Exception as e:
            fallback = dict(fams={"1": {}, "2": {}}, bias=REF_BIAS_MIN.get(slug,0.0), n=0, std=None,
                            tier="C", tiers={"1": "C", "2": "C"})
            return slug, fallback, f"calib_min {slug}: {e}"
        finally:
            finish_item("calibration_min", len(refresh_min))

    stage_started = begin_stage("calibration_min", len(refresh_min))
    for slug, value, error in _parallel_map(calibrate_min, refresh_min, workers):
        calib_min[slug] = value
        if error: errors.append(error)
    finish_stage("calibration_min", stage_started)

    screen_min_slugs = selected_city_slugs(MIN_SLUGS, calib_min, include_tier_c)

    def screen_min(slug):
        try:
            scoped_dates = selected_weather_dates(dates, calib_min[slug], include_tier_c)
            return screen(slug, calib_min[slug], scoped_dates, kind="min", fetch=fetch), None
        except Exception as e:
            return [], f"screen_min {slug}: {e}"
        finally:
            finish_item("weather_min", len(screen_min_slugs))

    stage_started = begin_stage("weather_min", len(screen_min_slugs))
    for rows, error in _parallel_map(screen_min, screen_min_slugs, workers):
        trades += rows
        if error: errors.append(error)
    finish_stage("weather_min", stage_started)

    stage_started = begin_stage("execution", None)
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
            mpx = event_params(bms, fetch, enrich_clob=False)
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
    finish_stage("execution", stage_started)

    # «Вердикт дня»: по одной самой реальной ставке на категорию — или честный пропуск
    def wx_verdict(combo, ps):
        if combo is not None:
            return dict(combo, kind="серия-комбо" if combo is series else "шанс-комбо")
        p = next((t for t in ps if t["conf"] >= 5 and t.get("robust") and (t.get("stake") or 0) > 0), None)
        if p: return dict({k: v for k, v in p.items() if k not in ("tid",)}, kind="одиночная")
        return None
    verdicts = dict(
        max=wx_verdict(approved["max"], [t for t in picks if "(мин)" not in t["city"]]),
        min=wx_verdict(approved["min"], [t for t in picks if "(мин)" in t["city"]]),
    )
    budget = allocator.snapshot()
    budget["rejections"] = [dict(city=c["city"], date=c["date"], buckets=c["buckets"],
                                 why=c.get("exec_why") or "не выбран")
                            for c in combo_top if not c.get("exec_ok")][:10]
    stage_started = begin_stage("finalize", None)
    html_health = dict(coverage=check_coverage(fetch), parse_fails=PARSE_FAIL[0])
    paper_forecasts = sorted(
        PAPER_FORECASTS,
        key=lambda row: (row.get("weather_date", ""), row.get("kind", ""),
                         row.get("city_slug", ""), row.get("event_slug", "")))
    finish_stage("finalize", stage_started)
    report = dict(
        generated=now.strftime("%Y-%m-%d %H:%M UTC"),
        bankroll=BANKROLL, day_limit=DAY_LIMIT, min_order=MIN_ORDER,
        budget=budget, portfolio=portfolio,
        model_policy=dict(lambda_model=LAMBDA,
                          fee="тейкер: rate·цена·(1−цена) с акции, rate берётся из параметров конкретного рынка",
                          min_leg_ask=0.03, combo_min_ev=COMBO_MIN_EV, combo_min_legs=COMBO_MIN_LEGS,
                          note="фаза валидации: усадка к рынку, дешёвые хвосты запрещены"),
        res_checks=sorted(RES_FAILS), pool_checks=sorted(POOL_FAILS), param_checks=sorted(PARAM_FAILS),
        verdicts=verdicts,
        calib_json=dict(cal_date=now.strftime("%Y-%m-%d"), cities=calib, cities_min=calib_min),
        picks=picks[:12], watch=watch[:10], chance_combos=combo_top[:10], series_pick=series,
        bias_drift_over_1C=drift, errors=errors,
        pure_arb=pure_arb, most_inefficient=sloppy[:5],
        html_health=html_health, paper_forecasts=paper_forecasts,
        runtime=dict(workers=workers,
                     elapsed_seconds=round(time.monotonic()-started, 2),
                     stages=stage_times,
                     network=(production_fetcher.stats() if production_fetcher else None),
                     scope=dict(include_tier_c=bool(include_tier_c),
                                refreshed_max_calibrations=len(refresh_max),
                                carried_max_tier_c=sorted(carried_max),
                                included_max_cities=len(screen_max_slugs),
                                included_max_city_days=sum(len(selected_weather_dates(
                                    dates, calib[slug], include_tier_c)) for slug in screen_max_slugs),
                                skipped_max_tier_c=sorted(set(ST)-set(screen_max_slugs)),
                                refreshed_min_calibrations=len(refresh_min),
                                carried_min_tier_c=sorted(carried_min),
                                included_min_cities=len(screen_min_slugs),
                                included_min_city_days=sum(len(selected_weather_dates(
                                    dates, calib_min[slug], include_tier_c)) for slug in screen_min_slugs),
                                skipped_min_tier_c=sorted(set(MIN_SLUGS)-set(screen_min_slugs))),
                     bulk_weather_optional_clob_enrichment=False),
    )
    return report


def main(fetch=None, workers=None, include_tier_c=False):
    print(json.dumps(build_report(fetch=fetch, workers=workers,
                                  include_tier_c=include_tier_c),
                     ensure_ascii=False, indent=1))

if __name__ == "__main__":
    main()
