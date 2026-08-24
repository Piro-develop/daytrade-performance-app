import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const styles = await readFile(new URL("../styles.css", import.meta.url), "utf8");
const indexSource = await readFile(new URL("../index.html", import.meta.url), "utf8");
const appSource = await readFile(new URL("../app.js", import.meta.url), "utf8");

test("ページ全体の横overflowと横方向のオーバースクロールを防ぐ", () => {
  assert.match(styles, /html,\s*body\s*\{[^}]*overflow-x:\s*hidden;[^}]*overscroll-behavior-x:\s*none;/s);
  assert.match(styles, /@supports\s*\(overflow-x:\s*clip\)/);
  assert.match(styles, /\.modal-backdrop,\s*\.trade-modal\s*\{[^}]*overflow-x:\s*hidden;/s);
});

test("モーダル・フォーム・gridとflexの子要素をviewport内で縮められる", () => {
  assert.match(styles, /\.app-shell,[\s\S]*?\.position-lot-choice\s*\{[^}]*min-width:\s*0;[^}]*max-width:\s*100%;/);
  assert.match(styles, /input,\s*select,\s*textarea\s*\{[^}]*min-width:\s*0;[^}]*max-width:\s*100%;/s);
  assert.match(styles, /\.allocation-group-row select\s*\{[^}]*width:\s*100%;/s);
});

test("長い銘柄名や設定文は親要素を押し広げず折り返す", () => {
  assert.match(styles, /\.security-option span,[\s\S]*?\.source-note\s*\{[^}]*overflow-wrap:\s*anywhere;/);
});

test("390px・393px・430pxで下部ナビの合計幅が親幅を超えない規則を使う", () => {
  const breakpoint = Number(styles.match(/@media\s*\(max-width:(\d+)px\)\s*\{\s*\.sidebar nav\s*\{\s*flex:\s*1 1 0;/)?.[1]);
  assert.ok([390, 393, 430].every((width) => width <= breakpoint));
  assert.match(styles, /\.settings-nav\s*\{\s*flex:\s*0 0 24%;\s*width:\s*auto;\s*min-width:\s*0;/);
});

test("ズーム・入力操作・縦スクロールを妨げる強制処理を追加しない", () => {
  const viewport = indexSource.match(/<meta name="viewport"[^>]+>/)?.[0] ?? "";
  assert.match(viewport, /width=device-width/);
  assert.doesNotMatch(viewport, /user-scalable|maximum-scale/);
  assert.doesNotMatch(appSource, /touchmove/);
  assert.doesNotMatch(styles, /(?:input|select|textarea)[^{]*\{[^}]*touch-action:/s);
});
