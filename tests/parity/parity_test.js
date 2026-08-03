#!/usr/bin/env node
/* Паритет веб-скринера и ночного джоба.
 *
 * Скрипт ВЫДЁРГИВАЕТ расчётное ядро прямо из web/weather_screener.html (блок
 * между PARITY-CORE-START и PARITY-CORE-END), прогоняет общие кейсы из
 * parity_cases.json и печатает результат в JSON. tests/test_parity.py считает то
 * же самое на Python и сверяет числа и вердикты. Разъехались страница и джоб —
 * тест красный. Сети здесь нет: книги и параметры рынка лежат в кейсах.
 *
 * Запуск: node tests/parity/parity_test.js
 */
"use strict";
const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(__dirname, "..", "..");
const HTML = path.join(ROOT, "web", "weather_screener.html");
const CASES = path.join(__dirname, "parity_cases.json");

function loadCore(){
  const src = fs.readFileSync(HTML, "utf8");
  const a = src.indexOf("/* PARITY-CORE-START");
  const endMark = "/* PARITY-CORE-END */";
  const b = src.indexOf(endMark);
  if (a < 0 || b < 0 || b < a){
    throw new Error("В web/weather_screener.html нет блока PARITY-CORE — паритет проверять нечем");
  }
  const code = src.slice(a, b + endMark.length);
  if (/document\.|window\.|fetch\(/.test(code)){
    throw new Error("Ядро паритета обязано быть чистым: ни DOM, ни сети");
  }
  return new Function(code + "\nreturn PARITY_CORE;")();
}

const C = loadCore();
const cases = JSON.parse(fs.readFileSync(CASES, "utf8"));
const r = (x, n) => (x === null || x === undefined) ? null : Math.round(x*Math.pow(10, n))/Math.pow(10, n);
const mpOf = o => ({ fee_rate: o.fee_rate, tick: o.tick, min_notional: o.min_order,
                     min_shares: o.min_shares || 0, source: "case" });

const out = {};

out.market_params = cases.market_params.map(c => {
  const p = C.eventParams(c.markets);
  return { name: c.name, params: p === null ? null :
    { fee_rate: r(p.fee_rate, 12), tick: r(p.tick, 12), min_notional: r(p.min_notional, 12), min_shares: r(p.min_shares, 12) } };
});

out.prices = cases.prices.map(c => {
  const mp = mpOf(c.mp);
  return { price: c.price, fee: r(C.feeOf(c.price, mp), 12), allin: r(C.allin(c.price, mp), 12) };
});

out.fam_prob = cases.fam_prob.map(c => {
  const res = C.famProb(c.day, c.range[0], c.range[1], c.unit, c.fams, c.lead, c.dbias);
  const byFam = {};
  Object.keys(res.byFam).sort().forEach(k => { byFam[k] = r(res.byFam[k], 3); });
  return { name: c.name, p: res.p === null ? null : r(res.p, 6), by_fam: byFam };
});

out.log_pool = cases.log_pool.map(c => ({
  name: c.name,
  rows: C.logPool(c.rows).map(x => ({ p: r(x.p, 9), pLo: r(x.pLo, 9), pHi: r(x.pHi, 9) }))
}));

out.coverage = cases.coverage.map(c => ({ name: c.name, ok: C.coverageOk(c.ranges) }));

out.buckets = cases.buckets.map(t => ({ title: t, rng: C.parseBucket(t) }));

out.resolution = cases.resolution.map(c => {
  const seen = {};
  const steps = c.steps.map(s => {
    const [ok, info] = C.checkResolution(s.eslug, s.desc, c.unit, c.station, seen);
    return { ok, reason: info.reason === undefined ? null : info.reason,
             sources: info.sources || null, units: info.units || null,
             stations: info.stations || null, known_stations: info.known_stations || null };
  });
  return { name: c.name, steps };
});

out.kelly = cases.kelly.map(c => ({
  stake: r(C.kellyStake(c.p_base, c.p_cons, c.cost, c.bankroll, c.cap), 2)
}));

function execOf(step, mp, budgetLeft, books){
  if (!step) return null;
  // Преобразуем книги из массивов в структуру с метаданными
  const booksWithMeta = {};
  for (const tid in books){
    booksWithMeta[tid] = {
      levels: books[tid],
      min_order_size: 1,      // стандартное значение для тестовых книг
      tick_size: 0.01
    };
  }
  const ex = C.comboLots(step, mp, budgetLeft, booksWithMeta);
  return {
    ok: ex.ok, reason: ex.reason === undefined ? null : ex.reason,
    total_usd: r(ex.total_usd, 2), min_usd: ex.min_usd === null ? null : r(ex.min_usd, 2),
    ev_final: ex.ev_final === null || ex.ev_final === undefined ? null : r(ex.ev_final, 4),
    p_covered: r(ex.p_covered, 3), stake: r(ex.stake, 2), budget_left: r(ex.budget_left, 2),
    lots: (ex.lots || []).map(l => ({ bucket: l.bucket, limit: l.limit === null ? null : r(l.limit, 3),
                                      shares: r(l.shares, 1), usd: r(l.usd, 2) })),
    skipped: (ex.skipped || []).map(s => ({ bucket: s.bucket, why: s.why }))
  };
}

out.combo_lots = cases.combo_lots.map(c => ({
  name: c.name, exec: execOf(c.step, mpOf(c.mp), c.budget_left, c.books)
}));

out.arb = cases.arb.map(c => {
  // Преобразуем книги из массивов в структуру с метаданными
  const booksWithMeta = {};
  for (const tid in c.books){
    booksWithMeta[tid] = {
      levels: c.books[tid],
      min_order_size: 1,
      tick_size: 0.01
    };
  }
  const res = C.checkArbLegs(c.legs.map(t => [t]), mpOf(c.mp), booksWithMeta);
  return { name: c.name, ok: res.ok, why: res.why === undefined ? null : res.why,
           exec_sets: res.exec_sets, exec_cost: r(res.exec_cost, 3), exec_profit: r(res.exec_profit, 2) };
});

out.chance_combos = cases.chance_combos.map(c => {
  const rows = { buckets: c.rows.map(x => ({ title: x.bucket, lo: x.lo, p: x.p, pLo: x.pLo, pHi: x.pHi,
                                             ask: x.ask, tid: x.tid })) };
  const steps = C.chanceCombos(rows, mpOf(c.mp));
  return { name: c.name, steps: steps.map(s => ({
    buckets: s.buckets.map(b => b.title), cost: r(s.cost, 3), p_win: r(s.pWin, 3),
    p_rng: [r(Math.min(s.pLo, s.pHi), 2), r(Math.max(s.pLo, s.pHi), 2)] })) };
});

out.verdict = cases.verdict.map(c => {
  const mp = mpOf(c.mp);
  // Преобразуем книги из массивов в структуру с метаданными
  const booksWithMeta = c.books ? {} : null;
  if (c.books){
    for (const tid in c.books){
      booksWithMeta[tid] = {
        levels: c.books[tid],
        min_order_size: 1,
        tick_size: 0.01
      };
    }
  }
  const ex = c.step ? C.comboLots(c.step, mp, c.budget_left, booksWithMeta) : null;
  const [ok, why] = C.approveCombo(ex, c.budget_left);
  return { name: c.name, verdict: ok ? "BET" : "NO BET", why,
           total_usd: ex && ex.ok ? r(ex.total_usd, 2) : null,
           ev_final: ex && ex.ok ? r(ex.ev_final, 4) : null };
});

process.stdout.write(JSON.stringify(out, null, 1));
