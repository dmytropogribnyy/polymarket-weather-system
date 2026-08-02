#!/usr/bin/env node
/* Синтаксическая проверка веб-скринеров: скрипт внутри HTML обязан парситься.
 * Битую страницу нельзя заметить глазами — она просто молча ничего не считает.
 * Запуск: node tests/parity/check_syntax.js
 */
"use strict";
const fs = require("fs");
const path = require("path");

const WEB = path.resolve(__dirname, "..", "..", "web");
const files = fs.readdirSync(WEB).filter(f => f.endsWith(".html"));
if (!files.length){
  console.error("В web/ нет ни одной страницы — проверять нечего");
  process.exit(1);
}
let bad = 0;
for (const f of files){
  const src = fs.readFileSync(path.join(WEB, f), "utf8");
  const blocks = src.match(/<script>[\s\S]*?<\/script>/g) || [];
  for (const b of blocks){
    const code = b.replace(/^<script>/, "").replace(/<\/script>$/, "");
    try {
      new Function(code);
    } catch (e){
      console.error(`${f}: синтаксическая ошибка — ${e.message}`);
      bad++;
    }
  }
  console.log(`${f}: скриптов ${blocks.length} — ок`);
}
process.exit(bad ? 1 : 0);
