import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import {
  calculateCreditInterest,
  settlementDate
} from "../credit-calculation.mjs";

const appSource = await readFile(new URL("../app.js", import.meta.url), "utf8");
const ledgerSource = appSource.slice(appSource.indexOf("function calculateLedger"), appSource.indexOf("function summaryPeriodStart"));
const calculationUrl = new URL("../credit-calculation.mjs", import.meta.url).href;
const ledgerModule = `
  import { CREDIT_TYPES, calculateCreditInterest, rateForCreditType } from ${JSON.stringify(calculationUrl)};
  const accountTypeOf = (trade) => trade.accountType === "信用" ? "信用" : "現物";
  const creditTypeOf = (trade) => CREDIT_TYPES.includes(trade.creditType) ? trade.creditType : "";
  const positionKey = (code, accountType) => \`${"${code}:${accountType}"}\`;
  const byTimeAsc = (a, b) => a.date.localeCompare(b.date) || (a.createdAt ?? 0) - (b.createdAt ?? 0) || a.id.localeCompare(b.id);
  ${ledgerSource}
  export { calculateLedger };
`;
const { calculateLedger } = await import(`data:text/javascript;base64,${Buffer.from(ledgerModule).toString("base64")}`);

const trade = (id, action, date, price, quantity, extra = {}) => ({
  id, action, date, price, quantity, code: "9999", name: "テスト", market: "東証", style: "デイトレ", createdAt: Number(id.replace(/\D/g, "")) || 0, ...extra
});

test("現物は従来どおり平均取得価格で計算し金利は0円", () => {
  const ledger = calculateLedger([
    trade("c1", "買付", "2026-08-03", 1000, 100, { accountType: "現物" }),
    trade("c2", "買付", "2026-08-04", 1200, 100, { accountType: "現物" }),
    trade("c3", "売却", "2026-08-05", 1300, 100, { accountType: "現物" })
  ]);
  const sale = ledger.calculated.find((item) => item.id === "c3");
  assert.equal(sale.averageCostAtSale, 1100);
  assert.equal(sale.grossProfitBeforeInterest, 20000);
  assert.equal(sale.creditInterest, 0);
  assert.equal(sale.realisedProfit, 20000);
});

test("制度信用の同日返済は受渡日両端入れの1日分", () => {
  const result = calculateCreditInterest({ openDate: "2026-08-03", closeDate: "2026-08-03", price: 1000, quantity: 1000, creditType: "制度信用", annualRate: 0.028 });
  assert.equal(result.interestDays, 1);
  assert.equal(result.amount, 76);
});

test("一般信用は祝日を除いた受渡日と、その間の暦日で計算", () => {
  assert.equal(settlementDate("2026-08-07"), "2026-08-12");
  const result = calculateCreditInterest({ openDate: "2026-08-03", closeDate: "2026-08-07", price: 1000, quantity: 1000, creditType: "一般信用（無期限）", annualRate: 0.028 });
  assert.equal(result.openSettlementDate, "2026-08-05");
  assert.equal(result.closeSettlementDate, "2026-08-12");
  assert.equal(result.interestDays, 8);
  assert.equal(result.amount, 613);
  assert.equal(result.calendarConfirmed, true);
});

test("日計り信用は同日0円、持越しは年率1.80%", () => {
  const sameDay = calculateCreditInterest({ openDate: "2026-08-03", closeDate: "2026-08-03", price: 1000, quantity: 1000, creditType: "日計り信用", annualRate: 0.018 });
  const carried = calculateCreditInterest({ openDate: "2026-08-03", closeDate: "2026-08-04", price: 1000, quantity: 1000, creditType: "日計り信用", annualRate: 0.018 });
  assert.equal(sameDay.appliedAnnualRate, 0);
  assert.equal(sameDay.amount, 0);
  assert.equal(carried.appliedAnnualRate, 0.018);
  assert.equal(carried.interestDays, 2);
  assert.equal(carried.amount, 98);
});

test("祝日前後もJPX休場日を飛ばして受渡日を算出", () => {
  assert.equal(settlementDate("2026-09-18"), "2026-09-25");
  const result = calculateCreditInterest({ openDate: "2026-09-18", closeDate: "2026-09-24", price: 1000, quantity: 100, creditType: "制度信用", annualRate: 0.028 });
  assert.equal(result.closeSettlementDate, "2026-09-28");
  assert.equal(result.interestDays, 4);
});

test("複数建玉と一部返済は先入れ順で買付日・単価別に金利を配分", () => {
  const ledger = calculateLedger([
    trade("b1", "買付", "2026-08-03", 1000, 1000, { accountType: "信用", creditType: "制度信用", annualInterestRate: 0.028 }),
    trade("b2", "買付", "2026-08-05", 1100, 500, { accountType: "信用", creditType: "一般信用（無期限）", annualInterestRate: 0.028 }),
    trade("s1", "売却", "2026-08-10", 1200, 700, { accountType: "信用" }),
    trade("s2", "売却", "2026-08-14", 1300, 800, { accountType: "信用" })
  ]);
  const first = ledger.calculated.find((item) => item.id === "s1");
  const second = ledger.calculated.find((item) => item.id === "s2");
  assert.deepEqual(first.creditAllocations.map((item) => [item.openingTradeId, item.quantity]), [["b1", 700]]);
  assert.deepEqual(second.creditAllocations.map((item) => [item.openingTradeId, item.quantity]), [["b1", 300], ["b2", 500]]);
  assert.equal(first.grossProfitBeforeInterest, 140000);
  assert.equal(first.creditInterest, 483);
  assert.equal(first.realisedProfit, 139517);
  assert.equal(second.grossProfitBeforeInterest, 190000);
  assert.equal(second.creditInterest, 828);
  assert.equal(second.realisedProfit, 189172);
});

test("金利日数の手動上書きと買付時保存金利を使用", () => {
  const ledger = calculateLedger([
    trade("b1", "買付", "2026-08-03", 1000, 1000, { accountType: "信用", creditType: "制度信用", annualInterestRate: 0.025 }),
    trade("s1", "売却", "2026-08-10", 1100, 1000, { accountType: "信用", interestDayOverrides: { b1: 3 } })
  ]);
  const sale = ledger.calculated.find((item) => item.id === "s1");
  assert.equal(sale.creditAllocations[0].manualOverride, true);
  assert.equal(sale.creditAllocations[0].interestDays, 3);
  assert.equal(sale.creditInterest, 205);
});

test("信用種別がない既存信用データは従来損益を維持", () => {
  const ledger = calculateLedger([
    trade("b1", "買付", "2026-08-03", 1000, 100, { accountType: "信用" }),
    trade("s1", "売却", "2026-08-10", 1100, 100, { accountType: "信用" })
  ]);
  const sale = ledger.calculated.find((item) => item.id === "s1");
  assert.equal(sale.creditInterest, 0);
  assert.equal(sale.realisedProfit, 10000);
});

test("売却登録は買付時の運用スタイル・取引区分を引き継いで固定", () => {
  assert.match(appSource, /data-style="\$\{esc\(position\.style\)\}"/);
  assert.match(appSource, /openSell\(target\.dataset\.code, target\.dataset\.style/);
  assert.match(appSource, /setAccountType\(accountType, true\)/);
  assert.match(appSource, /\$\("#trade-style"\)\.disabled = true/);
});
