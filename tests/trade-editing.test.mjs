import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { calculateSpotLedger } from "../spot-calculation.mjs";
import { openingLotsForPosition, openingQuantityChangeError } from "../trade-editing.mjs";

const buy = (id, date, quantity, extra = {}) => ({ id, date, createdAt: extra.createdAt ?? 1, code: "1234", name: "テスト", action: "買付", accountType: extra.accountType ?? "現物", style: extra.style ?? "スイング", price: extra.price ?? 1000, quantity, ...extra });
const sell = (id, date, quantity, extra = {}) => ({ id, date, createdAt: extra.createdAt ?? 2, code: "1234", name: "テスト", action: "売却", accountType: extra.accountType ?? "現物", style: extra.style ?? "スイング", price: extra.price ?? 1100, quantity, ...extra });

test("ケースA: 現物の複数買付はFIFO残株を付けず両方を編集候補にする", () => {
  const trades = [
    buy("b1", "2026-08-01", 100, { price: 1000 }),
    buy("b2", "2026-08-02", 100, { price: 990 }),
    sell("s1", "2026-08-03", 100)
  ];
  const lots = openingLotsForPosition(trades, "1234", "現物");
  assert.deepEqual(lots.map((lot) => lot.openingTradeId), ["b1", "b2"]);
  assert.ok(lots.every((lot) => lot.remainingQuantity === null && lot.committedQuantity === null));
});

test("ケースB: 全売却後の再買付だけを現在の保有サイクル候補にする", () => {
  const trades = [
    buy("old", "2026-01-01", 100),
    sell("closed", "2026-01-10", 100),
    buy("current", "2026-02-01", 100)
  ];
  assert.deepEqual(openingLotsForPosition(trades, "1234", "現物").map((lot) => lot.openingTradeId), ["current"]);
});

test("ケースC: 現物数量変更はFIFOでなくSBI準拠ledgerの時系列整合性で判定する", () => {
  const trades = [buy("b1", "2026-08-01", 100), buy("b2", "2026-08-02", 100), sell("s1", "2026-08-03", 150)];
  const valid = trades.map((trade) => trade.id === "b1" ? { ...trade, quantity: 60 } : trade);
  const invalid = trades.map((trade) => trade.id === "b1" ? { ...trade, quantity: 40 } : trade);
  assert.equal(openingQuantityChangeError(trades, "b1", 40), "");
  assert.equal(calculateSpotLedger(valid).invalid, null);
  assert.match(calculateSpotLedger(invalid).invalid, /保有株数を10株超えて売却/);
});

test("ケースD: 信用返済の建玉割当と残株数を維持する", () => {
  const trades = [
    buy("b1", "2026-08-01", 100, { accountType: "信用" }),
    buy("b2", "2026-08-02", 200, { accountType: "信用" }),
    sell("s1", "2026-08-03", 150, { accountType: "信用", positionAllocations: [{ openingTradeId: "b1", quantity: 100 }, { openingTradeId: "b2", quantity: 50 }] })
  ];
  const lots = openingLotsForPosition(trades, "1234", "信用");
  assert.deepEqual(lots.map((lot) => [lot.openingTradeId, lot.remainingQuantity]), [["b2", 150]]);
});

test("信用の返済済み数量を下回る変更だけを事前に拒否する", () => {
  const credit = [buy("c1", "2026-08-01", 1000, { accountType: "信用" }), sell("cs1", "2026-08-02", 800, { accountType: "信用", positionAllocations: [{ openingTradeId: "c1", quantity: 800 }] })];
  assert.equal(openingQuantityChangeError(credit, "c1", 799), "すでに800株返済済みのため、買付株数を800株未満には変更できません。");
  assert.equal(openingQuantityChangeError(credit, "c1", 800), "");
});

test("現物候補説明と既存編集・画面トップ遷移を維持する", async () => {
  const [appSource, indexSource, styleSource] = await Promise.all([
    readFile(new URL("../app.js", import.meta.url), "utf8"),
    readFile(new URL("../index.html", import.meta.url), "utf8"),
    readFile(new URL("../styles.css", import.meta.url), "utf8")
  ]);
  assert.match(appSource, /const changed = state\.activeView !== view/);
  assert.match(appSource, /if \(changed\) requestAnimationFrame\(\(\) => window\.scrollTo/);
  assert.match(appSource, /現物は平均取得単価で管理するため、買付ごとの残株数は表示しません/);
  assert.match(appSource, /const choiceState = isCredit \? .*残り/);
  assert.match(appSource, /openBuy\(lots\[0\]\.trade\)/);
  assert.match(appSource, /if \(formMode === "edit"\) await setDoc/);
  assert.match(indexSource, /id="position-lot-description"/);
  assert.match(styleSource, /\.position-row-main:active/);
});
