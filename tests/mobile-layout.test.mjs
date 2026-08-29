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

test("取引日の入力欄を銘柄・取引区分と同じ全幅フォーム列へ揃える", () => {
  assert.match(indexSource, /<label class="full">取引日<input id="trade-date" type="date" required><\/label>/);
  assert.match(indexSource, /<div class="form-choice full"><span>取引区分<\/span>/);
  assert.match(indexSource, /<label id="security-field" class="full">銘柄/);
  assert.match(styles, /#trade-date\s*\{[^}]*width:\s*100%;[^}]*box-sizing:\s*border-box;[^}]*padding-inline:\s*0;/s);
  assert.match(styles, /#trade-date::\-webkit-date-and-time-value\s*\{[^}]*min-width:\s*0;[^}]*padding-inline-start:\s*12px;[^}]*text-align:\s*left;/s);
  assert.doesNotMatch(styles, /#trade-date\s*\{[^}]*appearance:\s*none;/s);
});

test("長い銘柄名や設定文は親要素を押し広げず折り返す", () => {
  assert.match(styles, /\.security-option span,[\s\S]*?\.source-note\s*\{[^}]*overflow-wrap:\s*anywhere;/);
});

test("390px・393px・430pxで保有3段目と下部ナビを折り返さず親幅内へ収める", () => {
  assert.match(styles, /\.position-row-footer\s*\{[^}]*flex-wrap:\s*nowrap;/s);
  assert.match(styles, /\.position-row-footer \.sale-register-button\s*\{[^}]*white-space:\s*nowrap;/s);
  assert.match(styles, /@media\(max-width:430px\)[\s\S]*\.position-row-footer\s*\{[^}]*gap:\s*6px;/);
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
