import { initializeApp } from "https://www.gstatic.com/firebasejs/11.10.0/firebase-app.js";
import { getAuth, GoogleAuthProvider, signInWithPopup, signInWithRedirect, onAuthStateChanged, signOut } from "https://www.gstatic.com/firebasejs/11.10.0/firebase-auth.js";
import { getFirestore, collection, addDoc, deleteDoc, doc, onSnapshot, setDoc, serverTimestamp } from "https://www.gstatic.com/firebasejs/11.10.0/firebase-firestore.js";

const firebaseConfig = {
  apiKey: "AIzaSyBcF8KJ6ltfl5yyL-5445h3u93Ej4hWtrk",
  authDomain: "daytrade-performance-app.firebaseapp.com",
  projectId: "daytrade-performance-app",
  storageBucket: "daytrade-performance-app.firebasestorage.app",
  messagingSenderId: "753888387624",
  appId: "1:753888387624:web:e43b22d15d165dd4484b1d"
};

const TAX_RATE = 0.20315;
const PNL_HISTORY_START = "2026-07-01";
const PNL_WEEK_START = "2026-07-20";
const PNL_MONTH_START = "2026-07";
const app = initializeApp(firebaseConfig);
const auth = getAuth(app);
const db = getFirestore(app);
const provider = new GoogleAuthProvider();
provider.setCustomParameters({ prompt: "select_account" });

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const esc = (value = "") => String(value).replace(/[&<>'"]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[char]);
const localDate = (date = new Date()) => `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
const currentWeekStart = () => { const date = new Date(); date.setHours(0, 0, 0, 0); const day = date.getDay(); date.setDate(date.getDate() - (day === 0 ? 6 : day - 1)); return localDate(date); };
const yen = (value, signed = true) => `${signed && value > 0 ? "+ " : signed && value < 0 ? "− " : ""}${Math.abs(value).toLocaleString("ja-JP", { maximumFractionDigits: 0 })}円`;
const afterTax = (profit) => profit > 0 ? profit * (1 - TAX_RATE) : profit;
const normalize = (value) => String(value ?? "").normalize("NFKC").toLowerCase().replace(/[ァ-ヶ]/g, (char) => String.fromCharCode(char.charCodeAt(0) - 0x60)).replace(/[\s・（）()株式会社]/g, "");
const byTimeAsc = (a, b) => a.date.localeCompare(b.date) || (a.createdAt ?? 0) - (b.createdAt ?? 0) || a.id.localeCompare(b.id);

const state = {
  user: null,
  trades: [],
  securities: [],
  stocksAsOf: "",
  activeView: "overview",
  range: "30",
  recordQuery: "",
  pnlPeriod: "day",
  pnlSelections: { day: localDate(), week: currentWeekStart(), month: localDate().slice(0, 7) },
  unsubscribe: null,
  form: { mode: "new", action: "買付", editId: null, selected: null, manual: false, sellContext: null }
};

const headings = {
  overview: ["投資運用記録", "デイトレ・スイングの振り返りと成績"],
  records: ["売買記録", "買付から売却までの履歴を確認"],
  analytics: ["パフォーマンス分析", "確定した損益の傾向と改善ポイント"],
  settings: ["設定", "表示とデータ管理"]
};

function showToast(message) {
  const toast = $("#toast");
  toast.textContent = message;
  toast.classList.remove("hidden");
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => toast.classList.add("hidden"), 2600);
}

function calculateLedger(trades) {
  const positions = new Map();
  const results = new Map();
  let invalid = null;
  [...trades].sort(byTimeAsc).forEach((trade) => {
    const current = positions.get(trade.code) ?? { code: trade.code, name: trade.name, market: trade.market ?? "", quantity: 0, averagePrice: 0 };
    if (trade.action === "買付") {
      const quantity = current.quantity + trade.quantity;
      const total = current.quantity * current.averagePrice + trade.quantity * trade.price;
      positions.set(trade.code, { ...current, name: trade.name, market: trade.market ?? current.market, quantity, averagePrice: total / quantity });
      results.set(trade.id, { realisedProfit: null, averageCostAtSale: null });
      return;
    }
    if (trade.quantity > current.quantity) {
      invalid ??= `${trade.date}の${trade.name}は、保有株数を${trade.quantity - current.quantity}株超えて売却しています。`;
      results.set(trade.id, { realisedProfit: null, averageCostAtSale: null });
      return;
    }
    const realisedProfit = (trade.price - current.averagePrice) * trade.quantity;
    const quantity = current.quantity - trade.quantity;
    positions.set(trade.code, { ...current, quantity, averagePrice: quantity ? current.averagePrice : 0 });
    results.set(trade.id, { realisedProfit, averageCostAtSale: current.averagePrice });
  });
  return {
    invalid,
    positions: [...positions.values()].filter((position) => position.quantity > 0),
    calculated: trades.map((trade) => ({ ...trade, ...(results.get(trade.id) ?? { realisedProfit: null, averageCostAtSale: null }) }))
  };
}

function rangeStart(days) {
  if (days === "all") return "0000-00-00";
  const date = new Date();
  date.setHours(0, 0, 0, 0);
  date.setDate(date.getDate() - Number(days) + 1);
  return localDate(date);
}

function completedForRange(calculated) {
  const start = rangeStart(state.range);
  return calculated.filter((trade) => trade.action === "売却" && trade.realisedProfit !== null && trade.date >= start);
}

function statsFor(completed) {
  const wins = completed.filter((trade) => trade.realisedProfit > 0);
  const losses = completed.filter((trade) => trade.realisedProfit < 0);
  const grossProfit = wins.reduce((sum, trade) => sum + trade.realisedProfit, 0);
  const grossLoss = Math.abs(losses.reduce((sum, trade) => sum + trade.realisedProfit, 0));
  let total = 0, peak = 0, maxDrawdown = 0;
  [...completed].sort(byTimeAsc).forEach((trade) => {
    total += trade.realisedProfit;
    peak = Math.max(peak, total);
    maxDrawdown = Math.min(maxDrawdown, total - peak);
  });
  return { profit: grossProfit - grossLoss, taxReference: completed.reduce((sum, trade) => sum + afterTax(trade.realisedProfit), 0), winRate: completed.length ? wins.length / completed.length * 100 : 0, winCount: wins.length, saleCount: completed.length, pf: grossLoss ? grossProfit / grossLoss : grossProfit ? Infinity : 0, maxDrawdown };
}

function chartSvg(completed) {
  if (!completed.length) return '<div class="chart-empty">売却記録を登録するとグラフを表示します</div>';
  let running = 0;
  const values = [...completed].sort(byTimeAsc).map((trade) => ({ date: trade.date, value: running += trade.realisedProfit }));
  const min = Math.min(0, ...values.map((item) => item.value));
  const max = Math.max(0, ...values.map((item) => item.value));
  const spread = max - min || 1;
  const points = values.map((item, index) => `${values.length === 1 ? 50 : index / (values.length - 1) * 100},${94 - (item.value - min) / spread * 84}`).join(" ");
  const zeroY = 94 - (0 - min) / spread * 84;
  const yTicks = [...new Set([max, 0, min])].map((value) => ({ value, y: 94 - (value - min) / spread * 84 }));
  const dates = [...new Set(values.map((item) => item.date))];
  const labelIndexes = dates.length === 1 ? [0] : dates.length === 2 ? [0, 1] : [0, Math.floor((dates.length - 1) / 2), dates.length - 1];
  const dateLabels = labelIndexes.map((index) => dates[index].replaceAll("-", "/"));
  return `<div class="chart-figure"><div class="chart-y-axis">${yTicks.map((tick) => `<span style="top:${tick.y}%">${yen(tick.value, tick.value < 0)}</span>`).join("")}</div><svg viewBox="0 0 100 100" preserveAspectRatio="none" role="img" aria-label="累積実現損益グラフ"><defs><linearGradient id="chart-area" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#5ba77b" stop-opacity=".4"/><stop offset="1" stop-color="#5ba77b" stop-opacity=".02"/></linearGradient></defs>${yTicks.filter((tick) => tick.value !== 0).map((tick) => `<line class="chart-grid" x1="0" y1="${tick.y}" x2="100" y2="${tick.y}"/>`).join("")}<line class="chart-zero" x1="0" y1="${zeroY}" x2="100" y2="${zeroY}"/><polygon class="chart-area" points="${points} 100,100 0,100"/><polyline class="chart-line" points="${points}"/></svg><div class="chart-dates ${dateLabels.length === 1 ? "single" : ""}">${dateLabels.map((date) => `<span>${date}</span>`).join("")}</div></div>`;
}

function render() {
  if (!state.user) return;
  const ledger = calculateLedger(state.trades);
  const completed = completedForRange(ledger.calculated);
  const stats = statsFor(completed);
  renderOverview(ledger, completed, stats);
  renderRecords(ledger);
  renderAnalytics(ledger);
  renderSettings();
}

function renderOverview(ledger, completed, stats) {
  const recent = [...ledger.calculated].sort((a, b) => -byTimeAsc(a, b)).slice(0, 4);
  const positions = new Map(ledger.positions.map((position) => [position.code, position]));
  const summaryStats = [["全体", stats], ...["デイトレ", "スイング"].map((style) => [style, statsFor(completed.filter((trade) => trade.style === style))])];
  const profitSummary = summaryStats.map(([label, item]) => { const afterTaxValue = Math.trunc(item.taxReference); return `<div class="summary-breakdown-row"><span>${label}：</span><span class="summary-breakdown-values"><strong class="${item.profit > 0 ? "positive" : item.profit < 0 ? "negative" : "muted"}">${item.profit === 0 ? "± 0円" : yen(item.profit)}</strong><small>(${yen(afterTaxValue, afterTaxValue < 0)})</small></span></div>`; }).join("");
  const winSummary = summaryStats.map(([label, item]) => `<div class="summary-breakdown-row"><span>${label}：</span><span class="summary-breakdown-values"><strong class="positive">${item.winRate.toFixed(1)}%</strong><small>(${item.winCount}/${item.saleCount})</small></span></div>`).join("");
  $("#overview-view").innerHTML = `
    <div class="stats-grid">
      <article class="stat-card breakdown-card"><div class="stat-top"><span>実現損益</span><i>円</i></div><div class="summary-breakdown">${profitSummary}</div></article>
      <article class="stat-card breakdown-card"><div class="stat-top"><span>勝率</span><i>◎</i></div><div class="summary-breakdown">${winSummary}</div></article>
      <article class="stat-card"><div class="stat-top"><span>PF</span><i>⚖</i></div><strong class="positive">${Number.isFinite(stats.pf) ? stats.pf.toFixed(2) : "∞"}</strong><small>総利益 ÷ 総損失</small></article>
      <article class="stat-card"><div class="stat-top"><span>最大DD</span><i>↘</i></div><strong class="negative">${yen(stats.maxDrawdown)}</strong><small>累積損益の最大下落額</small></article>
    </div>
    <div class="dashboard-grid">
      <article class="panel"><div class="panel-heading"><div><p class="section-kicker">PERFORMANCE</p><h2>累積実現損益</h2></div><span class="period-badge">${state.range === "all" ? "全期間" : `過去${state.range}日`}</span></div><div class="chart-wrap">${chartSvg(completed)}</div></article>
      <article class="panel"><div class="panel-heading"><div><p class="section-kicker">OPEN POSITIONS</p><h2>保有中の銘柄</h2></div><span class="period-badge">${ledger.positions.length}銘柄</span></div><div class="position-list">${ledger.positions.map((position) => `
        <div class="position-row"><div><strong>${esc(position.code)} ${esc(position.name)}</strong><small>${esc(position.market)} ・ 平均取得 ${yen(position.averagePrice, false)}</small></div><div class="position-actions"><strong>${position.quantity.toLocaleString()}株</strong><button class="sale-register-button" data-action="sell" data-code="${esc(position.code)}" type="button">売却記録を登録</button></div></div>`).join("") || '<div class="empty-state">現在の保有銘柄はありません</div>'}</div></article>
    </div>
    <article class="panel recent-panel"><div class="panel-heading"><div><p class="section-kicker">RECENT ACTIVITY</p><h2>直近の売買</h2></div><button class="text-button" data-action="view-records" type="button">すべて見る ›</button></div><div class="trade-list compact">${recent.map((trade) => tradeCard(trade, positions)).join("") || '<div class="empty-state">「＋」から最初の買付を登録してください</div>'}</div></article>`;
}

function tradeCard(trade, positions) {
  const position = positions.get(trade.code);
  const result = trade.realisedProfit === null ? (position ? "保有中" : "売却済み") : yen(trade.realisedProfit);
  const resultClass = trade.realisedProfit === null ? "muted" : trade.realisedProfit >= 0 ? "positive" : "negative";
  return `<div class="trade-row"><span class="side-badge ${trade.action === "買付" ? "buy" : "sell"}">${trade.action === "買付" ? "BUY" : "SELL"}</span><div class="trade-main"><strong>${esc(trade.code)} ${esc(trade.name)}</strong><small>${trade.date.replaceAll("-", "/")} ・ ${esc(trade.style)} ・ ${yen(trade.price, false)} × ${trade.quantity.toLocaleString()}株</small></div><div class="trade-result"><strong class="${resultClass}">${result}</strong>${trade.action === "買付" && position ? `<button class="sale-register-button" data-action="sell" data-code="${esc(trade.code)}" data-style="${esc(trade.style)}" data-date="${esc(trade.date)}" type="button">売却記録を登録</button>` : ""}</div></div>`;
}

function parseLocalDate(value) {
  return new Date(`${value}T00:00:00`);
}

function japaneseDate(value) {
  const date = parseLocalDate(value);
  return `${date.getFullYear()}年${date.getMonth() + 1}月${date.getDate()}日`;
}

function weekLabel(start) {
  const weekdays = ["日", "月", "火", "水", "木", "金", "土"];
  const monthDay = (date) => `${date.getMonth() + 1}/${date.getDate()}（${weekdays[date.getDay()]}）`;
  const end = new Date(start);
  end.setDate(end.getDate() + 4);
  return `${monthDay(start)}〜${monthDay(end)}`;
}

function weekOptions() {
  const options = [];
  const current = new Date();
  current.setHours(0, 0, 0, 0);
  const day = current.getDay();
  current.setDate(current.getDate() - (day === 0 ? 6 : day - 1));
  for (const start = parseLocalDate(PNL_WEEK_START); start <= current; start.setDate(start.getDate() + 7)) {
    options.push({ value: localDate(start), label: weekLabel(start) });
  }
  return options;
}

function monthOptions() {
  const options = [];
  const current = new Date();
  current.setHours(0, 0, 0, 0);
  current.setDate(1);
  for (const start = parseLocalDate(`${PNL_MONTH_START}-01`); start <= current; start.setMonth(start.getMonth() + 1)) {
    options.push({ value: localDate(start).slice(0, 7), label: `${start.getFullYear()}年${start.getMonth() + 1}月` });
  }
  return options;
}

function pnlRange(period) {
  const selection = state.pnlSelections[period];
  if (period === "day") {
    const date = parseLocalDate(selection);
    return { start: selection, end: selection, label: `${date.getFullYear()}/${date.getMonth() + 1}/${date.getDate()}` };
  }
  if (period === "week") {
    const start = parseLocalDate(selection);
    const end = new Date(start);
    end.setDate(end.getDate() + 4);
    return { start: selection, end: localDate(end), label: weekLabel(start) };
  }
  const start = parseLocalDate(`${selection}-01`);
  const end = new Date(start);
  end.setFullYear(end.getFullYear(), end.getMonth() + 1, 0);
  return { start: localDate(start), end: localDate(end), label: `${start.getFullYear()}年${start.getMonth() + 1}月1日〜${end.getDate()}日` };
}

function pnlPeriodSelector(period) {
  if (period === "day") {
    return `<label><span>対象日</span><input id="pnl-period-picker" type="date" min="${PNL_HISTORY_START}" max="${localDate()}" value="${state.pnlSelections.day}"></label>`;
  }
  const options = period === "week" ? weekOptions() : monthOptions();
  const label = period === "week" ? "対象週" : "対象月";
  return `<label><span>${label}</span><select id="pnl-period-picker">${options.map((option) => `<option value="${option.value}" ${state.pnlSelections[period] === option.value ? "selected" : ""}>${option.label}</option>`).join("")}</select></label>`;
}

function renderRecords(ledger) {
  const term = normalize(state.recordQuery);
  const records = [...ledger.calculated].filter((trade) => !term || normalize(`${trade.code}${trade.name}`).includes(term)).sort((a, b) => -byTimeAsc(a, b));
  const recordGroups = [];
  records.forEach((trade) => {
    let group = recordGroups.at(-1);
    if (!group || group.date !== trade.date) {
      group = { date: trade.date, trades: [] };
      recordGroups.push(group);
    }
    group.trades.push(trade);
  });
  const completed = ledger.calculated.filter((trade) => trade.action === "売却" && trade.realisedProfit !== null);
  const period = pnlRange(state.pnlPeriod);
  const totalPnl = completed.reduce((sum, trade) => sum + trade.realisedProfit, 0);
  const selectedPnl = completed.filter((trade) => trade.date >= period.start && trade.date <= period.end).reduce((sum, trade) => sum + trade.realisedProfit, 0);
  const positions = new Map(ledger.positions.map((position) => [position.code, position]));
  $("#records-view").innerHTML = `
    <div class="pnl-overview">
      <article class="pnl-card"><div><p class="section-kicker">TOTAL PROFIT / LOSS</p><h2>全期間の累計損益</h2></div><strong class="${totalPnl >= 0 ? "positive" : "negative"}">${yen(totalPnl)}</strong><small>売却済み取引の利益と損失を全期間で合算</small></article>
      <article class="pnl-card"><div class="pnl-card-heading"><div><p class="section-kicker">PERIOD PROFIT / LOSS</p><h2>期間別の損益</h2></div><div class="pnl-period-switch">${[["day","一日"],["week","週間"],["month","月間"]].map(([value,label]) => `<button class="${state.pnlPeriod === value ? "active" : ""}" data-action="pnl-period" data-period="${value}" type="button">${label}</button>`).join("")}</div></div>
      <div class="pnl-period-selector">${pnlPeriodSelector(state.pnlPeriod)}</div>
      <strong class="${selectedPnl >= 0 ? "positive" : "negative"}">${yen(selectedPnl)}</strong><small>${period.label} ・ 表示期間内の売却済み取引について、利益と損失を合算</small></article>
    </div>
    <div class="view-panel records-list-panel"><div class="records-toolbar"><label class="search-field">⌕<input id="record-search" value="${esc(state.recordQuery)}" placeholder="銘柄コード・銘柄名で検索"></label><div class="record-summary"><span>${records.length}件</span><strong class="${records.reduce((sum,t)=>sum+(t.realisedProfit??0),0)>=0?"positive":"negative"}">${yen(records.reduce((sum,t)=>sum+(t.realisedProfit??0),0))}</strong></div></div>
    <div class="record-groups">${recordGroups.map((group) => `<section class="record-day"><h3>${japaneseDate(group.date)}</h3><div class="record-day-list">${group.trades.map((trade) => {
      const result = trade.action === "買付" ? "買付" : trade.realisedProfit === null ? "確認要" : yen(trade.realisedProfit);
      const resultClass = trade.action === "買付" ? "buy-text" : trade.realisedProfit === null ? "muted" : trade.realisedProfit >= 0 ? "positive" : "negative";
      return `<div class="record-entry"><button class="record-entry-main" data-action="edit" data-id="${esc(trade.id)}" type="button"><span class="style-badge">${esc(trade.style)}</span><span class="record-security"><strong>${esc(trade.code)}</strong><span>${esc(trade.name)}</span></span><strong class="record-entry-result ${resultClass}">${result}</strong><span class="record-chevron">›</span></button><button class="record-delete" data-action="delete" data-id="${esc(trade.id)}" title="削除" type="button">削</button></div>`;
    }).join("")}</div></section>`).join("") || `<div class="empty-state">該当する売買はありません</div>`}</div></div>`;
  const search = $("#record-search");
  search?.addEventListener("input", (event) => { state.recordQuery = event.target.value; renderRecords(calculateLedger(state.trades)); requestAnimationFrame(() => { const next = $("#record-search"); next?.focus(); next?.setSelectionRange(state.recordQuery.length, state.recordQuery.length); }); });
  $("#pnl-period-picker")?.addEventListener("change", (event) => { state.pnlSelections[state.pnlPeriod] = event.target.value; renderRecords(calculateLedger(state.trades)); });
}

function renderAnalytics(ledger) {
  const completed = ledger.calculated.filter((trade) => trade.action === "売却" && trade.realisedProfit !== null);
  const stats = statsFor(completed);
  const score = completed.length ? Math.round(Math.max(0, Math.min(100, 45 + stats.winRate * .35 + Math.min(Number.isFinite(stats.pf) ? stats.pf : 4, 4) * 8))) : 0;
  const styleAmount = (style) => completed.filter((trade) => trade.style === style).reduce((sum, trade) => sum + trade.realisedProfit, 0);
  $("#analytics-view").innerHTML = `<div class="analytics-layout"><article class="view-panel score-panel"><p class="section-kicker">TRADING SCORE</p><div class="score-ring"><span>${score}</span><small>/ 100</small></div><h2>${completed.length ? (score >= 70 ? "安定したパフォーマンス" : "改善余地があります") : "売却記録がありません"}</h2><p>売却済み取引だけを分析し、保有中の含み損益は含みません。</p></article><article class="view-panel"><div class="panel-heading"><div><p class="section-kicker">TRADE STYLE</p><h2>取引区分別の実現損益</h2></div></div><div class="style-results">${["デイトレ","スイング"].map((style) => { const amount=styleAmount(style); return `<div><span>${style}</span><strong class="${amount>=0?"positive":"negative"}">${yen(amount)}</strong><small>税引後参考 ${yen(completed.filter(t=>t.style===style).reduce((s,t)=>s+afterTax(t.realisedProfit),0))}</small></div>`; }).join("")}</div></article><article class="view-panel"><div class="panel-heading"><div><p class="section-kicker">INSIGHTS</p><h2>振り返りポイント</h2></div></div><div class="insight-list"><div><span>01</span><p><strong>売買を実際の約定単位で記録</strong><small>買付と売却を分け、売却時に損益を確定します。</small></p></div><div><span>02</span><p><strong>平均取得価格を自動更新</strong><small>追加購入も含めた加重平均で計算します。</small></p></div><div><span>03</span><p><strong>保有数超過を登録前に防止</strong><small>履歴の修正・削除時にも整合性を確認します。</small></p></div></div></article></div>`;
}

function renderSettings() {
  $("#settings-view").innerHTML = `<div class="settings-layout"><article class="view-panel settings-card"><p class="section-kicker">ACCOUNT</p><h2>ログイン中のアカウント</h2><div class="setting-row"><span class="account-chip">${state.user.photoURL ? `<img src="${esc(state.user.photoURL)}" alt="">` : ""}<span><strong>${esc(state.user.displayName || "Googleユーザー")}</strong><small>${esc(state.user.email || "")}</small></span></span><button class="secondary-button" data-action="logout" type="button">ログアウト</button></div></article><article class="view-panel settings-card"><p class="section-kicker">CALCULATION</p><h2>計算設定</h2><div class="setting-row"><span><strong>実現損益</strong><small>（売却価格 − 平均取得価格）× 売却株数</small></span><span class="fixed-value">税引前を基本表示</span></div><div class="setting-row"><span><strong>税引後参考値</strong><small>利益に20.315％を単純適用。実際の損益通算・還付とは異なる場合があります。</small></span><span class="fixed-value">参考表示</span></div></article><article class="view-panel settings-card"><p class="section-kicker">DATA</p><h2>データ管理</h2><div class="setting-row"><span><strong>Firebase同期</strong><small>Googleログインしたご本人の端末間で自動同期</small></span><span class="fixed-value">接続済み</span></div><div class="setting-row"><span><strong>CSVバックアップ</strong><small>${state.trades.length}件の売買記録を書き出します</small></span><button class="secondary-button" data-action="csv" type="button">書き出す</button></div><p class="source-note">銘柄検索：JPX「東証上場銘柄一覧」${esc(state.stocksAsOf)}時点。プライム・スタンダード・グロースの国内普通株${state.securities.length.toLocaleString()}銘柄を収録。</p></article></div>`;
}

function switchView(view) {
  state.activeView = view;
  $$(".nav-item").forEach((button) => button.classList.toggle("active", button.dataset.view === view));
  $$(".app-view").forEach((section) => section.classList.add("hidden"));
  $(`#${view}-view`).classList.remove("hidden");
  $("#page-title").textContent = headings[view][0];
  $("#page-subtitle").textContent = headings[view][1];
  $("#range-control").classList.toggle("hidden", view === "settings" || view === "records");
  $("#open-buy").classList.toggle("hidden", view === "settings");
}

function resetForm() {
  state.form = { mode: "new", action: "買付", editId: null, selected: null, manual: false, sellContext: null };
  $("#trade-form").reset();
  $("#trade-date").value = localDate();
  $("#form-error").textContent = "";
  $("#security-options").classList.add("hidden");
  $("#manual-fields").classList.add("hidden");
  $("#security-field").classList.remove("hidden");
  $("#fixed-security").classList.add("hidden");
  $("#trade-quantity").removeAttribute("max");
  $("#sell-from-edit").classList.add("hidden");
}

function openBuy(editTrade = null) {
  resetForm();
  state.form.mode = editTrade ? "edit" : "new";
  state.form.action = "買付";
  state.form.editId = editTrade?.id ?? null;
  $("#modal-kicker").textContent = editTrade ? "EDIT POSITION" : "NEW POSITION";
  $("#modal-title").textContent = editTrade ? "買付記録を修正" : "買付記録を登録";
  $("#price-label").textContent = "取得価格";
  $("#save-trade").textContent = editTrade ? "修正を保存" : "買付を記録";
  $("#calculation-note").className = "calculation-note full";
  $("#calculation-note").innerHTML = "<strong>買付後の保有に追加します</strong><small>同じ銘柄を保有中の場合は、平均取得価格を自動更新します。</small>";
  $("#quantity-helper").innerHTML = "";
  if (editTrade) {
    const found = state.securities.find((security) => security.code === editTrade.code);
    state.form.selected = found ?? { code: editTrade.code, name: editTrade.name, market: editTrade.market ?? "手動登録" };
    $("#security-query").value = `${editTrade.code}　${editTrade.name}`;
    $("#trade-date").value = editTrade.date;
    $("#trade-style").value = editTrade.style;
    $("#trade-price").value = editTrade.price;
    $("#trade-quantity").value = editTrade.quantity;
    $("#trade-note").value = editTrade.note ?? "";
    if (calculateLedger(state.trades).positions.some((position) => position.code === editTrade.code)) $("#sell-from-edit").classList.remove("hidden");
  }
  $("#modal-backdrop").classList.remove("hidden");
}

function openSell(code, style = "スイング", editTrade = null, defaultDate = null) {
  resetForm();
  const ledger = calculateLedger(state.trades);
  const position = ledger.positions.find((item) => item.code === code);
  const calculatedEdit = editTrade ? ledger.calculated.find((item) => item.id === editTrade.id) : null;
  const maxQuantity = (position?.quantity ?? 0) + (editTrade?.quantity ?? 0);
  const averagePrice = calculatedEdit?.averageCostAtSale ?? position?.averagePrice ?? 0;
  state.form = { mode: editTrade ? "edit" : "new", action: "売却", editId: editTrade?.id ?? null, selected: { code, name: editTrade?.name ?? position?.name ?? "", market: editTrade?.market ?? position?.market ?? "" }, manual: false, sellContext: { maxQuantity, averagePrice } };
  $("#modal-kicker").textContent = editTrade ? "EDIT CLOSE" : "CLOSE POSITION";
  $("#modal-title").textContent = editTrade ? "売却記録を修正" : "売却記録を登録";
  $("#price-label").textContent = "売却価格";
  $("#save-trade").textContent = editTrade ? "修正を保存" : "売却を記録";
  $("#security-field").classList.add("hidden");
  $("#fixed-security").classList.remove("hidden");
  $("#fixed-security").innerHTML = `<small>売却対象銘柄</small><strong>${esc(code)}　${esc(state.form.selected.name)}</strong><span>この売却登録では銘柄を変更できません</span>`;
  $("#trade-quantity").max = String(maxQuantity);
  $("#quantity-helper").innerHTML = `上限 ${maxQuantity.toLocaleString()}株 <button id="fill-all" type="button">全株を入力</button>`;
  $("#calculation-note").className = "calculation-note sale full";
  updateSalePreview();
  if (editTrade) {
    $("#trade-date").value = editTrade.date;
    $("#trade-style").value = editTrade.style;
    $("#trade-price").value = editTrade.price;
    $("#trade-quantity").value = editTrade.quantity;
    $("#trade-note").value = editTrade.note ?? "";
    updateSalePreview();
  } else {
    $("#trade-style").value = style;
    if (defaultDate) $("#trade-date").value = defaultDate;
  }
  $("#modal-backdrop").classList.remove("hidden");
}

function updateSalePreview() {
  if (state.form.action !== "売却" || !state.form.sellContext) return;
  const { maxQuantity, averagePrice } = state.form.sellContext;
  const price = Number($("#trade-price").value);
  const quantity = Number($("#trade-quantity").value);
  const profit = price > 0 && quantity > 0 ? (price - averagePrice) * quantity : null;
  $("#calculation-note").innerHTML = `<span><small>売却可能株数</small><strong>${maxQuantity.toLocaleString()}株</strong></span><span><small>平均取得価格</small><strong>${yen(averagePrice,false)}</strong></span><span><small>実現損益見込み</small><strong class="${profit === null ? "muted" : profit >= 0 ? "positive" : "negative"}">${profit === null ? "価格・株数を入力" : yen(profit)}</strong>${profit === null ? "" : `<small>税引後参考 ${yen(afterTax(profit))}</small>`}</span>`;
}

function closeModal() { $("#modal-backdrop").classList.add("hidden"); resetForm(); }

function showSecurityOptions() {
  if (state.form.action !== "買付") return;
  const term = normalize($("#security-query").value);
  const matches = state.securities.filter((security) => !term || normalize(`${security.code}${security.name}${security.reading ?? ""}`).includes(term)).slice(0, 20);
  const options = $("#security-options");
  options.innerHTML = `${matches.map((security) => `<button class="security-option" data-action="choose-security" data-code="${esc(security.code)}" type="button"><strong>${esc(security.code)}</strong><span>${esc(security.name)}</span><small>${esc(security.market)}</small></button>`).join("")}${term ? '<button class="manual-option" data-action="manual-security" type="button">一覧にない銘柄を手動入力</button>' : ""}`;
  options.classList.remove("hidden");
}

async function saveTrade(event) {
  event.preventDefault();
  const button = $("#save-trade");
  const error = $("#form-error");
  error.textContent = "";
  let security = state.form.selected;
  if (state.form.action === "買付" && state.form.manual) {
    const code = $("#manual-code").value.trim().normalize("NFKC").toUpperCase();
    const name = $("#manual-name").value.trim();
    if (!code || !name) { error.textContent = "銘柄コードと銘柄名を入力してください。"; return; }
    security = { code, name, market: "手動登録" };
  }
  if (!security) { error.textContent = "表示された候補から銘柄を選んでください。"; showSecurityOptions(); return; }
  const price = Number($("#trade-price").value);
  const quantity = Number($("#trade-quantity").value);
  if (!(price > 0) || !Number.isInteger(quantity) || quantity < 1) { error.textContent = "価格は0より大きい数、株数は1以上の整数で入力してください。"; return; }
  const existing = state.trades.find((trade) => trade.id === state.form.editId);
  const formMode = state.form.mode;
  const trade = { code: security.code, name: security.name, market: security.market ?? "", action: state.form.action, style: $("#trade-style").value, date: $("#trade-date").value, price, quantity, note: $("#trade-note").value.trim(), createdAt: existing?.createdAt ?? Date.now(), updatedAt: Date.now() };
  const candidate = state.form.mode === "edit" ? state.trades.map((item) => item.id === state.form.editId ? { ...trade, id: item.id } : item) : [...state.trades, { ...trade, id: `pending-${Date.now()}` }];
  const validation = calculateLedger(candidate);
  if (validation.invalid) { error.textContent = validation.invalid; return; }
  button.disabled = true;
  try {
    const tradesRef = collection(db, "users", state.user.uid, "trades");
    const payload = { ...trade, serverUpdatedAt: serverTimestamp() };
    if (formMode === "edit") await setDoc(doc(tradesRef, state.form.editId), payload, { merge: true });
    else await addDoc(tradesRef, payload);
    closeModal();
    showToast(formMode === "edit" ? "売買記録を修正しました" : `${trade.action}記録を登録しました`);
  } catch (cause) {
    console.error(cause);
    error.textContent = "保存できませんでした。通信状態を確認して、もう一度お試しください。";
  } finally { button.disabled = false; }
}

async function removeTrade(id) {
  const trade = state.trades.find((item) => item.id === id);
  if (!trade || !confirm(`${trade.date} ${trade.name}の${trade.action}記録を削除しますか？`)) return;
  const candidate = state.trades.filter((item) => item.id !== id);
  const validation = calculateLedger(candidate);
  if (validation.invalid) { alert(`削除できません。\n${validation.invalid}\n先に後続の売却記録を修正または削除してください。`); return; }
  try { await deleteDoc(doc(db, "users", state.user.uid, "trades", id)); showToast("売買記録を削除しました"); }
  catch (cause) { console.error(cause); alert("削除できませんでした。通信状態をご確認ください。"); }
}

function exportCsv() {
  if (!state.trades.length) { showToast("書き出す売買記録がありません"); return; }
  const ledger = calculateLedger(state.trades);
  const quote = (value) => `"${String(value ?? "").replaceAll('"','""')}"`;
  const rows = [["取引日","銘柄コード","銘柄名","市場","取引区分","売買","約定価格","株数","実現損益（税引前）","税引後参考値","メモ"], ...[...ledger.calculated].sort(byTimeAsc).map((trade) => [trade.date,trade.code,trade.name,trade.market,trade.style,trade.action,trade.price,trade.quantity,trade.realisedProfit ?? "",trade.realisedProfit === null ? "" : Math.round(afterTax(trade.realisedProfit)),trade.note ?? ""])];
  const blob = new Blob(["\uFEFF" + rows.map((row) => row.map(quote).join(",")).join("\r\n")], { type: "text/csv;charset=utf-8" });
  const link = document.createElement("a"); link.href = URL.createObjectURL(blob); link.download = `売買記録_${localDate()}.csv`; link.click(); URL.revokeObjectURL(link.href); showToast("CSVを書き出しました");
}

async function login() {
  $("#login-error").textContent = "";
  try { await signInWithPopup(auth, provider); }
  catch (cause) {
    if (["auth/popup-blocked","auth/cancelled-popup-request"].includes(cause.code)) await signInWithRedirect(auth, provider);
    else if (cause.code !== "auth/popup-closed-by-user") { console.error(cause); $("#login-error").textContent = "ログインできませんでした。もう一度お試しください。"; }
  }
}

async function loadStocks() {
  const [response, readingResponse] = await Promise.all([fetch("./stocks.json"), fetch("./stock-readings.json")]);
  if (!response.ok || !readingResponse.ok) throw new Error("銘柄一覧を読み込めませんでした");
  const [data, readingData] = await Promise.all([response.json(), readingResponse.json()]);
  state.securities = data.securities.map((security) => ({ ...security, reading: readingData.readings[security.code] ?? "" }));
  state.stocksAsOf = data.asOf.replaceAll("-", "/");
}

function subscribeTrades(user) {
  state.unsubscribe?.();
  state.unsubscribe = onSnapshot(collection(db, "users", user.uid, "trades"), (snapshot) => {
    state.trades = snapshot.docs.map((item) => ({ id: item.id, ...item.data() }));
    render();
  }, (cause) => { console.error(cause); showToast("データを読み込めませんでした"); });
}

$("#login-button").addEventListener("click", login);
$("#open-buy").addEventListener("click", () => openBuy());
$("#close-modal").addEventListener("click", closeModal);
$("#cancel-modal").addEventListener("click", closeModal);
$("#sell-from-edit").addEventListener("click", () => { const trade = state.trades.find((item) => item.id === state.form.editId); if (!trade) return; closeModal(); openSell(trade.code, trade.style, null, trade.date); });
$("#trade-form").addEventListener("submit", saveTrade);
$("#security-query").addEventListener("focus", showSecurityOptions);
$("#security-query").addEventListener("input", () => { state.form.selected = null; state.form.manual = false; $("#manual-fields").classList.add("hidden"); showSecurityOptions(); });
$("#trade-price").addEventListener("input", updateSalePreview);
$("#trade-quantity").addEventListener("input", updateSalePreview);
$("#range-select").addEventListener("change", (event) => { state.range = event.target.value; render(); });
$("#modal-backdrop").addEventListener("mousedown", (event) => { if (event.target === $("#modal-backdrop")) closeModal(); });
document.addEventListener("keydown", (event) => { if (event.key === "Escape" && !$("#modal-backdrop").classList.contains("hidden")) closeModal(); });
document.addEventListener("click", async (event) => {
  const target = event.target.closest("[data-action], .nav-item, #fill-all");
  if (!target) return;
  if (target.classList.contains("nav-item")) { switchView(target.dataset.view); return; }
  if (target.id === "fill-all") { $("#trade-quantity").value = state.form.sellContext.maxQuantity; updateSalePreview(); return; }
  const action = target.dataset.action;
  if (action === "view-records") switchView("records");
  if (action === "pnl-period") { state.pnlPeriod = target.dataset.period; renderRecords(calculateLedger(state.trades)); }
  if (action === "sell") openSell(target.dataset.code, target.dataset.style ?? "スイング", null, target.dataset.date ?? null);
  if (action === "choose-security") { const security = state.securities.find((item) => item.code === target.dataset.code); state.form.selected = security; state.form.manual = false; $("#security-query").value = `${security.code}　${security.name}`; $("#security-options").classList.add("hidden"); $("#manual-fields").classList.add("hidden"); }
  if (action === "manual-security") { state.form.manual = true; state.form.selected = null; $("#security-options").classList.add("hidden"); $("#manual-fields").classList.remove("hidden"); $("#manual-code").focus(); }
  if (action === "edit") { const trade = state.trades.find((item) => item.id === target.dataset.id); if (trade) trade.action === "買付" ? openBuy(trade) : openSell(trade.code, trade.style, trade); }
  if (action === "delete") await removeTrade(target.dataset.id);
  if (action === "csv") exportCsv();
  if (action === "logout") await signOut(auth);
});

try { await loadStocks(); }
catch (cause) { console.error(cause); $("#login-error").textContent = "銘柄一覧を読み込めませんでした。ページを再読み込みしてください。"; }

onAuthStateChanged(auth, (user) => {
  $("#boot").classList.add("hidden");
  if (!user) {
    state.user = null; state.trades = []; state.unsubscribe?.();
    $("#app").classList.add("hidden"); $("#login-screen").classList.remove("hidden");
    return;
  }
  state.user = user;
  $("#login-screen").classList.add("hidden"); $("#app").classList.remove("hidden");
  $("#range-select").value = state.range;
  switchView(state.activeView);
  subscribeTrades(user);
});
