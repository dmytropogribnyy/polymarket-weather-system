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
   resolution station in the description. Stations are verified manually
   when a city is added (hardcoded in `ST`), and at runtime every market
   passes a fail-closed check: resolution source (Wunderground/NOAA/NWS)
   and units must match the model, otherwise the market is skipped and
   reported. The station-vs-downtown gap is half the edge.
2. **Calibration v2 (lead-matched, per model family).** The forecast *as it
   stood 24h and 48h before the day* (Open-Meteo Previous Runs API,
   `previous_day1/2`) vs actual METAR maxima, separately for each of the four
   model families — ECMWF's bias is NOT transferred to GFS/ICON/GEM (in
   Munich they differ by 2°C). Per-family bias/std/SE; tiers A/B/C from the
   worst family (tier C is not tradable).
3. **Probability v2.** A 143-member super-ensemble (ECMWF + GFS + ICON + GEM):
   equal weight per family, each member shifted by its own family's bias,
   smoothed with a kernel τ² = max(0.36, std² − ensemble-spread²) — residual
   uncertainty only, no double counting. Then shrunk toward market prices via
   a normalized log-pool p^λ·q^(1−λ) with λ = 0.25 (model weight) during the
   validation phase; both the raw and the shrunk probability are logged.
4. **Robustness.** Everything is recomputed with each family's bias shifted by
   ± its standard error (std/√n — the uncertainty of the mean, not the daily
   spread). A signal counts only if the edge survives both stress runs.
5. **Fees.** Polymarket charges a taker fee of 0.05·price·(1−price) per share
   on weather markets (verified against real fills to the 4th decimal). All
   economics — filters, EV, Kelly, combos, both arbitrage detectors — use
   all-in prices. Legs cheaper than 3¢ are banned during validation.
6. **Sizing & budget.** Quarter-Kelly on a conservative probability, capped by
   order-book depth and by a code-enforced budget: $5/day across all weather
   entries, $15/day total, computed from actual purchases on the wallet.
7. **Execution.** A book-walk computes executable lots per leg (fees included),
   honoring the $1 minimum order and rejecting thin-book legs; the combo's EV
   is recomputed after leg drops (`ev_final`) and rejected if it decays.
8. **Portfolio feedback.** The daily job reads open positions via the public
   data API (read-only, wallet address only), computes the per-outcome payoff
   table for every open event, tracks today's spend against the daily limit,
   flags recommendations that conflict with held positions, and reminds about
   unredeemed winnings.

Details, formulas and thresholds: `docs/METHODOLOGY.md`.

## Current state

The system went through an external review on 2026-08-02 which found a real
calibration-horizon error and undeclared taker fees; the review's NO-GO was
accepted and the probability layer was rebuilt the same day. See
`docs/REVIEW_RESPONSE.md` for the point-by-point verification and changes.

Bankroll ~$100, validation phase: $5/day weather cap inside a $15/day total,
probabilities shrunk toward the market (λ=0.25), skip-days are the norm.
Limits rise only after 30 journaled bets confirm calibration. See
`docs/JOURNAL.md` — the first resolution was a miss, duly recorded.

## Why this repository is public

So that another model (or a human) can be given a link and asked to attack
the methodology. The most painful spots are collected in
`docs/OPEN_QUESTIONS.md` — ten specific questions with the failure modes I
suspect. If you were asked to review this system, start there, and please
respond with formulas and testable claims rather than generic advice.
