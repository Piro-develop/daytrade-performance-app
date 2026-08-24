import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createChartAxis, createChartHighlights, formatChartTick } from "../summary-ui.mjs";

const appSource = await readFile(new URL("../app.js", import.meta.url), "utf8");
const styles = await readFile(new URL("../styles.css", import.meta.url), "utf8");
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

test("実現損益の注意書きを1行表示しPF・DDをサマリから外す", () => {
  assert.match(overviewSource, /class="profit-tax-note">（）内は税引後損益<\/small>/);
  assert.doesNotMatch(overviewSource, /metricCard\("PF"|metricCard\("最大DD"/);
  assert.match(styles, /\.profit-tax-note\s*\{[^}]*white-space:\s*nowrap;/s);
  assert.match(styles, /\.summary-stats-grid\s*\{[^}]*grid-template-columns:\s*repeat\(3,minmax\(0,1fr\)\)/s);
});

test("保有銘柄カードを3段構成にし数値と登録ボタンを同じ段へ置く", () => {
  assert.match(overviewSource, /position-row-meta[^>]*>\$\{esc\(position\.market\)\} ・ \$\{esc\(position\.style\)\} ・ \$\{esc\(position\.accountType\)\}/);
  assert.match(overviewSource, /position-row-footer/);
  assert.match(overviewSource, /position-values[^>]*data-action="open-position-buys"/);
  assert.match(overviewSource, /\$\{position\.quantity\.toLocaleString\(\)\}株<\/strong><strong>\$\{yen\(position\.averagePrice, false\)\}/);
  assert.match(overviewSource, />売買記録を登録<\/button>/);
  assert.match(styles, /\.position-row-footer\s*\{[^}]*display:\s*flex;[^}]*justify-content:\s*space-between;/s);
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
