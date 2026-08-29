import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const appSource = await readFile(new URL("../app.js", import.meta.url), "utf8");
const stocksData = JSON.parse(await readFile(new URL("../stocks.json", import.meta.url), "utf8"));
const readingsData = JSON.parse(await readFile(new URL("../stock-readings.json", import.meta.url), "utf8"));
const aliasData = JSON.parse(await readFile(new URL("../stock-search-aliases.json", import.meta.url), "utf8"));

const normalizeSource = appSource.match(/const normalize = .*;/)?.[0] ?? "";
const matcherStart = appSource.indexOf("function securityMatchesSearch");
const matcherEnd = appSource.indexOf("const KEYBOARD_SAFE_INPUT_SELECTOR");
const matcherSource = appSource.slice(matcherStart, matcherEnd);
const securityMatchesSearch = new Function(`${normalizeSource}\n${matcherSource}\nreturn securityMatchesSearch;`)();

function securityFor(code) {
  const security = stocksData.securities.find((item) => item.code === code);
  assert.ok(security, `${code} がstocks.jsonに存在すること`);
  return {
    ...security,
    reading: readingsData.readings[code] ?? "",
    aliases: aliasData.aliases[code] ?? []
  };
}

test("278A Terra Droneは個別aliasを含めた各種入力で検索できる", () => {
  const terraDrone = securityFor("278A");
  for (const query of ["てら", "テラ", "どろーん", "ドローン", "Terra", "terra drone", "278", "78A"]) {
    assert.equal(securityMatchesSearch(terraDrone, query), true, `${query} で一致すること`);
  }
});

test("429A テクセンドフォトマスクはreadingでひらがな検索できる", () => {
  const texend = securityFor("429A");
  for (const query of ["てく", "テク", "ふぉとますく", "フォトマスク", "429"]) {
    assert.equal(securityMatchesSearch(texend, query), true, `${query} で一致すること`);
  }
});

test("aliasファイルはコードごとに読みを安全に追加できる構造である", () => {
  assert.deepEqual(aliasData.aliases["278A"], ["てらどろーん"]);
  for (const [code, aliases] of Object.entries(aliasData.aliases)) {
    assert.match(code, /^[0-9A-Z]+$/);
    assert.ok(Array.isArray(aliases));
    assert.ok(aliases.length > 0);
    assert.ok(aliases.every((alias) => typeof alias === "string" && alias.trim()));
  }
});

test("共通検索関数を買付候補と売買記録候補・結果の両方で使う", () => {
  assert.match(appSource, /state\.securities\.filter\(\(security\) => securityMatchesSearch\(security, query\)\)/);
  assert.match(appSource, /recordSecurityCandidates\(\)\.filter\(\(candidate\) => securityMatchesSearch\(candidate, search\.value\)\)/);
  assert.match(appSource, /return securityMatchesSearch\(\{ code: trade\.code, name: trade\.name, reading: candidate\?\.reading \?\? "", aliases: candidate\?\.aliases \?\? \[\] \}, state\.recordQuery\)/);
  assert.match(appSource, /fetch\("\.\/stock-search-aliases\.json"\)/);
});
