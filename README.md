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
src/paper_eval.py    append-only full-distribution archive and proper scoring
                     (log-loss, RPS, cheap tails, data-driven lambda)
src/watchdog.py      6-hourly watchdog: fresh large earthquakes, arbitrage
                     signals in circuits #2 and #3
src/check_city.py    spot-check one city: python3 check_city.py chengdu 2026-08-03

web/weather_screener.html   standalone browser screener, 48 cities
web/quake_screener.html     earthquake-count screener (Poisson vs USGS)
web/crypto_screener.html    BTC/ETH above-$K vs Deribit options surface

docs/METHODOLOGY.md    how probabilities and stake sizes are actually computed
docs/OPEN_QUESTIONS.md the places where I am not sure I'm right (start here)
docs/JOURNAL.md        real bets and outcomes
docs/REVIEW_RESPONSE.md what the external reviews asked for, and what was done
docs/tasks/            prompts of the scheduled jobs (copies for reading; the
                       jobs themselves live outside this repository)

tests/                 deterministic test suite, no network: every external API
                       is injected as a fake `fetch`
tests/parity/          the JS↔Python parity harness (extracts the PARITY-CORE
                       block straight out of web/weather_screener.html)
.github/workflows/     CI: syntax checks + the whole suite on every push and PR
```

The HTML files are fully self-contained: download, open in a browser, press
the button. No server, no build step, no API keys. The Python scripts use the
standard library only — zero dependencies.

Docs are written in Russian (the project's working language). The code
comments are Russian too; the code itself is short and readable regardless.

## How it works in one minute

1. **Resolution contract.** Every Polymarket weather market names its
   resolution rules in the description. At runtime the rules are parsed and
   validated fail-closed: source (Wunderground/NOAA/NWS), station (compared
   with the configured station of that city) and units must all be present,
   unambiguous and matching, and the rules must not have changed since the
   market was last seen. Anything else is NO BET, reported in `res_checks`.
   The station-vs-downtown gap is half the edge.
2. **Calibration v2 (lead-matched, per model family).** The forecast *as it
   stood 24h and 48h before the day* (Open-Meteo Previous Runs API,
   `previous_day1/2`) vs actual METAR maxima, separately for each of the four
   model families — ECMWF's bias is NOT transferred to GFS/ICON/GEM (in
   Munich they differ by 2°C). Per-family bias/std/SE; tiers A/B/C from the
   worst family (tier C is not tradable).
3. **Probability v2.** A 143-member super-ensemble (ECMWF + GFS + ICON + GEM):
   equal weight per family, each member shifted by its own family's bias,
   smoothed with a kernel τ² = max(0.36, std² − *historical* ensemble spread of
   the calibration window) — residual uncertainty only, and deliberately not
   today's spread, which would shrink the kernel exactly when the ensemble
   disagrees. Then shrunk toward market prices via a normalized log-pool
   p^λ·q^(1−λ) with λ = 0.25, computed **only over the complete mutually
   exclusive set of outcomes**: a missing or unrecognized bucket fails closed
   instead of renormalizing a partial subset to 1.
4. **Robustness.** Everything is recomputed with each family's bias shifted by
   ± its standard error (std/√n — the uncertainty of the mean, not the daily
   spread). A signal counts only if the edge survives both stress runs.
5. **Market-specific trading parameters.** Taker fee rate, tick size and
   minimum order are read from the concrete market (Gamma fields, falling back
   to CLOB by `conditionId`) — weather, earthquakes and crypto no longer share
   a hard-coded fee constant. Missing or insane values mean NO BET. All
   economics — filters, EV, Kelly, combos, arbitrage — use the resulting
   all-in price. Legs cheaper than 3¢ are banned during validation.
6. **Sizing & budget.** Quarter-Kelly on a conservative probability, capped by
   order-book depth and by one code-enforced allocator: $5 per **resolution
   (weather) date** shared by max, min and series recommendations alike —
   already executed positions of that date included — inside a $15/day total.
7. **Execution.** A decimal book-walk computes executable lots per leg (fees
   included), honoring the market's minimum order and rejecting thin-book legs.
   A combo is approved only after the lots exist: at least two surviving legs,
   fee-inclusive `ev_final` ≥ 0.10, and `total_usd` within the remaining
   budget. Every candidate is either approved or explicitly rejected with a
   reason — there is no "check only the first six" shortcut.
8. **Arbitrage, honestly.** "The asks sum to less than $1" is not arbitrage and
   is no longer presented as one anywhere: a set counts only when the all-in
   prices sum below $1 *and* the books hold enough volume for the minimum order
   on every leg.
9. **Portfolio feedback.** The daily job reads open positions via the public
   data API (read-only, wallet address only), computes the per-outcome payoff
   table for every open event, tracks today's spend against the daily limit,
   flags recommendations that conflict with held positions, and reminds about
   unredeemed winnings.

Details, formulas and thresholds: `docs/METHODOLOGY.md`.

## Tests

```
python3 -m unittest discover -s tests -t .   # everything, no network
node tests/parity/parity_test.js             # the JS core, standalone
node tests/parity/check_syntax.js            # the HTML screeners must parse
```

The suite is deterministic and offline by construction: production code takes a
`fetch` callable, tests inject a fake that raises on any URL it was not told
about, so a test that accidentally reaches the network fails instead of
flaking. The parity test pulls the calculation core out of
`web/weather_screener.html` and compares it with `src/wx_daily.py` number by
number — if the page and the nightly job drift apart, CI goes red.

## Paper evaluation (no money, no wallet)

Every complete weather market scanned by `wx_daily.py` is emitted in
`paper_forecasts` with the full mutually-exclusive distribution from the raw
model, the shrunk model and normalized market midpoints. Archive a daily run:

```
python src/wx_daily.py > report.json
python src/paper_eval.py capture report.json /persistent/path/paper_forecasts.jsonl
```

After final outcomes have been recorded, score every city-day rather than only
the legs that happened to become bets:

```
python src/paper_eval.py score /persistent/path/paper_forecasts.jsonl outcomes.json
```

The score report compares mean log-loss and normalized RPS, summarizes all
market buckets priced at 5¢ or less, and evaluates a fixed lambda grid. The
ledger is atomic and append-only: an exact retry is harmless, while changed
content for the same event and capture time is rejected.

## Current state

The system went through an external review on 2026-08-02 which found a real
calibration-horizon error and undeclared taker fees; the review's NO-GO was
accepted and the probability layer was rebuilt the same day. A second pass
closed the remaining safety blockers: one aggregate budget per resolution date,
executable-lot sizing in decimal arithmetic, verdicts gated on executable
economics, a fail-closed resolution contract, per-market trading parameters,
web/Python parity, and the model-safety invariants. See
`docs/REVIEW_RESPONSE.md` for the point-by-point status, including what was
deliberately **not** done.

Note on the scheduled jobs: they live outside this repository and are not
updated by any change here. Until the job is pointed at the current code, none
of the protections above are in effect for the nightly run.

Bankroll ~$100, validation phase: $5/day weather cap inside a $15/day total,
probabilities shrunk toward the market (λ=0.25), skip-days are the norm.
Limits rise only after enough independently settled city-days confirm
calibration; P&L alone is not evidence. See `docs/JOURNAL.md` and the paper
evaluation workflow above.

## Why this repository is public

So that another model (or a human) can be given a link and asked to attack
the methodology. The most painful spots are collected in
`docs/OPEN_QUESTIONS.md` — ten specific questions with the failure modes I
suspect. If you were asked to review this system, start there, and please
respond with formulas and testable claims rather than generic advice.
