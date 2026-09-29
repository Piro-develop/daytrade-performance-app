import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";
import { afterTaxProfitOf, afterTaxTotalForTrades } from "../profit-display.mjs";
import { calculateAnnualTaxEstimates } from "../tax-calculation.mjs";

const source = await readFile(new URL("../app.js", import.meta.url), "utf8");
const slice = (start, end) => source.slice(source.indexOf(start), source.indexOf(end));
const byTimeAsc = (a, b) => a.date.localeCompare(b.date) || a.id.localeCompare(b.id);
const sale = (id, realisedProfit, overrides = {}) => ({ id, action: "売却", date: "2026-09-01", accountType: "信用", style: "スイング", realisedProfit, ...overrides });
function setup() {
  const state = { summaryFilters: { period: "all", style: "all", accountType: "all" } };
  const context = vm.createContext({ state, afterTaxProfitOf, afterTaxTotalForTrades, calculateAnnualTaxEstimates, byTimeAsc,
    hasOwn: (object, key) => Object.hasOwn(object, key), accountTypeOf: trade => trade.accountType,
    pnlRange: () => ({ start: "2026-09-01", end: "2026-09-30" }) });
  vm.runInContext(slice("function summaryPeriodStart", "function chartSvg"), context);
  return { state, context, stats: trades => context.statsFor(context.completedForSummary(trades)) };
}

test("利益と損失を相殺せず合計し、未実現・買付・損益ゼロを含めない", () => {
  const { stats } = setup();
  const trades = [sale("win1", 1000), sale("win2", 2000), sale("loss1", -500), sale("loss2", -100), sale("zero", 0), sale("pending", null), sale("buy", 99999, { action: "買付" })];
  const before = JSON.stringify(trades);
  const result = stats(trades);
  assert.equal(result.afterTaxProfitTotal, 3000);
  assert.equal(result.afterTaxLossTotal, -600);
  assert.equal(result.grossProfit, 3000);
  assert.equal(result.grossLoss, -600);
  assert.equal(result.afterTaxAverageProfit, 1500);
  assert.equal(result.afterTaxAverageLoss, -300);
  assert.equal(JSON.stringify(trades), before);
});

test("SBI実績・税引後概算で最大取引を選び、税引前での順位と混同しない", () => {
  const { stats } = setup();
  const result = stats([
    sale("largest-before-tax", 2000, { brokerActuals: { settlement: 800 } }),
    sale("largest-after-tax", 1500, { estimatedAfterTaxProfit: 1200 }),
    sale("largest-loss-before-tax", -1000, { brokerActuals: { settlement: -100 } }),
    sale("largest-loss-after-tax", -500, { estimatedAfterTaxProfit: -400 })
  ]);
  assert.equal(result.afterTaxProfitTotal, 2000);
  assert.equal(result.afterTaxLossTotal, -500);
  assert.equal(result.maxProfitTrade.id, "largest-after-tax");
  assert.equal(result.maxLossTrade.id, "largest-loss-after-tax");
  assert.equal(result.afterTaxMaxProfit, afterTaxProfitOf(result.maxProfitTrade));
  assert.equal(result.afterTaxMaxLoss, afterTaxProfitOf(result.maxLossTrade));
});

test("期間・取引区分・取引スタイルの集計条件を合計と移動先に反映する", () => {
  const { state, stats } = setup();
  state.summaryFilters = { period: "month", style: "スイング", accountType: "信用" };
  const result = stats([
    sale("included", 1000, { brokerActuals: { settlement: 800 } }),
    sale("outside-period", 9000, { date: "2026-08-31" }),
    sale("outside-account", 10000, { accountType: "現物" }),
    sale("outside-style", 11000, { style: "デイトレ" })
  ]);
  assert.equal(result.afterTaxProfitTotal, 800);
  assert.equal(result.afterTaxLossTotal, 0);
  assert.equal(result.maxProfitTrade.id, "included");
  assert.equal(result.maxLossTrade, null);
});

test("対象なし・利益のみ・損失のみ・同額最大でも移動先を安全に決める", () => {
  const { stats } = setup();
  for (const input of [[], [sale("zero", 0)]]) {
    const result = stats(input);
    assert.equal(result.afterTaxProfitTotal, 0);
    assert.equal(result.afterTaxLossTotal, 0);
    assert.equal(result.maxProfitTrade, null);
    assert.equal(result.maxLossTrade, null);
  }
  assert.equal(stats([sale("win", 10)]).maxLossTrade, null);
  assert.equal(stats([sale("loss", -10)]).maxProfitTrade, null);
  const ties = [sale("later", 100, { date: "2026-09-02" }), sale("earlier", 100)];
  assert.equal(stats(ties).maxProfitTrade.id, "earlier");
  assert.equal(stats(ties.toReversed()).maxProfitTrade.id, "earlier");
});

function navigationSetup(exists = true) {
  const events = [], frames = [];
  const state = { trades: [{ id: "target" }], activeView: "overview", pnlPeriod: "day", recordQuery: "別の銘柄", recordSecurityCode: "9999" };
  const entry = { dataset: { id: "target" }, classList: { add: value => events.push(value) }, focus: options => events.push(["focus", options.preventScroll]), scrollIntoView: options => events.push(["scroll", options.block]) };
  const ledger = { calculated: exists ? state.trades : [] };
  const context = vm.createContext({ state, calculateLedger: () => ledger,
    renderRecords: value => { assert.equal(value, ledger); events.push("render"); },
    switchView: view => { state.activeView = view; events.push(view); frames.push(() => events.push("top")); },
    requestAnimationFrame: fn => frames.push(fn), $$: () => [entry], showToast: message => events.push(message) });
  vm.runInContext(slice("function openRecordTrade", "function closePositionLotModal"), context);
  return { state, context, events, flush: () => frames.splice(0).forEach(fn => fn()) };
}

test("対象取引を隠す期間・検索を解除し、画面切替後にフォーカスと目印を付ける", () => {
  const { state, context, events, flush } = navigationSetup();
  const before = JSON.stringify(state.trades);
  context.openRecordTrade("target");
  assert.equal(state.pnlPeriod, "all");
  assert.equal(state.recordQuery, "");
  assert.equal(state.recordSecurityCode, null);
  assert.deepEqual(events, ["render", "records"]);
  flush();
  assert.deepEqual(events, ["render", "records", "top", "record-entry-highlight", ["focus", true], ["scroll", "center"]]);
  assert.equal(JSON.stringify(state.trades), before);
});

test("取引がなくなった場合や別画面へ移動済みの場合に誤ってスクロールしない", () => {
  const missing = navigationSetup(false);
  missing.context.openRecordTrade("target");
  assert.equal(missing.state.activeView, "overview");
  assert.equal(missing.state.pnlPeriod, "day");
  assert.equal(missing.events.length, 1);
  const switched = navigationSetup();
  switched.context.openRecordTrade("target");
  switched.state.activeView = "overview";
  switched.flush();
  assert.ok(!switched.events.includes("record-entry-highlight"));
});
