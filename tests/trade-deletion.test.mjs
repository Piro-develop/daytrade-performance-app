import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { calculateSpotLedger } from "../spot-calculation.mjs";
import { deleteTradeOnce, validateTradeDeletion } from "../trade-deletion.mjs";

const BUY = "\u8cb7\u4ed8";
const SELL = "\u58f2\u5374";
const SPOT = "\u73fe\u7269";
const CREDIT = "\u4fe1\u7528";

const trade = (id, action, accountType, date, quantity, extra = {}) => ({
  id,
  code: "1234",
  name: "\u30c6\u30b9\u30c8",
  market: "\u6771\u8a3c\u30d7\u30e9\u30a4\u30e0",
  style: "\u30b9\u30a4\u30f3\u30b0",
  action,
  accountType,
  date,
  price: action === BUY ? 1000 : 1100,
  quantity,
  createdAt: extra.createdAt ?? Date.parse(date),
  ...extra
});

function calculateTestLedger(trades) {
  const spot = calculateSpotLedger(trades.filter((item) => item.accountType !== CREDIT));
  if (spot.invalid) return { invalid: spot.invalid, positions: spot.positions, openCreditLots: [] };

  const lots = new Map();
  let invalid = null;
  [...trades].filter((item) => item.accountType === CREDIT).sort((a, b) => a.date.localeCompare(b.date) || a.createdAt - b.createdAt).forEach((item) => {
    if (invalid) return;
    if (item.action === BUY) {
      lots.set(item.id, { id: item.id, remainingQuantity: Number(item.quantity) });
      return;
    }

    let allocations = Array.isArray(item.positionAllocations) ? item.positionAllocations : [];
    if (!allocations.length) {
      let remaining = Number(item.quantity);
      allocations = [...lots.values()].flatMap((lot) => {
        const quantity = Math.min(remaining, lot.remainingQuantity);
        remaining -= quantity;
        return quantity > 0 ? [{ openingTradeId: lot.id, quantity }] : [];
      });
    }
    const total = allocations.reduce((sum, allocation) => sum + Number(allocation.quantity), 0);
    if (total !== Number(item.quantity)) { invalid = "\u4fe1\u7528\u5efa\u7389\u6570\u91cf\u304c\u4e0d\u8db3\u3057\u3066\u3044\u307e\u3059\u3002"; return; }
    allocations.forEach((allocation) => {
      const lot = lots.get(allocation.openingTradeId);
      if (!lot || Number(allocation.quantity) > lot.remainingQuantity) { invalid = "\u5b58\u5728\u3057\u306a\u3044\u4fe1\u7528\u5efa\u7389\u3092\u8fd4\u6e08\u3057\u3066\u3044\u307e\u3059\u3002"; return; }
      lot.remainingQuantity -= Number(allocation.quantity);
    });
  });

  const openCreditLots = [...lots.values()].filter((lot) => lot.remainingQuantity > 0);
  return {
    invalid,
    positions: [...spot.positions, ...openCreditLots.map((lot) => ({ accountType: CREDIT, quantity: lot.remainingQuantity }))],
    openCreditLots
  };
}

test("case 1: a standalone spot purchase can be deleted", () => {
  const result = validateTradeDeletion([trade("b1", BUY, SPOT, "2026-08-01", 100)], "b1", calculateTestLedger);
  assert.equal(result.ok, true);
  assert.equal(result.candidate.length, 0);
  assert.equal(result.ledger.positions.length, 0);
});

test("case 2: a spot purchase used by a later sale cannot be deleted", () => {
  const trades = [trade("b1", BUY, SPOT, "2026-08-01", 100), trade("s1", SELL, SPOT, "2026-08-02", 100)];
  const result = validateTradeDeletion(trades, "b1", calculateTestLedger);
  assert.equal(result.ok, false);
  assert.match(result.error, /\u5f8c\u7d9a\u306e\u58f2\u5374\u6642\u70b9\u3067\u4fdd\u6709\u682a\u6570\u304c\u4e0d\u8db3/);
});

test("case 3: deleting a spot sale restores the holding", () => {
  const trades = [trade("b1", BUY, SPOT, "2026-08-01", 100), trade("s1", SELL, SPOT, "2026-08-02", 100)];
  const result = validateTradeDeletion(trades, "s1", calculateTestLedger);
  assert.equal(result.ok, true);
  assert.equal(result.ledger.positions[0].quantity, 100);
});

test("case 4: an unrepaid credit purchase can be deleted", () => {
  const result = validateTradeDeletion([trade("c1", BUY, CREDIT, "2026-08-01", 100)], "c1", calculateTestLedger);
  assert.equal(result.ok, true);
  assert.equal(result.ledger.openCreditLots.length, 0);
});

test("case 5: a credit purchase referenced by positionAllocations cannot be deleted", () => {
  const trades = [
    trade("c1", BUY, CREDIT, "2026-08-01", 100),
    trade("r1", SELL, CREDIT, "2026-08-02", 100, { positionAllocations: [{ openingTradeId: "c1", quantity: 100 }] })
  ];
  const result = validateTradeDeletion(trades, "c1", calculateTestLedger);
  assert.equal(result.ok, false);
  assert.match(result.error, /positionAllocations|\u5f8c\u7d9a\u306e\u8fd4\u6e08\u8a18\u9332|\u95a2\u9023\u3059\u308b\u8fd4\u6e08\u8a18\u9332/);
});

test("case 6: deleting a credit repayment restores its opening lot", () => {
  const trades = [
    trade("c1", BUY, CREDIT, "2026-08-01", 100),
    trade("r1", SELL, CREDIT, "2026-08-02", 100, { positionAllocations: [{ openingTradeId: "c1", quantity: 100 }] })
  ];
  const result = validateTradeDeletion(trades, "r1", calculateTestLedger);
  assert.equal(result.ok, true);
  assert.deepEqual(result.ledger.openCreditLots.map((lot) => [lot.id, lot.remainingQuantity]), [["c1", 100]]);
});

test("case 7: only an unused opening lot can be deleted from multiple lots", () => {
  const trades = [
    trade("a", BUY, CREDIT, "2026-08-01", 100),
    trade("b", BUY, CREDIT, "2026-08-02", 100),
    trade("r1", SELL, CREDIT, "2026-08-03", 100, { positionAllocations: [{ openingTradeId: "a", quantity: 100 }] })
  ];
  assert.equal(validateTradeDeletion(trades, "a", calculateTestLedger).ok, false);
  assert.equal(validateTradeDeletion(trades, "b", calculateTestLedger).ok, true);
});

test("case 8: a Firestore failure does not mutate local trades", async () => {
  const trades = [trade("b1", BUY, SPOT, "2026-08-01", 100)];
  const original = structuredClone(trades);
  const pendingIds = new Set();
  let calls = 0;
  const result = await deleteTradeOnce({
    id: "b1",
    pendingIds,
    deleteDocument: async () => { calls += 1; throw new Error("network"); }
  });
  assert.equal(result.status, "failed");
  assert.equal(calls, 1);
  assert.deepEqual(trades, original);
  assert.equal(pendingIds.size, 0);
});

test("cases 9 and 10: cancel does not delete and repeated taps run once", async () => {
  let calls = 0;
  const pendingIds = new Set();
  let release;
  const deletion = new Promise((resolve) => { release = resolve; });
  const first = deleteTradeOnce({ id: "b1", pendingIds, deleteDocument: async () => { calls += 1; await deletion; } });
  const second = await deleteTradeOnce({ id: "b1", pendingIds, deleteDocument: async () => { calls += 1; } });
  assert.equal(second.status, "pending");
  assert.equal(calls, 1);
  release();
  assert.equal((await first).status, "deleted");
  assert.equal(pendingIds.size, 0);
});

test("the edit modal owns deletion and the mobile confirmation remains contained", async () => {
  const [appSource, indexSource, styleSource] = await Promise.all([
    readFile(new URL("../app.js", import.meta.url), "utf8"),
    readFile(new URL("../index.html", import.meta.url), "utf8"),
    readFile(new URL("../styles.css", import.meta.url), "utf8")
  ]);
  assert.match(indexSource, /id="delete-trade"[^>]*>\u3053\u306e\u7d04\u5b9a\u3092\u524a\u9664/);
  assert.match(indexSource, /\u3053\u306e\u7d04\u5b9a\u8a18\u9332\u3092\u524a\u9664\u3057\u307e\u3059\u3002\u524a\u9664\u5f8c\u306f\u5143\u306b\u623b\u305b\u307e\u305b\u3093/);
  assert.match(indexSource, /id="cancel-delete"[\s\S]*id="confirm-delete"/);
  assert.match(appSource, /requestAnimationFrame\(\(\) => \$\("#cancel-delete"\)\.focus\(\)\)/);
  assert.match(appSource, /validateTradeDeletion\(state\.trades, id, calculateLedger\)/);
  assert.match(appSource, /deleteDoc\(doc\(db, "users", state\.user\.uid, "trades", documentId\)\)/);
  assert.doesNotMatch(appSource, /record-delete|removeTrade\(|data-action="delete"/);
  assert.doesNotMatch(appSource, /state\.trades\s*=\s*state\.trades\.filter/);
  assert.doesNotMatch(styleSource, /\.record-delete/);
  assert.match(styleSource, /\.delete-confirm-modal\s*\{[^}]*width:\s*min\(520px,100%\)/s);
  assert.match(styleSource, /@media\(max-width:430px\)[\s\S]*\.delete-confirm-actions\s*\{[^}]*grid-template-columns:\s*repeat\(2,minmax\(0,1fr\)\)/);
  assert.match(styleSource, /\.delete-trade-details dd\s*\{[^}]*overflow-wrap:\s*anywhere;/s);
});
