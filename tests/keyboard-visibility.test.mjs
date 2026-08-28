import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const appSource = await readFile(new URL("../app.js", import.meta.url), "utf8");
const indexSource = await readFile(new URL("../index.html", import.meta.url), "utf8");

test("買付銘柄と売買記録検索は同じキーボード可視化対象を使う", () => {
  assert.match(indexSource, /id="security-query" class="keyboard-safe-input"/);
  assert.match(appSource, /id="record-search" class="keyboard-safe-input"/);
  assert.match(appSource, /const KEYBOARD_SAFE_INPUT_SELECTOR = "\.keyboard-safe-input"/);
  assert.match(appSource, /document\.addEventListener\("focusin"/);
});

test("Visual Viewport変化後もフォーカス中の入力欄を可視領域へ戻す", () => {
  assert.match(appSource, /window\.visualViewport\?\.addEventListener\("resize", keepFocusedInputVisible\)/);
  assert.match(appSource, /window\.visualViewport\?\.addEventListener\("scroll", keepFocusedInputVisible\)/);
  assert.match(appSource, /requestAnimationFrame\(\(\) => \{/);
  assert.match(appSource, /field\.getBoundingClientRect\(\)/);
  assert.match(appSource, /field\.scrollIntoView\(\{ block: "center", inline: "nearest", behavior: "auto" \}\)/);
});

test("売買記録の再描画後も入力位置とカーソルを保ち強制スクロールを重ねない", () => {
  assert.match(appSource, /next\?\.focus\(\{ preventScroll: true \}\)/);
  assert.match(appSource, /next\?\.setSelectionRange\(state\.recordQuery\.length, state\.recordQuery\.length\)/);
  assert.match(appSource, /keepFocusedInputVisible\(\)/);
  assert.doesNotMatch(appSource, /touchmove/);
});
