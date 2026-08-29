import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const appSource = await readFile(new URL("../app.js", import.meta.url), "utf8");
const styles = await readFile(new URL("../styles.css", import.meta.url), "utf8");
const candidatesSource = appSource.slice(appSource.indexOf("function recordSecurityCandidates"), appSource.indexOf("function renderRecordSearchOptions"));
const optionsSource = appSource.slice(appSource.indexOf("function renderRecordSearchOptions"), appSource.indexOf("function renderRecordSearchResults"));
const recordsSource = appSource.slice(appSource.indexOf("function renderRecordSearchResults"), appSource.indexOf("function renderAnalytics"));

test("候補は過去tradeだけからコード単位で重複を除きreadingとaliasを補う", () => {
  const state = {
    trades: [
      { code: "429A", name: "テクセンドフォトマスク" },
      { code: "429A", name: "テクセンドフォトマスク" },
      { code: "OLD1", name: "旧データ銘柄" }
    ],
    securities: [
      { code: "429A", name: "テクセンドフォトマスク", reading: "テクセンドフォトマスク", aliases: ["てくせんど"] },
      { code: "9999", name: "未取引銘柄", reading: "ミトリヒキメイガラ" }
    ]
  };
  const candidates = new Function("state", `${candidatesSource}; return recordSecurityCandidates();`)(state);
  assert.deepEqual(candidates, [
    { code: "429A", name: "テクセンドフォトマスク", reading: "テクセンドフォトマスク", aliases: ["てくせんど"] },
    { code: "OLD1", name: "旧データ銘柄", reading: "", aliases: [] }
  ]);
});

test("候補と検索結果はコード・銘柄名・reading・aliasを共通関数で部分一致検索する", () => {
  assert.match(optionsSource, /securityMatchesSearch\(candidate, search\.value\)/);
  assert.match(recordsSource, /securityMatchesSearch\(\{ code: trade\.code, name: trade\.name, reading: candidate\?\.reading \?\? "", aliases: candidate\?\.aliases \?\? \[\] \}, state\.recordQuery\)/);
  assert.match(optionsSource, /data-action="choose-record-security"/);
  assert.match(optionsSource, /<strong>\$\{esc\(candidate\.code\)\}<\/strong><span>\$\{esc\(candidate\.name\)\}<\/span>/);
});

test("候補リストは検索欄直下に表示し入力欄の部分更新構造を維持する", () => {
  assert.match(recordsSource, /class="record-search-wrap"/);
  assert.match(recordsSource, /id="record-search-options" class="security-options record-search-options hidden"/);
  assert.match(styles, /\.record-search-wrap\{position:relative;width:min\(460px,100%\);min-width:0\}/);
  assert.match(recordsSource, /renderRecordSearchResults\(calculateLedger\(state\.trades\)\); renderRecordSearchOptions\(\);/);
  assert.doesNotMatch(optionsSource, /state\.securities\.filter|renderRecords\(/);
});

test("候補選択は同じ検索inputへ値を設定してその銘柄だけへ絞り込む", () => {
  assert.match(appSource, /if \(action === "choose-record-security"\)/);
  assert.match(appSource, /state\.recordSecurityCode = candidate\.code/);
  assert.match(appSource, /state\.recordQuery = `\$\{candidate\.code\}　\$\{candidate\.name\}`/);
  assert.match(appSource, /search\.value = state\.recordQuery/);
  assert.match(appSource, /renderRecordSearchResults\(calculateLedger\(state\.trades\)\)/);
  assert.match(recordsSource, /if \(state\.recordSecurityCode\) return String\(trade\.code \?\? ""\) === state\.recordSecurityCode/);
  assert.match(recordsSource, /state\.recordSecurityCode = null; state\.recordQuery = event\.currentTarget\.value/);
});
