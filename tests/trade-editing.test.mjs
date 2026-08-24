import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { openingLotsForPosition, openingQuantityChangeError, openingTradeUsage } from "../trade-editing.mjs";

const buy = (id, date, quantity, extra = {}) => ({ id, date, createdAt: extra.createdAt ?? 1, code: "1234", name: "テスト", action: "買付", accountType: extra.accountType ?? "現物", price: extra.price ?? 1000, quantity, ...extra });
const sell = (id, date, quantity, extra = {}) => ({ id, date, createdAt: extra.createdAt ?? 2, code: "1234", name: "テスト", action: "売却", accountType: extra.accountType ?? "現物", price: extra.price ?? 1100, quantity, ...extra });

test("現物の一部売却後も元の買付記録と残株数を取得する", () => {
  const trades = [buy("b1", "2026-08-01", 1000), sell("s1", "2026-08-02", 400)];
  const lots = openingLotsForPosition(trades, "1234", "現物");
  assert.equal(lots.length, 1);
  assert.equal(lots[0].openingTradeId, "b1");
  assert.equal(lots[0].remainingQuantity, 600);
  assert.equal(lots[0].committedQuantity, 400);
});

test("現物の複数買付は古い買付から売却分を充当し、残る買付を個別表示する", () => {
  const trades = [
    buy("b1", "2026-08-01", 100, { price: 1000 }),
    buy("b2", "2026-08-02", 200, { price: 990 }),
    sell("s1", "2026-08-03", 150)
  ];
  const usage = openingTradeUsage(trades);
  assert.equal(usage.get("b1").remainingQuantity, 0);
  assert.equal(usage.get("b2").remainingQuantity, 150);
  assert.deepEqual(openingLotsForPosition(trades, "1234", "現物").map((lot) => lot.openingTradeId), ["b2"]);
});

test("信用返済の建玉割当から各買付の残株数を維持する", () => {
  const trades = [
    buy("b1", "2026-08-01", 100, { accountType: "信用" }),
    buy("b2", "2026-08-02", 200, { accountType: "信用" }),
    sell("s1", "2026-08-03", 150, { accountType: "信用", positionAllocations: [{ openingTradeId: "b1", quantity: 100 }, { openingTradeId: "b2", quantity: 50 }] })
  ];
  const lots = openingLotsForPosition(trades, "1234", "信用");
  assert.deepEqual(lots.map((lot) => [lot.openingTradeId, lot.remainingQuantity]), [["b2", 150]]);
});

test("売却・返済済み数量を下回る買付数量変更を分かりやすく拒否する", () => {
  const spot = [buy("b1", "2026-08-01", 1000), sell("s1", "2026-08-02", 800)];
  assert.equal(openingQuantityChangeError(spot, "b1", 500), "すでに800株売却済みのため、買付株数を800株未満には変更できません。");
  assert.equal(openingQuantityChangeError(spot, "b1", 800), "");
  const credit = [buy("c1", "2026-08-01", 1000, { accountType: "信用" }), sell("cs1", "2026-08-02", 800, { accountType: "信用", positionAllocations: [{ openingTradeId: "c1", quantity: 800 }] })];
  assert.equal(openingQuantityChangeError(credit, "c1", 799), "すでに800株返済済みのため、買付株数を800株未満には変更できません。");
});

test("主要画面の変更時だけトップへ戻し、保有から既存編集を開く", async () => {
  const [appSource, indexSource, styleSource] = await Promise.all([
    readFile(new URL("../app.js", import.meta.url), "utf8"),
    readFile(new URL("../index.html", import.meta.url), "utf8"),
    readFile(new URL("../styles.css", import.meta.url), "utf8")
  ]);
  assert.match(appSource, /const changed = state\.activeView !== view/);
  assert.match(appSource, /if \(changed\) requestAnimationFrame\(\(\) => window\.scrollTo/);
  assert.match(appSource, /data-action="open-position-buys"/);
  assert.match(appSource, /openBuy\(lots\[0\]\.trade\)/);
  assert.match(appSource, /closePositionLotModal\(\); openBuy\(trade\)/);
  assert.match(appSource, /if \(formMode === "edit"\) await setDoc/);
  assert.match(indexSource, /id="position-lot-backdrop"/);
  assert.match(styleSource, /\.position-row-main:active/);
});
