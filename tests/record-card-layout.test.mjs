import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const appSource = await readFile(new URL("../app.js", import.meta.url), "utf8");
const styles = await readFile(new URL("../styles.css", import.meta.url), "utf8");
const recordsSource = appSource.slice(appSource.indexOf("function renderRecordSearchResults"), appSource.indexOf("function renderAnalytics"));

test("売買記録カードは銘柄行と取引情報・損益行の2行構成にする", () => {
  assert.match(recordsSource, /class="record-security"><strong>\$\{esc\(trade\.code\)\}<\/strong><span>\$\{esc\(trade\.name\)\}<\/span><\/span>/);
  assert.match(recordsSource, /class="record-entry-meta"><span>\$\{esc\(accountDetailLabel\(trade\)\)\}\$\{allocationStatus\}<\/span><span>\$\{priceLabel\} \$\{yen\(trade\.price, false\)\}<\/span>/);
  assert.match(recordsSource, /const priceLabel = trade\.action === "買付" \? "買付価格" : "売却価格"/);
  assert.doesNotMatch(recordsSource, /class="style-badge"/);
});

test("売却は税引後損益を主表示し税引前だけを補助表示する", () => {
  const cardTaxBefore = recordsSource.match(/const taxBefore = [^\n]+/)?.[0] ?? "";
  assert.match(recordsSource, /const afterTaxProfit = trade\.realisedProfit === null \? null : afterTaxProfitOf\(trade\)/);
  assert.match(recordsSource, /class="record-entry-result"><strong class="\$\{resultClass\}">\$\{result\}<\/strong>\$\{taxBefore\}<\/span>/);
  assert.match(recordsSource, /<small>（税引前 \$\{yen\(trade\.realisedProfit\)\}）<\/small>/);
  assert.doesNotMatch(cardTaxBefore, /概算|afterTaxSourceLabel/);
});

test("カード寸法と操作を維持し長い銘柄名・スマホ幅のoverflowを防ぐ", () => {
  assert.match(recordsSource, /class="record-entry-main" data-action="edit"/);
  assert.match(styles, /\.record-entry\{min-height:56px;/);
  assert.match(styles, /\.record-entry-main\s*\{[^}]*grid-template-columns:\s*minmax\(0,1fr\) auto 14px;[^}]*grid-template-areas:[^}]*"security security chevron"[^}]*"meta result chevron";/s);
  assert.match(styles, /\.record-security span\s*\{[^}]*min-width:\s*0;/s);
  assert.match(styles, /\.record-entry-meta\s*\{[^}]*min-width:\s*0;[^}]*overflow:\s*hidden;/s);
  assert.match(styles, /@media\(max-width:720px\)\s*\{[^}]*\.record-entry-main\s*\{[^}]*grid-template-columns:\s*minmax\(0,1fr\) auto 10px;/s);
});
