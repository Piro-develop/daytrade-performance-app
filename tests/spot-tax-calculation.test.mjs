import test from "node:test";
import assert from "node:assert/strict";
import {
  calculateSpotLedger,
  sbiAcquisitionUnitPrice
} from "../spot-calculation.mjs";
import {
  calculateAnnualTaxEstimates,
  estimatedAfterTaxForTrades,
  estimatedTaxForAnnualProfit
} from "../tax-calculation.mjs";

const trade = (id, action, date, price, quantity, extra = {}) => ({
  id,
  action,
  date,
  price,
  quantity,
  code: "9999",
  name: "現物テスト",
  market: "東証",
  style: "デイトレ",
  accountType: "現物",
  createdAt: Number(id.replace(/\D/g, "")) || 0,
  ...extra
});

test("取得単価は買付手数料込みで1円未満を切り上げる", () => {
  assert.equal(sbiAcquisitionUnitPrice(12055, 100), 121);
  const ledger = calculateSpotLedger([
    trade("b1", "買付", "2026-08-03", 120, 100, { transactionFee: 55 })
  ]);
  assert.equal(ledger.positions[0].averagePrice, 121);
});

test("売却前の買増しは切上げ単価ではなく取得価額合計を引き継ぐ", () => {
  const ledger = calculateSpotLedger([
    trade("b1", "買付", "2026-08-03", 100, 2, { transactionFee: 1 }),
    trade("b2", "買付", "2026-08-04", 99, 1)
  ]);
  assert.equal(ledger.results.get("b1").taxAcquisitionUnitPrice, 101);
  assert.equal(ledger.results.get("b2").taxAcquisitionUnitPrice, 100);
  assert.equal(ledger.positions[0].averagePrice, 100);
});
test("異なる価格の複数買付は取得価額合計から総平均する", () => {
  const ledger = calculateSpotLedger([
    trade("b1", "買付", "2026-08-03", 3000, 100),
    trade("b2", "買付", "2026-08-04", 3100, 200),
    trade("s1", "売却", "2026-08-05", 3200, 100)
  ]);
  const sale = ledger.results.get("s1");
  assert.equal(sale.averageCostAtSale, 3067);
  assert.equal(sale.realisedProfit, 13300);
  assert.equal(ledger.positions[0].quantity, 200);
  assert.equal(ledger.positions[0].averagePrice, 3067);
});

test("一部売却後の買増しは残株の切上げ取得単価から再計算する", () => {
  const ledger = calculateSpotLedger([
    trade("b1", "買付", "2026-12-22", 120, 100, { transactionFee: 55 }),
    trade("b2", "買付", "2026-12-25", 115, 200, { transactionFee: 55 }),
    trade("s1", "売却", "2026-12-26", 123, 100, { transactionFee: 55 }),
    trade("b3", "買付", "2026-12-27", 110, 300, { transactionFee: 55 })
  ]);
  assert.equal(ledger.results.get("b2").taxAcquisitionUnitPrice, 118);
  assert.equal(ledger.results.get("s1").realisedProfit, 445);
  assert.equal(ledger.results.get("b3").taxAcquisitionUnitPrice, 114);
  assert.equal(ledger.positions[0].quantity, 500);
  assert.equal(ledger.positions[0].averagePrice, 114);
});
test("売却手数料を譲渡損益から控除する", () => {
  const ledger = calculateSpotLedger([
    trade("b1", "買付", "2026-08-03", 120, 100, { transactionFee: 55 }),
    trade("s1", "売却", "2026-08-04", 123, 100, { transactionFee: 55 })
  ]);
  assert.equal(ledger.results.get("s1").realisedProfit, 145);
});

test("同日の売却を先に登録しても当日の買付を先に扱う", () => {
  const ledger = calculateSpotLedger([
    trade("s1", "売却", "2026-08-03", 1100, 100, { createdAt: 1 }),
    trade("b2", "買付", "2026-08-03", 1000, 100, { createdAt: 2 })
  ]);
  assert.equal(ledger.invalid, null);
  assert.equal(ledger.results.get("s1").averageCostAtSale, 1000);
  assert.equal(ledger.results.get("s1").realisedProfit, 10000);
  assert.equal(ledger.positions.length, 0);
});
test("同日買付後の売却は当日の全買付を先に平均する", () => {
  const ledger = calculateSpotLedger([
    trade("b1", "買付", "2026-08-03", 1000, 100),
    trade("s1", "売却", "2026-08-03", 1100, 100)
  ]);
  assert.equal(ledger.results.get("s1").averageCostAtSale, 1000);
  assert.equal(ledger.results.get("s1").realisedProfit, 10000);
});

test("前日保有を売却して同日再購入しても当日買付を先に平均する", () => {
  const ledger = calculateSpotLedger([
    trade("b1", "買付", "2026-08-03", 1000, 100),
    trade("s1", "売却", "2026-08-04", 1200, 100),
    trade("b2", "買付", "2026-08-04", 1100, 100)
  ]);
  const sale = ledger.results.get("s1");
  assert.equal(sale.averageCostAtSale, 1050);
  assert.equal(sale.realisedProfit, 15000);
  assert.equal(sale.tradePerformanceProfit, 20000);
  assert.equal(sale.realisedProfitDifference, -5000);
  assert.equal(ledger.positions[0].averagePrice, 1050);
});

test("同日中に買付・売却を繰り返しても全買付の平均単価を使用する", () => {
  const ledger = calculateSpotLedger([
    trade("b1", "買付", "2026-08-03", 1000, 100),
    trade("s1", "売却", "2026-08-03", 1100, 100),
    trade("b2", "買付", "2026-08-03", 1200, 100),
    trade("s2", "売却", "2026-08-03", 1300, 100)
  ]);
  assert.equal(ledger.results.get("s1").averageCostAtSale, 1100);
  assert.equal(ledger.results.get("s1").realisedProfit, 0);
  assert.equal(ledger.results.get("s2").realisedProfit, 20000);
  assert.equal(ledger.positions.length, 0);
});

test("前日保有と当日追加買付を平均して当日一部売却する", () => {
  const ledger = calculateSpotLedger([
    trade("b1", "買付", "2026-08-03", 1000, 100),
    trade("b2", "買付", "2026-08-04", 1200, 100),
    trade("s1", "売却", "2026-08-04", 1300, 100)
  ]);
  assert.equal(ledger.results.get("s1").averageCostAtSale, 1100);
  assert.equal(ledger.results.get("s1").realisedProfit, 20000);
  assert.equal(ledger.positions[0].quantity, 100);
  assert.equal(ledger.positions[0].averagePrice, 1100);
});

test("年間損益が10万円利益・10万円損失なら概算税額0円", () => {
  const calculated = [
    trade("s1", "売却", "2026-02-02", 0, 1, { realisedProfit: 100000 }),
    trade("s2", "売却", "2026-03-02", 0, 1, { realisedProfit: -100000 })
  ];
  const result = calculateAnnualTaxEstimates(calculated);
  assert.equal(result.annualSummaries[0].netRealisedProfit, 0);
  assert.equal(result.annualSummaries[0].estimatedTax, 0);
  assert.equal(estimatedAfterTaxForTrades(calculated), 0);
});

test("年間損益10万円利益・5万円損失は5万円へ課税", () => {
  const tax = estimatedTaxForAnnualProfit(50000);
  assert.equal(tax.incomeTax, 7657);
  assert.equal(tax.residentTax, 2500);
  assert.equal(tax.totalTax, 10157);
});

test("先に損失、その後利益でも年間純利益だけへ課税", () => {
  const calculated = [
    trade("s1", "売却", "2026-02-02", 0, 1, { realisedProfit: -100000 }),
    trade("s2", "売却", "2026-03-02", 0, 1, { realisedProfit: 150000 })
  ];
  const result = calculateAnnualTaxEstimates(calculated);
  assert.equal(result.taxResults.get("s1").estimatedTaxChange, 0);
  assert.equal(result.taxResults.get("s2").estimatedTaxChange, 10157);
  assert.equal(result.annualSummaries[0].netRealisedProfit, 50000);
});

test("利益後の損失は徴収済み概算税の還付として扱う", () => {
  const calculated = [
    trade("s1", "売却", "2026-02-02", 0, 1, { realisedProfit: 100000 }),
    trade("s2", "売却", "2026-03-02", 0, 1, { realisedProfit: -50000 })
  ];
  const result = calculateAnnualTaxEstimates(calculated);
  assert.equal(result.taxResults.get("s1").estimatedTaxChange, 20315);
  assert.equal(result.taxResults.get("s2").estimatedTaxChange, -10158);
  assert.equal(result.annualSummaries[0].estimatedTax, 10157);
});

test("受渡日基準で年を分け、翌年取引と混在させない", () => {
  const calculated = [
    trade("s1", "売却", "2026-12-28", 0, 1, { realisedProfit: 100000 }),
    trade("s2", "売却", "2026-12-30", 0, 1, { realisedProfit: 100000 })
  ];
  const result = calculateAnnualTaxEstimates(calculated);
  assert.equal(result.taxResults.get("s1").taxYear, "2026");
  assert.equal(result.taxResults.get("s2").taxYear, "2027");
  assert.equal(result.annualSummaries.length, 2);
});
