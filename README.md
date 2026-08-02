# Polymarket weather system

A system for finding gaps between Polymarket crowd prices and probabilities
computed from meteorological ensembles. Three circuits: temperature markets
(the core), earthquake-count markets, and crypto price markets.

One idea underneath everything: **profit is the gap between the market price
and the true probability.** Forecast accuracy by itself earns nothing — it is
merely the ticket to play. Only the mispricing pays.

## What's inside

```
src/wx_daily.py      main scanner: station calibration, probabilities, combo
                     construction, Kelly stake sizing, executable lots,
                     portfolio check, verdict of the day
src/watchdog.py      6-hourly watchdog: fresh large earthquakes, arbitrage
                     signals in circuits #2 and #3
src/check_city.py    spot-check one city: python3 check_city.py chengdu 2026-08-03

web/weather_screener.html   standalone browser screener, 48 cities
web/quake_screener.html     earthquake-count screener (Poisson vs USGS)
web/crypto_screener.html    BTC/ETH above-$K vs Deribit options surface

docs/METHODOLOGY.md    how probabilities and stake sizes are actually computed
docs/OPEN_QUESTIONS.md the places where I am not sure I'm right (start here)
docs/JOURNAL.md        real bets and outcomes
docs/tasks/            prompts of the two scheduled jobs that run the system
```

The HTML files are fully self-contained: download, open in a browser, press
the button. No server, no build step, no API keys. The Python scripts use the
standard library only — zero dependencies.

Docs are written in Russian (the project's working language). The code
comments are Russian too; the code itself is short and readable regardless.

## How it works in one minute

1. **Resolution station.** Every Polymarket weather market names its
   resolution station in the description ("recorded at Chengdu Shuangliu
   International Airport"). We model that exact station — not "the city's
   weather". This is half the edge, because the crowd looks at the
   downtown forecast in a phone app.
2. **Calibration.** Take the station's actual METAR daily maxima for the last
   10 days and the archived ECMWF forecasts for the same days. The mean
   difference is the station's systematic bias; the spread of differences is
   the trust measure. Three trust tiers: A, B, C (tier C is not tradable).
3. **Probability.** A 143-member super-ensemble (ECMWF + GFS + ICON + GEM),
   each member shifted by the station bias, smoothed with a normal kernel,
   integrated over the market's bucket boundaries.
4. **Robustness.** Everything is recomputed with the bias shifted by ± its
   own spread. A signal counts only if the edge survives both stress runs.
5. **Sizing.** Quarter-Kelly on a conservative probability blend, capped by
   the daily limit and by the real order-book depth.
6. **Execution.** A book-walk computes executable lots per leg, honoring
   Polymarket's $1 minimum order and rejecting legs where filling $1 would
   cost over 1.5× the best ask (thin book).
7. **Portfolio feedback.** The daily job reads open positions via the public
   data API (read-only, wallet address only), computes the per-outcome payoff
   table for every open event, tracks today's spend against the daily limit,
   flags recommendations that conflict with held positions, and reminds about
   unredeemed winnings.

Details, formulas and thresholds: `docs/METHODOLOGY.md`.

## Current state

Bankroll $100, daily limit $15 — model-validation phase. The limit rises to
$25 only after 30 journaled bets confirm the model's calibration. Very few
resolutions so far; see `docs/JOURNAL.md` (the first one was a miss, which is
duly recorded).

## Why this repository is public

So that another model (or a human) can be given a link and asked to attack
the methodology. The most painful spots are collected in
`docs/OPEN_QUESTIONS.md` — ten specific questions with the failure modes I
suspect. If you were asked to review this system, start there, and please
respond with formulas and testable claims rather than generic advice.
