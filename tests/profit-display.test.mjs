import test from "node:test";
import assert from "node:assert/strict";
import { afterTaxProfitOf, afterTaxSourceLabel, afterTaxTotalForTrades, brokerActualAfterTaxProfitOf } from "../profit-display.mjs";
import { calculateAnnualTaxEstimates, estimatedAfterTaxForTrades } from "../tax-calculation.mjs";

const sale = (overrides = {}) => ({
  id: "sale-1",
  action: "売却",
  accountType: "信用",
  date: "2026-08-01",
  realisedProfit: 100000,
  estimatedAfterTaxProfit: 79685,
  ...overrides
});

test("信用売却は保存済みSBI決済損益を税引後の主表示へ優先する", () => {
  const trade = sale({ brokerActuals: { fees: 500, tax: 20000, settlement: 78500 } });
  assert.equal(brokerActualAfterTaxProfitOf(trade), 78500);
  assert.equal(afterTaxProfitOf(trade), 78500);
  assert.equal(afterTaxSourceLabel(trade), "SBI実績");
  assert.equal(trade.realisedProfit, 100000);
});

test("SBI実績がない取引と現物取引は既存の税引後概算を使う", () => {
  assert.equal(afterTaxProfitOf(sale({ brokerActuals: null })), 79685);
  assert.equal(afterTaxSourceLabel(sale({ brokerActuals: null })), "概算");
  assert.equal(afterTaxProfitOf(sale({ accountType: "現物", brokerActuals: { settlement: 1 } })), 79685);
});

test("集計は既存の年間損益通算結果を基準にしSBI実績分だけ置換する", () => {
  const raw = [
    sale({ id: "gain", date: "2026-02-02", realisedProfit: 100000, estimatedAfterTaxProfit: undefined, brokerActuals: null }),
    sale({ id: "loss", date: "2026-03-02", realisedProfit: -50000, estimatedAfterTaxProfit: undefined, brokerActuals: null })
  ];
  const estimates = calculateAnnualTaxEstimates(raw);
  const calculated = raw.map((trade) => ({ ...trade, ...(estimates.taxResults.get(trade.id) ?? {}) }));
  const expected = estimatedAfterTaxForTrades(calculated);
  assert.equal(afterTaxTotalForTrades(calculated), expected);

  const withActual = calculated.map((trade) => trade.id === "gain" ? { ...trade, brokerActuals: { settlement: 79000 } } : trade);
  assert.equal(
    afterTaxTotalForTrades(withActual),
    expected + 79000 - calculated[0].estimatedAfterTaxProfit
  );
});
