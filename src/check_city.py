#!/usr/bin/env python3
"""Точечная живая проверка города: python3 check_city.py <slug> [YYYY-MM-DD]
Показывает: вероятности модели против цен рынка, 4 модели, кандидатов и глубину стакана."""
import json, sys, types
src = open('/home/claude/work/wx_daily.py').read()
head, _, tail = src.rpartition('main()')
wx = types.ModuleType('wx'); exec(head + 'pass' + tail, wx.__dict__)

from datetime import datetime, timedelta, timezone
slug = sys.argv[1]
date = sys.argv[2] if len(sys.argv) > 2 else (datetime.now(timezone.utc)+timedelta(days=1)).strftime("%Y-%m-%d")
if slug not in wx.ST:
    print("город не найден; доступны:", ", ".join(wx.ST)); sys.exit(1)
cal = wx.calibrate(slug)
lead = max(0, (datetime.strptime(date, "%Y-%m-%d").date() - datetime.now(timezone.utc).date()).days)
print(f"{wx.ST[slug][4]} на {date} (lead {lead}) | калибровка: bias {cal['bias']:+.2f} std {cal['std']} n={cal['n']} тир {cal['tier']}")
trades = wx.screen(slug, cal, [(lead, date)])
if not trades:
    print("кандидатов по фильтрам нет — смотри полную картину в скринере")
for t in sorted(trades, key=lambda x: -x["conf"]*x["ev"]):
    depth = ""
    if t.get("tid"):
        try:
            book = wx.get(f"https://clob.polymarket.com/book?token_id={t['tid']}")
            usd = 0.0
            if t["side"] == "YES":
                lim = t["cost"] + 0.006
                usd = sum(float(a["price"])*float(a["size"]) for a in book.get("asks",[]) if float(a["price"]) <= lim)
            else:
                lim = (1 - t["cost"]) - 0.006
                usd = sum((1-float(b["price"]))*float(b["size"]) for b in book.get("bids",[]) if float(b["price"]) >= lim)
            depth = f" | глубина ${usd:.0f}"
        except Exception: depth = " | глубина н/д"
    print(f"[{t['conf']}/5] {t['side']:>3} '{t['bucket']}' цена {t['cost']} | модель {t['p']:.0%} vs рынок {t['mid']:.0%} | EV/$1 {t['ev']:+.2f} | {t['fams']}{depth}")
