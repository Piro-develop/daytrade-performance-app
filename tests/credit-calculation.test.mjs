import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import {
  calculateCreditInterest,
  settlementDate
} from "../credit-calculation.mjs";
import {
  ALLOCATION_METHODS,
  ALLOCATION_SETTINGS,
  allocationArrayToObject,
  allocationObjectToArray,
  automaticPositionAllocations,
  creditLotEvaluation,
  sortCreditLots
} from "../position-allocation.mjs";

const appSource = await readFile(new URL("../app.js", import.meta.url), "utf8");
const indexSource = await readFile(new URL("../index.html", import.meta.url), "utf8");
const ledgerSource = appSource.slice(appSource.indexOf("function calculateLedger"), appSource.indexOf("function summaryPeriodStart"));
const calculationUrl = new URL("../credit-calculation.mjs", import.meta.url).href;
const spotUrl = new URL("../spot-calculation.mjs", import.meta.url).href;
const taxUrl = new URL("../tax-calculation.mjs", import.meta.url).href;
const ledgerModule = `
  import { CREDIT_TYPES, calculateCreditInterest, rateForCreditType } from ${JSON.stringify(calculationUrl)};
  import { calculateSpotLedger } from ${JSON.stringify(spotUrl)};
  import { calculateAnnualTaxEstimates } from ${JSON.stringify(taxUrl)};
  const accountTypeOf = (trade) => trade.accountType === "信用" ? "信用" : "現物";
  const creditTypeOf = (trade) => CREDIT_TYPES.includes(trade.creditType) ? trade.creditType : "";
  const CUSTODY_TYPES = ["特定", "一般"];
  const custodyTypeOf = (trade) => CUSTODY_TYPES.includes(trade.custodyType) ? trade.custodyType : "未設定";
  const creditGroupKey = (trade) => \`${"${creditTypeOf(trade) || \"信用種別未設定\"}::${custodyTypeOf(trade)}"}\`;
  const ALLOCATION_SETTINGS = { defaultTradingUnit: 100 };
  const positionKey = (code, accountType) => \`${"${code}:${accountType}"}\`;
  const byTimeAsc = (a, b) => a.date.localeCompare(b.date) || (a.createdAt ?? 0) - (b.createdAt ?? 0) || a.id.localeCompare(b.id);
  ${ledgerSource}
  export { calculateLedger };
`;
const { calculateLedger } = await import(`data:text/javascript;base64,${Buffer.from(ledgerModule).toString("base64")}`);

const trade = (id, action, date, price, quantity, extra = {}) => ({
  id, action, date, price, quantity, code: "9999", name: "テスト", market: "東証", style: "デイトレ", createdAt: Number(id.replace(/\D/g, "")) || 0, ...extra
});

test("現物はSBI税務取得単価で計算し金利は0円", () => {
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

test("指定した建玉の価格と日付で全株返済を計算", () => {
  const ledger = calculateLedger([
    trade("b1", "買付", "2026-08-03", 1000, 100, { accountType: "信用", creditType: "制度信用", annualInterestRate: 0.028 }),
    trade("b2", "買付", "2026-08-05", 900, 100, { accountType: "信用", creditType: "一般信用（無期限）", annualInterestRate: 0.028 }),
    trade("s1", "売却", "2026-08-10", 1200, 100, { accountType: "信用", positionAllocations: [{ openingTradeId: "b2", quantity: 100 }], allocationMethod: "manual" })
  ]);
  const sale = ledger.calculated.find((item) => item.id === "s1");
  assert.equal(ledger.invalid, null);
  assert.equal(sale.allocationConfirmed, true);
  assert.deepEqual(sale.creditAllocations.map((item) => [item.openingTradeId, item.quantity]), [["b2", 100]]);
  assert.equal(sale.averageCostAtSale, 900);
  assert.equal(sale.grossProfitBeforeInterest, 30000);
});

test("1建玉の一部返済は指定株数だけ減らす", () => {
  const ledger = calculateLedger([
    trade("b1", "買付", "2026-08-03", 1000, 2000, { accountType: "信用", creditType: "制度信用", annualInterestRate: 0.028 }),
    trade("s1", "売却", "2026-08-10", 1100, 500, { accountType: "信用", positionAllocations: [{ openingTradeId: "b1", quantity: 500 }], allocationMethod: "manual" })
  ]);
  const sale = ledger.calculated.find((item) => item.id === "s1");
  assert.equal(sale.creditAllocations[0].quantity, 500);
  assert.equal(sale.grossProfitBeforeInterest, 50000);
  assert.equal(ledger.openCreditLots[0].remainingQuantity, 1500);
});

test("複数建玉を指定株数だけ一部返済し残株を維持", () => {
  const ledger = calculateLedger([
    trade("b1", "買付", "2026-08-03", 1000, 100, { accountType: "信用", creditType: "制度信用", annualInterestRate: 0.028 }),
    trade("b2", "買付", "2026-08-05", 1100, 100, { accountType: "信用", creditType: "制度信用", annualInterestRate: 0.028 }),
    trade("s1", "売却", "2026-08-10", 1200, 75, { accountType: "信用", positionAllocations: [{ openingTradeId: "b2", quantity: 50 }, { openingTradeId: "b1", quantity: 25 }], allocationMethod: "manual" })
  ]);
  const sale = ledger.calculated.find((item) => item.id === "s1");
  assert.deepEqual(sale.creditAllocations.map((item) => [item.openingTradeId, item.quantity]), [["b2", 50], ["b1", 25]]);
  assert.equal(sale.grossProfitBeforeInterest, 10000);
  assert.equal(ledger.openCreditLots.find((lot) => lot.id === "b1").remainingQuantity, 75);
  assert.equal(ledger.openCreditLots.find((lot) => lot.id === "b2").remainingQuantity, 50);
});

test("返済建玉の合計不一致と残株超過を登録前に拒否", () => {
  const buy = trade("b1", "買付", "2026-08-03", 1000, 100, { accountType: "信用", creditType: "制度信用", annualInterestRate: 0.028 });
  const mismatch = calculateLedger([buy, trade("s1", "売却", "2026-08-10", 1100, 50, { accountType: "信用", positionAllocations: [{ openingTradeId: "b1", quantity: 40 }] })]);
  const excess = calculateLedger([buy, trade("s2", "売却", "2026-08-10", 1100, 100, { accountType: "信用", positionAllocations: [{ openingTradeId: "b1", quantity: 101 }] })]);
  assert.match(mismatch.invalid, /指定株数合計/);
  assert.match(excess.invalid, /指定株数合計|残株数/);
});

test("運用スタイルが異なる建玉も返済でき、損益を元のスタイルへ配分", () => {
  const buy = trade("b1", "買付", "2026-08-03", 1000, 100, { accountType: "信用", style: "スイング", creditType: "制度信用", annualInterestRate: 0.028 });
  const ledger = calculateLedger([buy, trade("s1", "売却", "2026-08-10", 1100, 100, { accountType: "信用", style: "デイトレ", positionAllocations: [{ openingTradeId: "b1", quantity: 100 }] })]);
  const sale = ledger.calculated.find((item) => item.id === "s1");
  assert.equal(ledger.invalid, null);
  assert.equal(sale.styleProfits.スイング, sale.realisedProfit);
  assert.equal(sale.styleProfits.デイトレ, undefined);
});

test("自動選択は古い順・新しい順・利益順・損失順を使い分ける", () => {
  const lots = [
    { id: "old", date: "2026-08-01", createdAt: 1, price: 1000, remainingQuantity: 100 },
    { id: "loss", date: "2026-08-02", createdAt: 2, price: 1300, remainingQuantity: 100 },
    { id: "profit", date: "2026-08-03", createdAt: 3, price: 800, remainingQuantity: 100 }
  ];
  assert.equal(automaticPositionAllocations(lots, 50, "oldest", 1100)[0].openingTradeId, "old");
  assert.equal(automaticPositionAllocations(lots, 50, "newest", 1100)[0].openingTradeId, "profit");
  assert.equal(automaticPositionAllocations(lots, 50, "profit", 1100)[0].openingTradeId, "profit");
  assert.equal(automaticPositionAllocations(lots, 50, "loss", 1100)[0].openingTradeId, "loss");
  assert.deepEqual(sortCreditLots(lots, "oldest", 1100).map((lot) => lot.id), ["old", "loss", "profit"]);
  const sameDate = [
    { id: "lower", date: "2026-08-05", createdAt: 1, price: 1000, remainingQuantity: 100 },
    { id: "higher", date: "2026-08-05", createdAt: 2, price: 900, remainingQuantity: 100 }
  ];
  assert.equal(automaticPositionAllocations(sameDate, 50, "oldest", 1100)[0].openingTradeId, "higher");
  assert.equal(automaticPositionAllocations(sameDate, 50, "newest", 1100)[0].openingTradeId, "higher");
});

test("初期返済順はSBI標準の評価益順", () => {
  assert.equal(ALLOCATION_SETTINGS.defaultMethod, "profit");
  assert.equal(ALLOCATION_METHODS.profit, "SBI標準：評価益順");
});

test("SBI建玉別評価損益を1単元換算し、評価益順と同値の古い順を再現", () => {
  const lots = [
    { id: "old", date: "2026-08-01", createdAt: 1, price: 1000, remainingQuantity: 200, tradingUnit: 100 },
    { id: "new", date: "2026-08-02", createdAt: 2, price: 900, remainingQuantity: 100, tradingUnit: 100 },
    { id: "best", date: "2026-08-03", createdAt: 3, price: 800, remainingQuantity: 100, tradingUnit: 100 }
  ];
  const context = { evaluationProfitOverrides: { old: 20000, new: 10000, best: 30000 }, tradingUnit: 100 };
  assert.equal(creditLotEvaluation(lots[0], context).perTradingUnitProfit, 10000);
  assert.deepEqual(sortCreditLots(lots, "profit", context).map((lot) => lot.id), ["best", "old", "new"]);
  assert.deepEqual(sortCreditLots(lots, "loss", context).map((lot) => lot.id), ["old", "new", "best"]);
});

test("建日順は同日なら1単元評価益が大きい建玉を優先", () => {
  const lots = [
    { id: "low", date: "2026-08-05", createdAt: 1, price: 1000, remainingQuantity: 100 },
    { id: "high", date: "2026-08-05", createdAt: 2, price: 1000, remainingQuantity: 100 }
  ];
  const context = { evaluationProfitOverrides: { low: -1000, high: 5000 }, tradingUnit: 100 };
  assert.equal(sortCreditLots(lots, "oldest", context)[0].id, "high");
  assert.equal(sortCreditLots(lots, "newest", context)[0].id, "high");
});

test("信用種別または預り区分が異なる建玉の一括返済を拒否", () => {
  const buys = [
    trade("b1", "買付", "2026-08-03", 1000, 100, { accountType: "信用", creditType: "制度信用", custodyType: "特定" }),
    trade("b2", "買付", "2026-08-03", 1000, 100, { accountType: "信用", creditType: "日計り信用", custodyType: "特定" })
  ];
  const sale = trade("s1", "売却", "2026-08-04", 1100, 200, { accountType: "信用", positionAllocations: [{ openingTradeId: "b1", quantity: 100 }, { openingTradeId: "b2", quantity: 100 }] });
  assert.match(calculateLedger([...buys, sale]).invalid, /信用種別または預り区分/);
});

test("自動選択後の手動修正を保存用配列へ変換", () => {
  const object = allocationArrayToObject([{ openingTradeId: "b1", quantity: 80 }, { openingTradeId: "b2", quantity: 20 }]);
  object.b1 = 30;
  object.b2 = 70;
  assert.deepEqual(allocationObjectToArray(object), [{ openingTradeId: "b1", quantity: 30 }, { openingTradeId: "b2", quantity: 70 }]);
});

test("保存後の再読込でも建玉指定と証券会社実績値を維持", () => {
  const trades = JSON.parse(JSON.stringify([
    trade("b1", "買付", "2026-08-03", 1000, 100, { accountType: "信用", creditType: "制度信用", annualInterestRate: 0.028 }),
    trade("s1", "売却", "2026-08-10", 1200, 100, { accountType: "信用", positionAllocations: [{ openingTradeId: "b1", quantity: 100 }], allocationMethod: "profit", allocationConfirmed: true, brokerActuals: { fees: 100, tax: 2000, settlement: 17000 } })
  ]));
  const sale = calculateLedger(trades).calculated.find((item) => item.id === "s1");
  assert.equal(sale.allocationMethod, "profit");
  assert.equal(sale.brokerActuals.settlement, 17000);
  assert.equal(sale.creditAllocations[0].openingTradeId, "b1");
});

test("既存の信用返済は従来計算を維持し未確認として扱う", () => {
  const ledger = calculateLedger([
    trade("b1", "買付", "2026-08-03", 1000, 100, { accountType: "信用" }),
    trade("s1", "売却", "2026-08-10", 1100, 100, { accountType: "信用" })
  ]);
  const sale = ledger.calculated.find((item) => item.id === "s1");
  assert.equal(sale.realisedProfit, 10000);
  assert.equal(sale.allocationConfirmed, false);
  assert.equal(sale.allocationMethod, "legacy-fifo");
  assert.match(appSource, /返済建玉未確認/);
});

test("GMO実績値は照合用データとして保持し、返済順ロジックへハードコードしない", async () => {
  const actual = { code: "9449", date: "2026-08-24", quantity: 2000, price: 4088, fees: 4543, tax: 55670, settlement: 218287 };
  const reloaded = JSON.parse(JSON.stringify(actual));
  assert.deepEqual(reloaded, actual);
  assert.equal(actual.settlement + actual.fees + actual.tax, 278500);
  assert.doesNotMatch(appSource.slice(appSource.indexOf("function calculateLedger"), appSource.indexOf("function summaryPeriodStart")), /218287|55670|4543/);
  assert.doesNotMatch(await readFile(new URL("../position-allocation.mjs", import.meta.url), "utf8"), /218287|55670|4543|9449/);
});

test("建玉指定UI・実績値入力・スマホ向け部品を備える", () => {
  assert.match(appSource, /data-action="allocation-method"/);
  assert.match(appSource, /data-position-lot-id/);
  assert.match(appSource, /brokerActuals/);
  assert.match(appSource, /positionAllocations/);
  assert.match(appSource, /allocation-evaluation-price/);
  assert.match(appSource, /data-evaluation-profit-lot-id/);
  assert.match(appSource, /repaymentGroup/);
  assert.match(appSource, /custodyType/);
  assert.match(appSource, /税引後損益（概算）/);
  assert.match(indexSource, /id="custody-type"/);
  assert.match(indexSource, /id="transaction-fee"/);
  assert.match(appSource, /transactionFee/);
  assert.match(indexSource, /特定/);
});
