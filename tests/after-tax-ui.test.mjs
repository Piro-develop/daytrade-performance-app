import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const appSource = await readFile(new URL("../app.js", import.meta.url), "utf8");
const profitDisplaySource = await readFile(new URL("../profit-display.mjs", import.meta.url), "utf8");

const between = (start, end) => appSource.slice(appSource.indexOf(start), appSource.indexOf(end));
const overview = between("function renderOverview", "function parseLocalDate");
const records = between("function renderRecords", "function renderAnalytics");
const analytics = between("function renderAnalytics", "function renderSettings");
const preview = between("function updateSalePreview", "function renderCreditLotSelector");

test("サマリと直近売買は税引後を主表示し税引前を補助表示する", () => {
  assert.match(overview, /<span>税引後損益<\/span>/);
  assert.match(overview, /stats\.afterTaxAverageProfit/);
  assert.match(overview, /stats\.afterTaxAverageLoss/);
  assert.match(overview, /stats\.afterTaxMaxProfit/);
  assert.match(overview, /stats\.afterTaxMaxLoss/);
  assert.match(overview, /累積税引後損益/);
  assert.match(overview, /afterTaxProfitOf\(trade\)/);
  assert.match(overview, /（税引前 \$\{yen\(trade\.realisedProfit\)\}）/);
});

test("売買記録は累計・期間・各売却の税引後を主表示する", () => {
  assert.match(records, /全期間の累計税引後損益/);
  assert.match(records, /期間別の税引後損益/);
  assert.match(records, /afterTaxTotalForTrades\(completed/);
  assert.match(records, /afterTaxTotalForTrades\(selectedTrades/);
  assert.match(records, /const afterTaxProfit = trade\.realisedProfit === null \? null : afterTaxProfitOf\(trade\)/);
  assert.match(records, /class="record-entry-result"/);
  assert.match(records, /（税引前 \$\{yen\(trade\.realisedProfit\)\}）/);
});

test("分析の金額指標は共通税計算結果から税引後を主表示する", () => {
  assert.match(analytics, /運用スタイル別の税引後損益/);
  assert.match(analytics, /calculateAnnualTaxEstimates\(allocated\)/);
  assert.match(analytics, /afterTaxTotalForTrades\(trades\)/);
  assert.match(analytics, /（税引前 \$\{yen\(taxBefore\)\}）/);
});

test("売却・信用返済プレビューと編集時表示は税引後が主になる", () => {
  assert.match(preview, /const afterTaxProfit = calculated \? afterTaxProfitOf\(calculated\) : null/);
  assert.match(preview, /afterTaxSourceLabel\(calculated\)/);
  assert.match(preview, /税引後損益（\$\{afterTaxLabel\}）/);
  assert.match(preview, /（税引前 \$\{yen\(profit\)\}）/);
});

test("画面ごとの独自税率計算を追加せず共通モジュールを再利用する", () => {
  assert.match(appSource, /from "\.\/profit-display\.mjs"/);
  assert.match(profitDisplaySource, /calculateAnnualTaxEstimates/);
  assert.match(profitDisplaySource, /estimatedAfterTaxForTrades/);
  assert.doesNotMatch(`${appSource}\n${profitDisplaySource}`, /0\.20315\s*\*|\*\s*0\.20315/);
});
