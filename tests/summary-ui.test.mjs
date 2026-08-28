import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createChartAxis, createChartHighlights, formatChartTick } from "../summary-ui.mjs";

const appSource = await readFile(new URL("../app.js", import.meta.url), "utf8");
const styles = await readFile(new URL("../styles.css", import.meta.url), "utf8");
const indexSource = await readFile(new URL("../index.html", import.meta.url), "utf8");
const overviewSource = appSource.slice(appSource.indexOf("function renderOverview"), appSource.indexOf("function tradeCard"));

test("累積損益の最高値に応じて4～6個の読みやすい目盛りを作る", () => {
  const large = createChartAxis([300000, 900000, 1800000]);
  const medium = createChartAxis([100000, 250000, 400000]);
  assert.equal(large.step, 500000);
  assert.deepEqual(large.ticks, [0, 500000, 1000000, 1500000, 2000000]);
  assert.equal(medium.step, 100000);
  assert.deepEqual(medium.ticks, [0, 100000, 200000, 300000, 400000]);
  assert.ok([large, medium].every((axis) => axis.ticks.length >= 4 && axis.ticks.length <= 6));
});

test("マイナスとプラスの累積損益を両方含む目盛りを作る", () => {
  const axis = createChartAxis([-500000, 200000, 1000000]);
  assert.deepEqual(axis.ticks, [-500000, 0, 500000, 1000000]);
  assert.equal(formatChartTick(-500000), "−50万円");
  assert.equal(formatChartTick(0), "0円");
  assert.equal(formatChartTick(1500000), "150万円");
});

test("実現損益は税引後を主表示、税引前を括弧内へ表示する", () => {
  assert.match(overviewSource, /const receivedValue = Math\.trunc\(item\.taxReference\)/);
  assert.match(overviewSource, /<strong class="\$\{receivedValue[^}]+\}">\$\{receivedValue[^}]+\}<\/strong><small>\(\$\{item\.profit/);
  assert.match(overviewSource, /class="profit-tax-note">SBI実績を優先・未入力分は概算／（）内は税引前損益<\/small>/);
  assert.doesNotMatch(overviewSource, /metricCard\("PF"|metricCard\("最大DD"/);
  assert.match(styles, /\.profit-tax-note\s*\{[^}]*white-space:\s*nowrap;/s);
  assert.match(styles, /\.summary-stats-grid\s*\{[^}]*grid-template-columns:\s*repeat\(3,minmax\(0,1fr\)\)/s);
});

test("現物買付では手数料欄を隠し、現物売却だけ表示する", () => {
  assert.match(appSource, /const showTransactionFee = state\.form\.action === "売却" && \$\("#account-type"\)\.value === "現物";/);
  assert.match(appSource, /classList\.toggle\("hidden", !showTransactionFee\)/);
  assert.match(appSource, /\$\("#transaction-fee"\)\.disabled = !showTransactionFee/);
  assert.match(indexSource, /id="transaction-fee-field" class="hidden"/);
  assert.match(indexSource, /id="transaction-fee-label">売却手数料等<\/span>/);
  assert.doesNotMatch(indexSource, /買付手数料等/);
});

test("サマリは売買記録と同じ過去の日・週・月の期間ロジックを使う", () => {
  assert.match(appSource, /function summaryPeriodStart\(period\)\s*\{[^}]*pnlRange\(period\)\.start;/s);
  assert.match(appSource, /function summaryPeriodEnd\(period\)\s*\{[^}]*pnlRange\(period\)\.end;/s);
  assert.match(appSource, /trade\.date >= summaryPeriodStart\(period\) && trade\.date <= summaryPeriodEnd\(period\)/);
  assert.match(overviewSource, /\[\["all","全期間"\],\["day","一日"\],\["week","週間"\],\["month","月間"\]\]/);
  assert.match(overviewSource, /pnlPeriodSelector\(state\.summaryFilters\.period, "summary-period-picker"\)/);
  assert.match(overviewSource, /state\.pnlSelections\[state\.summaryFilters\.period\] = event\.target\.value/);
  assert.match(appSource, /const period = pnlRange\(state\.pnlPeriod\)/);
});

test("保有銘柄カードを3段構成にし数値と登録ボタンを同じ段へ置く", () => {
  assert.match(overviewSource, /position-row-meta[^>]*>\$\{esc\(position\.market\)\} ・ \$\{esc\(position\.style\)\} ・ \$\{esc\(position\.accountType\)\}/);
  assert.match(overviewSource, /position-row-footer/);
  assert.match(overviewSource, /position-values[^>]*data-action="open-position-buys"/);
  assert.match(overviewSource, /\$\{position\.quantity\.toLocaleString\(\)\}株<\/strong><strong>\$\{yen\(position\.averagePrice, false\)\}/);
  assert.match(overviewSource, />売却記録を登録<\/button>/);
  assert.match(overviewSource, /position-row-footer[^>]*>[\s\S]*position-values[\s\S]*sale-register-button/);
  assert.doesNotMatch(styles, /\.position-row\s*>\s*div\s*\{[^}]*display:\s*grid/);
  assert.match(styles, /\.position-row-footer\s*\{[^}]*width:\s*100%;[^}]*max-width:\s*100%;[^}]*display:\s*flex;[^}]*justify-content:\s*space-between;[^}]*flex-wrap:\s*nowrap;/s);
  assert.match(styles, /\.position-values\s*\{[^}]*min-width:\s*0;[^}]*max-width:\s*100%;[^}]*overflow:\s*hidden;[^}]*flex:\s*1 1 0;/s);
  assert.match(styles, /\.position-values strong\s*\{[^}]*font-size:\s*13px;[^}]*font-weight:\s*500;/s);
});

test("カード編集と売却登録の既存アクションを分離して維持する", () => {
  assert.match(overviewSource, /data-action="open-position-buys"/);
  assert.match(overviewSource, /class="sale-register-button" data-action="sell"/);
  assert.match(appSource, /if \(action === "open-position-buys"\)/);
  assert.match(appSource, /if \(action === "sell"\) openSell/);
  assert.match(styles, /\.position-row-meta\s*\{[^}]*text-overflow:\s*ellipsis;[^}]*white-space:\s*nowrap;/s);
  assert.match(styles, /\.position-row-footer \.sale-register-button\s*\{[^}]*white-space:\s*nowrap;/s);
  assert.match(styles, /\.position-row-footer \.sale-register-button\s*\{[^}]*flex:\s*0 0 auto;/s);
  assert.match(styles, /@media\(max-width:430px\)[\s\S]*\.position-values strong\s*\{[^}]*font-size:\s*11px;/);
});


test("chart highlights use the maximum and final cumulative values", () => {
  assert.deepEqual(createChartHighlights([100000, 300000, 250000]), {
    maximum: 300000,
    current: 250000
  });
  assert.deepEqual(createChartHighlights([-100000, -300000, -250000]), {
    maximum: -100000,
    current: -250000
  });
  assert.equal(createChartHighlights([]), null);
});

test("chart shows the maximum and current values without changing its data", () => {
  assert.match(appSource, /class="chart-highlights"/);
  assert.match(appSource, /yen\(highlights\.maximum\)/);
  assert.match(appSource, /yen\(highlights\.current\)/);
  assert.match(styles, /\.chart-highlights\s*\{[^}]*display:\s*flex;/s);
  assert.match(styles, /\.chart-highlights span\s*\{[^}]*white-space:\s*nowrap;/s);
  assert.match(styles, /@media\(max-width:430px\)[\s\S]*\.chart-highlights\s*\{[^}]*justify-content:\s*space-between;/);
});
