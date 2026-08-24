import { initializeApp } from "https://www.gstatic.com/firebasejs/11.10.0/firebase-app.js";
import { getAuth, GoogleAuthProvider, signInWithPopup, signInWithRedirect, onAuthStateChanged, signOut } from "https://www.gstatic.com/firebasejs/11.10.0/firebase-auth.js";
import { getFirestore, collection, addDoc, deleteDoc, doc, onSnapshot, setDoc, serverTimestamp } from "https://www.gstatic.com/firebasejs/11.10.0/firebase-firestore.js";
import { CREDIT_SETTINGS, CREDIT_TYPES, calculateCreditInterest, rateForCreditType } from "./credit-calculation.mjs";
import { ALLOCATION_METHODS, ALLOCATION_SETTINGS, allocationArrayToObject, allocationObjectToArray, automaticPositionAllocations, creditLotEvaluation } from "./position-allocation.mjs";
import { calculateSpotLedger, transactionFeeOf } from "./spot-calculation.mjs";
import { TAX_SETTINGS, calculateAnnualTaxEstimates, estimatedAfterTaxForTrades } from "./tax-calculation.mjs";

const firebaseConfig = {
  apiKey: "AIzaSyBcF8KJ6ltfl5yyL-5445h3u93Ej4hWtrk",
  authDomain: "daytrade-performance-app.firebaseapp.com",
  projectId: "daytrade-performance-app",
  storageBucket: "daytrade-performance-app.firebasestorage.app",
  messagingSenderId: "753888387624",
  appId: "1:753888387624:web:e43b22d15d165dd4484b1d"
};

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
const normalize = (value) => String(value ?? "").normalize("NFKC").toLowerCase().replace(/[ァ-ヶ]/g, (char) => String.fromCharCode(char.charCodeAt(0) - 0x60)).replace(/[\s・（）()株式会社]/g, "");
const byTimeAsc = (a, b) => a.date.localeCompare(b.date) || (a.createdAt ?? 0) - (b.createdAt ?? 0) || a.id.localeCompare(b.id);
const accountTypeOf = (trade) => trade.accountType === "信用" ? "信用" : "現物";
const creditTypeOf = (trade) => CREDIT_TYPES.includes(trade.creditType) ? trade.creditType : "";
const CUSTODY_TYPES = ["特定", "一般"];
const custodyTypeOf = (trade) => CUSTODY_TYPES.includes(trade.custodyType) ? trade.custodyType : "未設定";
const creditGroupKey = (trade) => `${creditTypeOf(trade) || "信用種別未設定"}::${custodyTypeOf(trade)}`;
const creditGroupLabel = (trade) => `${creditTypeOf(trade) || "信用種別未設定"}・${custodyTypeOf(trade) === "未設定" ? "預り区分未設定" : `${custodyTypeOf(trade)}預り`}`;
const hasOwn = (object, key) => Object.prototype.hasOwnProperty.call(object ?? {}, key);
const creditTypeLabel = (trade) => {
  if (accountTypeOf(trade) !== "信用") return "現物";
  const types = trade.creditTypes ?? trade.applicableCreditTypes ?? (creditTypeOf(trade) ? [creditTypeOf(trade)] : []);
  return types.length ? types.join("・") : "信用種別未設定";
};
const accountDetailLabel = (trade) => accountTypeOf(trade) === "信用" ? `信用・${creditTypeLabel(trade)}` : "現物";
const positionKey = (code, accountType) => `${code}:${accountType}`;

const state = {
  user: null,
  trades: [],
  securities: [],
  stocksAsOf: "",
  activeView: "overview",
  summaryFilters: { period: "all", style: "all", accountType: "all" },
  recordQuery: "",
  pnlPeriod: "day",
  pnlSelections: { day: localDate(), week: currentWeekStart(), month: localDate().slice(0, 7) },
  unsubscribe: null,
  form: { mode: "new", action: "買付", editId: null, selected: null, manual: false, sellContext: null, interestDayOverrides: {}, positionAllocations: {}, allocationMethod: ALLOCATION_SETTINGS.defaultMethod, allocationGroup: "", allocationTouched: false, availableCreditLots: [], availableCreditGroups: [], evaluationPrice: "", tradingUnit: ALLOCATION_SETTINGS.defaultTradingUnit, evaluationProfitOverrides: {}, evaluationExpenseOverrides: {} }
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
  const creditLots = new Map();
  const results = new Map();
  const spotLedger = calculateSpotLedger(trades);
  let invalid = spotLedger.invalid;
  [...trades].sort(byTimeAsc).forEach((trade) => {
    const accountType = accountTypeOf(trade);
    const key = positionKey(trade.code, accountType);
    if (accountType === "信用") {
      const lots = creditLots.get(key) ?? [];
      if (trade.action === "買付") {
        lots.push({
          id: trade.id,
          code: trade.code,
          name: trade.name,
          market: trade.market ?? "",
          date: trade.date,
          createdAt: trade.createdAt ?? 0,
          style: trade.style,
          price: Number(trade.price),
          remainingQuantity: Number(trade.quantity),
          creditType: creditTypeOf(trade),
          custodyType: custodyTypeOf(trade),
          tradingUnit: Number(trade.tradingUnit) > 0 ? Number(trade.tradingUnit) : ALLOCATION_SETTINGS.defaultTradingUnit,
          annualInterestRate: typeof trade.annualInterestRate === "number" && Number.isFinite(trade.annualInterestRate) ? trade.annualInterestRate : creditTypeOf(trade) ? rateForCreditType(creditTypeOf(trade)) : 0
        });
        creditLots.set(key, lots);
        results.set(trade.id, { realisedProfit: null, grossProfitBeforeInterest: null, creditInterest: 0, averageCostAtSale: null, creditAllocations: [] });
        return;
      }

      const available = lots.reduce((sum, lot) => sum + lot.remainingQuantity, 0);
      if (trade.quantity > available) {
        invalid ??= `${trade.date}の${trade.name}（信用）は、保有株数を${trade.quantity - available}株超えて売却しています。`;
        results.set(trade.id, { realisedProfit: null, grossProfitBeforeInterest: null, creditInterest: 0, averageCostAtSale: null, creditAllocations: [] });
        return;
      }

      const savedAllocations = Array.isArray(trade.positionAllocations) ? trade.positionAllocations : [];
      const allocationConfirmed = savedAllocations.length > 0;
      let allocationPlan = [];
      if (allocationConfirmed) {
        const requested = new Map();
        for (const item of savedAllocations) {
          const quantity = Number(item.quantity);
          if (!item.openingTradeId || !Number.isInteger(quantity) || quantity < 1) {
            invalid ??= `${trade.date}の${trade.name}（信用）は、返済建玉の指定内容が不正です。`;
            results.set(trade.id, { realisedProfit: null, grossProfitBeforeInterest: null, creditInterest: 0, averageCostAtSale: null, creditAllocations: [], allocationConfirmed: true });
            return;
          }
          requested.set(item.openingTradeId, (requested.get(item.openingTradeId) ?? 0) + quantity);
        }
        const selectedQuantity = [...requested.values()].reduce((sum, quantity) => sum + quantity, 0);
        if (selectedQuantity !== Number(trade.quantity)) {
          invalid ??= `${trade.date}の${trade.name}（信用）は、返済建玉の指定株数合計が売却株数と一致していません。`;
          results.set(trade.id, { realisedProfit: null, grossProfitBeforeInterest: null, creditInterest: 0, averageCostAtSale: null, creditAllocations: [], allocationConfirmed: true });
          return;
        }
        const selectedGroups = new Set();
        for (const [openingTradeId, quantity] of requested) {
          const lot = lots.find((item) => item.id === openingTradeId);
          if (!lot || quantity > lot.remainingQuantity) {
            invalid ??= `${trade.date}の${trade.name}（信用）は、指定した建玉の残株数を超えて返済しています。`;
            results.set(trade.id, { realisedProfit: null, grossProfitBeforeInterest: null, creditInterest: 0, averageCostAtSale: null, creditAllocations: [], allocationConfirmed: true });
            return;
          }
          selectedGroups.add(creditGroupKey(lot));
          if (selectedGroups.size > 1) {
            invalid ??= `${trade.date}の${trade.name}（信用）は、信用種別または預り区分が異なる建玉を同時に返済しています。`;
            results.set(trade.id, { realisedProfit: null, grossProfitBeforeInterest: null, creditInterest: 0, averageCostAtSale: null, creditAllocations: [], allocationConfirmed: true });
            return;
          }
          allocationPlan.push({ lot, quantity });
        }
      } else {
        let remaining = Number(trade.quantity);
        for (const lot of lots) {
          if (remaining <= 0) break;
          const quantity = Math.min(remaining, lot.remainingQuantity);
          if (quantity <= 0) continue;
          allocationPlan.push({ lot, quantity });
          remaining -= quantity;
        }
      }

      let totalCost = 0;
      let grossProfitBeforeInterest = 0;
      let rawInterest = 0;
      const allocations = [];
      for (const { lot, quantity } of allocationPlan) {
        const overrideDays = trade.interestDayOverrides?.[lot.id] ?? null;
        const interest = calculateCreditInterest({
          openDate: lot.date,
          closeDate: trade.date,
          price: lot.price,
          quantity,
          creditType: lot.creditType,
          annualRate: lot.annualInterestRate,
          overrideDays
        });
        totalCost += lot.price * quantity;
        const lotGrossProfit = (Number(trade.price) - lot.price) * quantity;
        grossProfitBeforeInterest += lotGrossProfit;
        rawInterest += interest.rawAmount;
        allocations.push({
          openingTradeId: lot.id,
          openDate: lot.date,
          openSettlementDate: interest.openSettlementDate,
          closeSettlementDate: interest.closeSettlementDate,
          openingPrice: lot.price,
          quantity,
          style: lot.style,
          custodyType: lot.custodyType,
          tradingUnit: lot.tradingUnit,
          creditType: lot.creditType,
          annualInterestRate: interest.appliedAnnualRate,
          automaticInterestDays: interest.automaticDays,
          interestDays: interest.interestDays,
          manualOverride: interest.manualOverride,
          interestAmount: interest.amount,
          interestAmountRaw: interest.rawAmount,
          calendarConfirmed: interest.calendarConfirmed,
          grossProfitBeforeInterest: lotGrossProfit,
          realisedProfit: lotGrossProfit - interest.amount
        });
        lot.remainingQuantity -= quantity;
      }
      const creditInterest = Math.floor(rawInterest + Number.EPSILON);
      const allocationInterest = allocations.reduce((sum, item) => sum + item.interestAmount, 0);
      if (allocations.length && allocationInterest !== creditInterest) {
        const last = allocations.at(-1);
        last.interestAmount += creditInterest - allocationInterest;
        last.realisedProfit = last.grossProfitBeforeInterest - last.interestAmount;
      }
      const styleProfits = allocationConfirmed ? allocations.reduce((summary, item) => {
        summary[item.style] = (summary[item.style] ?? 0) + item.realisedProfit;
        return summary;
      }, {}) : null;
      results.set(trade.id, {
        realisedProfit: grossProfitBeforeInterest - creditInterest,
        grossProfitBeforeInterest,
        creditInterest,
        averageCostAtSale: trade.quantity ? totalCost / trade.quantity : 0,
        creditAllocations: allocations,
        creditTypes: [...new Set(allocations.map((item) => item.creditType).filter(Boolean))],
        custodyTypes: [...new Set(allocations.map((item) => item.custodyType).filter(Boolean))],
        styleProfits,
        allocationConfirmed,
        allocationMethod: allocationConfirmed ? trade.allocationMethod ?? "manual" : "legacy-fifo"
      });
      return;
    }
    results.set(trade.id, spotLedger.results.get(trade.id));
  });
  spotLedger.positions.forEach((position) => positions.set(positionKey(position.code, "現物"), position));
  creditLots.forEach((lots, key) => {
    const remainingLots = lots.filter((lot) => lot.remainingQuantity > 0);
    if (!remainingLots.length) return;
    const quantity = remainingLots.reduce((sum, lot) => sum + lot.remainingQuantity, 0);
    const totalCost = remainingLots.reduce((sum, lot) => sum + lot.remainingQuantity * lot.price, 0);
    const first = remainingLots[0];
    positions.set(key, {
      code: first.code,
      name: first.name,
      market: first.market,
      accountType: "信用",
      quantity,
      style: first.style,
      averagePrice: totalCost / quantity,
      creditTypes: [...new Set(remainingLots.map((lot) => lot.creditType).filter(Boolean))],
      custodyTypes: [...new Set(remainingLots.map((lot) => lot.custodyType).filter(Boolean))]
    });
  });
  const calculated = trades.map((trade) => ({ ...trade, accountType: accountTypeOf(trade), ...(results.get(trade.id) ?? { realisedProfit: null, grossProfitBeforeInterest: null, creditInterest: 0, averageCostAtSale: null, creditAllocations: [] }) }));
  const taxEstimates = calculateAnnualTaxEstimates(calculated);
  const calculatedWithTax = calculated.map((trade) => ({ ...trade, ...(taxEstimates.taxResults.get(trade.id) ?? {}) }));
  return {
    invalid,
    positions: [...positions.values()].filter((position) => position.quantity > 0),
    openCreditLots: [...creditLots.values()].flat().filter((lot) => lot.remainingQuantity > 0).map((lot) => ({ ...lot })),
    calculated: calculatedWithTax,
    annualTaxSummaries: taxEstimates.annualSummaries
  };
}

function summaryPeriodStart(period) {
  if (period === "all") return "0000-00-00";
  if (period === "day") return localDate();
  if (period === "week") return currentWeekStart();
  return `${localDate().slice(0, 7)}-01`;
}

function styleProfitOf(trade, style) {
  if (trade.styleProfits && hasOwn(trade.styleProfits, style)) return Number(trade.styleProfits[style]);
  return trade.style === style ? Number(trade.realisedProfit) : null;
}

function matchesSummaryFilters(trade, includePeriod = true, style = state.summaryFilters.style) {
  const { period, accountType } = state.summaryFilters;
  return (!includePeriod || trade.date >= summaryPeriodStart(period))
    && (style === "all" || (trade.action === "売却" && trade.styleProfits ? hasOwn(trade.styleProfits, style) : trade.style === style))
    && (accountType === "all" || accountTypeOf(trade) === accountType);
}

function completedForSummary(calculated, style = state.summaryFilters.style) {
  return calculated
    .filter((trade) => trade.action === "売却" && trade.realisedProfit !== null && matchesSummaryFilters(trade, true, style))
    .map((trade) => style === "all" ? trade : { ...trade, style, realisedProfit: styleProfitOf(trade, style) });
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
  return {
    profit: grossProfit - grossLoss,
    taxReference: estimatedAfterTaxForTrades(completed),
    winRate: completed.length ? wins.length / completed.length * 100 : 0,
    winCount: wins.length,
    saleCount: completed.length,
    averageProfit: wins.length ? grossProfit / wins.length : 0,
    averageLoss: losses.length ? -grossLoss / losses.length : 0,
    maxProfit: wins.length ? Math.max(...wins.map((trade) => trade.realisedProfit)) : 0,
    maxLoss: losses.length ? Math.min(...losses.map((trade) => trade.realisedProfit)) : 0,
    pf: grossLoss ? grossProfit / grossLoss : grossProfit ? Infinity : 0,
    maxDrawdown
  };
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
  const completed = completedForSummary(ledger.calculated);
  const stats = statsFor(completed);
  renderOverview(ledger, completed, stats);
  renderRecords(ledger);
  renderAnalytics(ledger);
  renderSettings(ledger);
}

function summaryFilterGroup(key, label, options) {
  return `<div class="summary-filter-row"><span>${label}</span><div class="summary-filter-options" role="group" aria-label="${label}">${options.map(([value, text]) => `<button class="${state.summaryFilters[key] === value ? "active" : ""}" data-action="summary-filter" data-filter="${key}" data-value="${value}" type="button" aria-pressed="${state.summaryFilters[key] === value}">${text}</button>`).join("")}</div></div>`;
}

function renderOverview(ledger, completed, stats) {
  const recent = [...ledger.calculated].filter((trade) => matchesSummaryFilters(trade)).sort((a, b) => -byTimeAsc(a, b)).slice(0, 4);
  const positions = new Map(ledger.positions.map((position) => [positionKey(position.code, position.accountType), position]));
  const styleSummary = state.summaryFilters.style === "all"
    ? [["全体", stats], ...["デイトレ", "スイング"].map((style) => [style, statsFor(completedForSummary(ledger.calculated, style))])]
    : [[state.summaryFilters.style, stats]];
  const profitSummary = styleSummary.map(([label, item]) => { const taxValue = Math.trunc(item.taxReference); return `<div class="summary-breakdown-row"><span>${label}：</span><span class="summary-breakdown-values"><strong class="${item.profit > 0 ? "positive" : item.profit < 0 ? "negative" : "muted"}">${item.profit === 0 ? "± 0円" : yen(item.profit)}</strong><small>(${taxValue === 0 ? "0円" : yen(taxValue)})</small></span></div>`; }).join("");
  const winSummary = styleSummary.map(([label, item]) => `<div class="summary-breakdown-row"><span>${label}：</span><span class="summary-breakdown-values"><strong class="${item.saleCount ? "positive" : "muted"}">${item.winRate.toFixed(1)}%</strong><small>(${item.winCount}/${item.saleCount})</small></span></div>`).join("");
  const metricYen = (value) => value === 0 ? "± 0円" : yen(value);
  const metricClass = (value) => value > 0 ? "positive" : value < 0 ? "negative" : "muted";
  const metricCard = (label, icon, value, note, className = "") => `<article class="stat-card compact-stat"><div class="stat-top"><span>${label}</span><i>${icon}</i></div><strong class="${className}">${value}</strong><small>${note}</small></article>`;
  const periodLabels = { day: "今日", week: "今週", month: "今月", all: "全期間" };
  const styleLabels = { all: "全て", デイトレ: "デイトレ", スイング: "スイング" };
  const accountLabels = { all: "全て", 現物: "現物", 信用: "信用" };
  const filterLabel = `${periodLabels[state.summaryFilters.period]} × ${styleLabels[state.summaryFilters.style]} × ${accountLabels[state.summaryFilters.accountType]}`;
  $("#overview-view").innerHTML = `
    <section class="summary-filters" aria-label="サマリの集計条件">
      <div class="summary-filter-heading"><div><p class="section-kicker">SUMMARY FILTERS</p><h2>集計条件</h2></div><small>${filterLabel}</small></div>
      ${summaryFilterGroup("period", "期間", [["all","全期間"],["day","今日"],["week","週"],["month","月"]])}
      ${summaryFilterGroup("style", "取引スタイル", [["all","全て"],["デイトレ","デイトレ"],["スイング","スイング"]])}
      ${summaryFilterGroup("accountType", "取引区分", [["all","全て"],["現物","現物"],["信用","信用"]])}
    </section>
    <div class="stats-grid summary-stats-grid">
      <article class="stat-card breakdown-card"><div class="stat-top"><span>実現損益</span><i>円</i></div><div class="summary-breakdown">${profitSummary}</div><small>（ ）内は選択条件の年間損益通算を反映した税引後損益（概算）</small></article>
      <article class="stat-card breakdown-card"><div class="stat-top"><span>勝率</span><i>◎</i></div><div class="summary-breakdown">${winSummary}</div></article>
      ${metricCard("PF", "⚖", Number.isFinite(stats.pf) ? stats.pf.toFixed(2) : "∞", "総利益 ÷ 総損失", stats.pf ? "positive" : "muted")}
      ${metricCard("平均利益", "＋", metricYen(stats.averageProfit), "利益になった取引の平均", metricClass(stats.averageProfit))}
      ${metricCard("平均損失", "−", metricYen(stats.averageLoss), "損失になった取引の平均", metricClass(stats.averageLoss))}
      ${metricCard("最大利益", "↑", metricYen(stats.maxProfit), "1取引あたりの最大利益", metricClass(stats.maxProfit))}
      ${metricCard("最大損失", "↓", metricYen(stats.maxLoss), "1取引あたりの最大損失", metricClass(stats.maxLoss))}
      ${metricCard("最大DD", "↘", metricYen(stats.maxDrawdown), "累積損益の最大下落額", metricClass(stats.maxDrawdown))}
    </div>
    <div class="dashboard-grid">
      <article class="panel"><div class="panel-heading"><div><p class="section-kicker">PERFORMANCE</p><h2>累積実現損益</h2></div><span class="period-badge">${filterLabel}</span></div><div class="chart-wrap">${chartSvg(completed)}</div></article>
      <article class="panel"><div class="panel-heading"><div><p class="section-kicker">OPEN POSITIONS</p><h2>保有中の銘柄</h2></div><span class="period-badge">全保有 ${ledger.positions.length}件</span></div><div class="position-list">${ledger.positions.map((position) => `
        <div class="position-row"><div><strong>${esc(position.code)} ${esc(position.name)}</strong><small>${esc(position.market)} ・ ${esc(position.style)} ・ ${esc(position.accountType === "信用" ? `信用・${position.creditTypes?.length ? position.creditTypes.join("・") : "信用種別未設定"}` : "現物")} ・ 平均取得 ${yen(position.averagePrice, false)}</small></div><div class="position-actions"><strong>${position.quantity.toLocaleString()}株</strong><button class="sale-register-button" data-action="sell" data-code="${esc(position.code)}" data-style="${esc(position.style)}" data-account-type="${esc(position.accountType)}" type="button">売却記録を登録</button></div></div>`).join("") || '<div class="empty-state">現在の保有銘柄はありません</div>'}</div></article>
    </div>
    <article class="panel recent-panel"><div class="panel-heading"><div><p class="section-kicker">RECENT ACTIVITY</p><h2>条件内の直近売買</h2></div><button class="text-button" data-action="view-records" type="button">すべて見る ›</button></div><div class="trade-list compact">${recent.map((trade) => tradeCard(trade, positions)).join("") || '<div class="empty-state">選択した条件に該当する売買はありません</div>'}</div></article>`;
}
function tradeCard(trade, positions) {
  const accountType = accountTypeOf(trade);
  const position = positions.get(positionKey(trade.code, accountType));
  const result = trade.realisedProfit === null ? (position ? "保有中" : "売却済み") : yen(trade.realisedProfit);
  const resultClass = trade.realisedProfit === null ? "muted" : trade.realisedProfit >= 0 ? "positive" : "negative";
  return `<div class="trade-row"><span class="side-badge ${trade.action === "買付" ? "buy" : "sell"}">${trade.action === "買付" ? "BUY" : "SELL"}</span><div class="trade-main"><strong>${esc(trade.code)} ${esc(trade.name)}</strong><small>${trade.date.replaceAll("-", "/")} ・ ${esc(trade.style)} ・ ${esc(accountDetailLabel(trade))} ・ ${yen(trade.price, false)} × ${trade.quantity.toLocaleString()}株</small></div><div class="trade-result"><strong class="${resultClass}">${result}</strong>${trade.action === "買付" && position ? `<button class="sale-register-button" data-action="sell" data-code="${esc(trade.code)}" data-style="${esc(trade.style)}" data-account-type="${esc(accountType)}" data-date="${esc(trade.date)}" type="button">売却記録を登録</button>` : ""}</div></div>`;
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
      const allocationStatus = trade.action === "売却" && accountTypeOf(trade) === "信用" && !trade.allocationConfirmed ? " ・ 返済建玉未確認" : "";
      return `<div class="record-entry"><button class="record-entry-main" data-action="edit" data-id="${esc(trade.id)}" type="button"><span class="style-badge">${esc(trade.style)}</span><span class="record-security"><strong>${esc(trade.code)}</strong><span>${esc(trade.name)} ・ ${esc(accountDetailLabel(trade))}${allocationStatus}</span></span><strong class="record-entry-result ${resultClass}">${result}</strong><span class="record-chevron">›</span></button><button class="record-delete" data-action="delete" data-id="${esc(trade.id)}" title="削除" type="button">削</button></div>`;
    }).join("")}</div></section>`).join("") || `<div class="empty-state">該当する売買はありません</div>`}</div></div>`;
  const search = $("#record-search");
  search?.addEventListener("input", (event) => { state.recordQuery = event.target.value; renderRecords(calculateLedger(state.trades)); requestAnimationFrame(() => { const next = $("#record-search"); next?.focus(); next?.setSelectionRange(state.recordQuery.length, state.recordQuery.length); }); });
  $("#pnl-period-picker")?.addEventListener("change", (event) => { state.pnlSelections[state.pnlPeriod] = event.target.value; renderRecords(calculateLedger(state.trades)); });
}

function renderAnalytics(ledger) {
  const completed = ledger.calculated.filter((trade) => trade.action === "売却" && trade.realisedProfit !== null);
  const stats = statsFor(completed);
  const score = completed.length ? Math.round(Math.max(0, Math.min(100, 45 + stats.winRate * .35 + Math.min(Number.isFinite(stats.pf) ? stats.pf : 4, 4) * 8))) : 0;
  const completedByStyle = (style) => completed.flatMap((trade) => {
    const profit = styleProfitOf(trade, style);
    return profit === null ? [] : [{ ...trade, style, realisedProfit: profit }];
  });
  const styleAmount = (style) => completedByStyle(style).reduce((sum, trade) => sum + trade.realisedProfit, 0);
  const styleAfterTax = (style) => estimatedAfterTaxForTrades(completedByStyle(style));
  $("#analytics-view").innerHTML = `<div class="analytics-layout"><article class="view-panel score-panel"><p class="section-kicker">TRADING SCORE</p><div class="score-ring"><span>${score}</span><small>/ 100</small></div><h2>${completed.length ? (score >= 70 ? "安定したパフォーマンス" : "改善余地があります") : "売却記録がありません"}</h2><p>売却済み取引だけを分析し、信用取引は金利控除後の実現損益を使用します。</p></article><article class="view-panel"><div class="panel-heading"><div><p class="section-kicker">TRADE STYLE</p><h2>運用スタイル別の実現損益</h2></div></div><div class="style-results">${["デイトレ","スイング"].map((style) => { const amount=styleAmount(style); return `<div><span>${style}</span><strong class="${amount>=0?"positive":"negative"}">${yen(amount)}</strong><small>税引後損益（概算） ${yen(styleAfterTax(style))}</small></div>`; }).join("")}</div></article><article class="view-panel"><div class="panel-heading"><div><p class="section-kicker">INSIGHTS</p><h2>振り返りポイント</h2></div></div><div class="insight-list"><div><span>01</span><p><strong>売買を実際の約定単位で記録</strong><small>買付と売却を分け、売却時に損益を確定します。</small></p></div><div><span>02</span><p><strong>現物と信用を分けて計算</strong><small>現物は税務上の取得単価と取引成績上の平均原価を分け、信用は返済する買付建玉を指定して金利を控除します。</small></p></div><div><span>03</span><p><strong>保有数超過を登録前に防止</strong><small>履歴の修正・削除時にも整合性を確認します。</small></p></div></div></article></div>`;
}

function renderSettings(ledger) {
  const incomeTaxRateLabel = (TAX_SETTINGS.incomeAndReconstructionRate * 100).toFixed(3);
  const residentTaxRateLabel = (TAX_SETTINGS.residentRate * 100).toFixed(0);
  const annualRows = ledger.annualTaxSummaries.map((summary) => '<div class="setting-row"><span><strong>' + esc(summary.year) + '年</strong><small>利益 ' + yen(summary.realisedGains, false) + '／損失 ' + yen(summary.realisedLosses) + '／通算 ' + yen(summary.netRealisedProfit) + '</small></span><span class="fixed-value">税額概算 ' + yen(summary.estimatedTax, false) + '<br>税引後 ' + yen(summary.estimatedAfterTaxProfit) + '</span></div>').join("");
  const annualTaxHtml = annualRows || '<div class="empty-state">売却済み取引がありません</div>';
  const spotRuleDifference = ledger.calculated.filter((trade) => trade.action === "売却" && accountTypeOf(trade) === "現物").reduce((sum, trade) => sum + Number(trade.realisedProfitDifference || 0), 0);
  const spotDifferenceText = spotRuleDifference === 0 ? "現在の記録では差額なし" : "現在の記録への影響 " + yen(spotRuleDifference);
  $("#settings-view").innerHTML = `<div class="settings-layout"><article class="view-panel settings-card"><p class="section-kicker">ACCOUNT</p><h2>ログイン中のアカウント</h2><div class="setting-row"><span class="account-chip">${state.user.photoURL ? `<img src="${esc(state.user.photoURL)}" alt="">` : ""}<span><strong>${esc(state.user.displayName || "Googleユーザー")}</strong><small>${esc(state.user.email || "")}</small></span></span><button class="secondary-button" data-action="logout" type="button">ログアウト</button></div></article><article class="view-panel settings-card"><p class="section-kicker">CALCULATION</p><h2>計算設定</h2><div class="setting-row"><span><strong>実現損益</strong><small>現物はSBI証券の税務上の取得価額に合わせ、同日中の全買付を先に合算し、買付手数料を含む1株単価を1円未満切り上げます。売却手数料は実現損益から控除します。信用は従来どおり返済建玉と金利を反映します。</small></span><span class="fixed-value">税引前を基本表示</span></div><div class="setting-row"><span><strong>信用買い金利</strong><small>制度信用 2.80%／一般信用（無期限）2.80%／日計りは当日0%、持越し1.80%。受渡日T+2の両端入れ、365日割、円未満切捨て。</small></span><span class="fixed-value">買付時の率を保存</span></div><div class="setting-row"><span><strong>税引後損益（概算）</strong><small>受渡日基準の暦年ごとに現物・信用の利益と損失を通算し、所得税等${incomeTaxRateLabel}％と住民税${residentTaxRateLabel}％を別々に円未満切捨て。損失後の利益では徴収、利益後の損失では還付として概算します。</small></span><span class="fixed-value">特定口座（源泉徴収あり）想定</span></div></article><article class="view-panel settings-card"><p class="section-kicker">ANNUAL TAX ESTIMATE</p><h2>年間損益・税額（概算）</h2>${annualTaxHtml}<div class="setting-row"><span><strong>旧計算との差</strong><small>取引成績用の平均原価と、SBI税務ルールの実現損益との差です。</small></span><span class="fixed-value">${spotDifferenceText}</span></div><p class="source-note">全記録を1つの特定口座（源泉徴収あり）として概算しています。NISA／一般口座／複数証券会社・配当・投資信託等は区別していないため、実際の税額はSBI証券の年間取引報告書で確認してください。</p></article><article class="view-panel settings-card"><p class="section-kicker">DATA</p><h2>データ管理</h2><div class="setting-row"><span><strong>Firebase同期</strong><small>Googleログインしたご本人の端末間で自動同期</small></span><span class="fixed-value">接続済み</span></div><div class="setting-row"><span><strong>CSVバックアップ</strong><small>${state.trades.length}件の売買記録を書き出します</small></span><button class="secondary-button" data-action="csv" type="button">書き出す</button></div><p class="source-note">銘柄検索：JPX「東証上場銘柄一覧」${esc(state.stocksAsOf)}時点。信用金利の営業日カレンダーは2026・2027年のJPX休場日を収録し、その他の年は手動日数修正に対応。</p></article></div>`;
}

function switchView(view) {
  state.activeView = view;
  $$(".nav-item").forEach((button) => button.classList.toggle("active", button.dataset.view === view));
  $$(".app-view").forEach((section) => section.classList.add("hidden"));
  $(`#${view}-view`).classList.remove("hidden");
  $("#page-title").textContent = headings[view][0];
  $("#page-subtitle").textContent = headings[view][1];

  $("#open-buy").classList.toggle("hidden", view === "settings");
}

function updateBuyCalculationNote() {
  if (state.form.action !== "買付") return;
  const isCredit = $("#account-type").value === "信用";
  const creditType = $("#credit-type").value;
  if (!isCredit || !creditType) {
    $("#calculation-note").innerHTML = "<strong>買付後の保有に追加します</strong><small>現物は同日買付を先に合算し、手数料を含めた取得単価を1円未満切り上げて更新します。</small>";
    return;
  }
  const rate = rateForCreditType(creditType) * 100;
  const rateNote = creditType === "日計り信用" ? `当日返済 0%／持越し 年率${rate.toFixed(2)}%` : `年率${rate.toFixed(2)}%`;
  $("#calculation-note").innerHTML = `<strong>${esc(creditType)} ・ ${rateNote}</strong><small>この適用金利を買付データに保存し、将来の設定変更による過去取引の書換えを防ぎます。</small>`;
}

function updateCreditTypeVisibility() {
  const showCreditType = state.form.action === "買付" && $("#account-type").value === "信用";
  $("#credit-type-field").classList.toggle("hidden", !showCreditType);
  $("#custody-type-field").classList.toggle("hidden", !showCreditType);
  $("#credit-type").required = showCreditType;
  $("#custody-type").required = showCreditType;
  if (showCreditType && state.form.mode === "new") {
    if (!$("#credit-type").value) $("#credit-type").value = "制度信用";
    if (!$("#custody-type").value) $("#custody-type").value = "特定";
  }
  updateBuyCalculationNote();
}

function updateTransactionFeeVisibility() {
  const isSpot = $("#account-type").value === "現物";
  $("#transaction-fee-field").classList.toggle("hidden", !isSpot);
  $("#transaction-fee-label").textContent = state.form.action === "買付" ? "買付手数料等" : "売却手数料等";
  $("#transaction-fee").disabled = !isSpot;
}

function setAccountType(value = "現物", locked = false) {
  const selected = value === "信用" ? "信用" : "現物";
  $("#account-type").value = selected;
  $$("#account-type-switch button").forEach((button) => {
    const active = button.dataset.value === selected;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
    button.disabled = locked;
  });
  updateCreditTypeVisibility();
  updateTransactionFeeVisibility();
}

function chooseAccountType(value) {
  const selected = value === "信用" ? "信用" : "現物";
  setAccountType(selected);
  if (state.form.action !== "売却" || state.form.mode !== "edit") return;
  const editTrade = state.trades.find((trade) => trade.id === state.form.editId);
  if (!editTrade) return;
  const ledger = calculateLedger(state.trades);
  const position = ledger.positions.find((item) => item.code === editTrade.code && item.accountType === selected);
  const originalAccountType = accountTypeOf(editTrade);
  const calculatedEdit = ledger.calculated.find((trade) => trade.id === editTrade.id);
  const sameAccountType = originalAccountType === selected;
  const maxQuantity = (position?.quantity ?? 0) + (sameAccountType ? editTrade.quantity : 0);
  const averagePrice = sameAccountType ? calculatedEdit?.averageCostAtSale ?? position?.averagePrice ?? 0 : position?.averagePrice ?? 0;
  state.form.sellContext = { maxQuantity, averagePrice };
  $("#trade-quantity").max = String(maxQuantity);
  $("#quantity-helper").innerHTML = `上限 ${maxQuantity.toLocaleString()}株 <button id="fill-all" type="button">全株を入力</button>`;
  updateSalePreview();
}

function resetForm() {
  state.form = { mode: "new", action: "買付", editId: null, selected: null, manual: false, sellContext: null, interestDayOverrides: {}, positionAllocations: {}, allocationMethod: ALLOCATION_SETTINGS.defaultMethod, allocationGroup: "", allocationTouched: false, availableCreditLots: [], availableCreditGroups: [], evaluationPrice: "", tradingUnit: ALLOCATION_SETTINGS.defaultTradingUnit, evaluationProfitOverrides: {}, evaluationExpenseOverrides: {} };
  $("#trade-form").reset();
  $("#trade-date").value = localDate();
  $("#transaction-fee").value = "0";
  $("#form-error").textContent = "";
  $("#security-options").classList.add("hidden");
  $("#manual-fields").classList.add("hidden");
  $("#security-field").classList.remove("hidden");
  $("#fixed-security").classList.add("hidden");
  $("#trade-quantity").removeAttribute("max");
  $("#trade-style").disabled = false;
  setAccountType("現物");
  $("#custody-type").value = "特定";
  $("#sell-from-edit").classList.add("hidden");
  $("#credit-interest-details").classList.add("hidden");
  $("#credit-interest-details").innerHTML = "";
  $("#broker-actuals").classList.add("hidden");
  $("#broker-actual-difference").innerHTML = "";
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
  $("#quantity-helper").innerHTML = "";
  if (editTrade) {
    const found = state.securities.find((security) => security.code === editTrade.code);
    state.form.selected = found ?? { code: editTrade.code, name: editTrade.name, market: editTrade.market ?? "手動登録" };
    $("#security-query").value = `${editTrade.code}　${editTrade.name}`;
    $("#trade-date").value = editTrade.date;
    $("#trade-style").value = editTrade.style;
    setAccountType(accountTypeOf(editTrade));
    $("#credit-type").value = creditTypeOf(editTrade);
    $("#custody-type").value = custodyTypeOf(editTrade);
    state.form.tradingUnit = Number(editTrade.tradingUnit) > 0 ? Number(editTrade.tradingUnit) : ALLOCATION_SETTINGS.defaultTradingUnit;
    $("#trade-price").value = editTrade.price;
    $("#trade-quantity").value = editTrade.quantity;
    $("#transaction-fee").value = transactionFeeOf(editTrade);
    $("#trade-note").value = editTrade.note ?? "";
    if (calculateLedger(state.trades).positions.some((position) => position.code === editTrade.code && position.accountType === accountTypeOf(editTrade))) $("#sell-from-edit").classList.remove("hidden");
  }
  updateCreditTypeVisibility();
  updateTransactionFeeVisibility();
  $("#modal-backdrop").classList.remove("hidden");
}

function availableCreditLotsForSale() {
  if (state.form.action !== "売却" || $("#account-type").value !== "信用") return [];
  const existing = state.trades.find((trade) => trade.id === state.form.editId);
  const draftOrder = { id: existing?.id ?? "pending-preview", date: $("#trade-date").value, createdAt: existing?.createdAt ?? Date.now() };
  const priorTrades = state.trades.filter((trade) => trade.id !== state.form.editId && byTimeAsc(trade, draftOrder) < 0);
  return calculateLedger(priorTrades).openCreditLots.filter((lot) => lot.code === state.form.selected.code);
}

function allocationEvaluationContext(fallbackPrice = 0) {
  return {
    evaluationPrice: Number(state.form.evaluationPrice) > 0 ? Number(state.form.evaluationPrice) : 0,
    fallbackPrice: Number(fallbackPrice) > 0 ? Number(fallbackPrice) : 0,
    tradingUnit: Number(state.form.tradingUnit) > 0 ? Number(state.form.tradingUnit) : ALLOCATION_SETTINGS.defaultTradingUnit,
    evaluationProfitOverrides: state.form.evaluationProfitOverrides,
    evaluationExpenseOverrides: state.form.evaluationExpenseOverrides
  };
}

function readBrokerActuals() {
  const readOptionalNumber = (selector) => $(selector).value === "" ? null : Number($(selector).value);
  const actuals = { fees: readOptionalNumber("#broker-fees"), tax: readOptionalNumber("#broker-tax"), settlement: readOptionalNumber("#broker-settlement") };
  return Object.values(actuals).every((value) => value === null) ? null : actuals;
}

function refreshPositionAllocations(price, quantity) {
  if ($("#account-type").value !== "信用") {
    state.form.availableCreditLots = [];
    state.form.availableCreditGroups = [];
    state.form.positionAllocations = {};
    return;
  }
  const allLots = availableCreditLotsForSale();
  state.form.availableCreditGroups = [...new Map(allLots.map((lot) => [creditGroupKey(lot), { key: creditGroupKey(lot), label: creditGroupLabel(lot) }])).values()];
  if (!state.form.availableCreditGroups.some((group) => group.key === state.form.allocationGroup)) {
    const savedIds = new Set(Object.keys(state.form.positionAllocations));
    const savedLot = allLots.find((lot) => savedIds.has(lot.id));
    state.form.allocationGroup = savedLot ? creditGroupKey(savedLot) : state.form.availableCreditGroups[0]?.key ?? "";
    state.form.allocationTouched = false;
  }
  const lots = allLots.filter((lot) => creditGroupKey(lot) === state.form.allocationGroup);
  state.form.availableCreditLots = lots;
  const availableIds = new Set(lots.map((lot) => lot.id));
  state.form.positionAllocations = Object.fromEntries(Object.entries(state.form.positionAllocations).filter(([id]) => availableIds.has(id)));
  if (!state.form.allocationTouched && Number.isInteger(quantity) && quantity > 0) {
    state.form.positionAllocations = allocationArrayToObject(automaticPositionAllocations(lots, quantity, state.form.allocationMethod, allocationEvaluationContext(price)));
  }
  const maxQuantity = lots.reduce((sum, lot) => sum + lot.remainingQuantity, 0);
  state.form.sellContext.maxQuantity = maxQuantity;
  $("#trade-quantity").max = String(maxQuantity);
  $("#quantity-helper").innerHTML = `上限 ${maxQuantity.toLocaleString()}株 <button id="fill-all" type="button">全株を入力</button>`;
}

function openSell(code, style = "スイング", accountType = "現物", editTrade = null, defaultDate = null) {
  resetForm();
  const ledger = calculateLedger(state.trades);
  const position = ledger.positions.find((item) => item.code === code && item.accountType === accountType);
  const calculatedEdit = editTrade ? ledger.calculated.find((item) => item.id === editTrade.id) : null;
  const sameAccountType = !editTrade || accountTypeOf(editTrade) === accountType;
  const maxQuantity = (position?.quantity ?? 0) + (editTrade && sameAccountType ? editTrade.quantity : 0);
  const averagePrice = sameAccountType ? calculatedEdit?.averageCostAtSale ?? position?.averagePrice ?? 0 : position?.averagePrice ?? 0;
  const savedAllocations = Array.isArray(editTrade?.positionAllocations) ? editTrade.positionAllocations : [];
  const savedEvaluation = editTrade?.allocationEvaluation ?? {};
  state.form = {
    mode: editTrade ? "edit" : "new", action: "売却", editId: editTrade?.id ?? null,
    selected: { code, name: editTrade?.name ?? position?.name ?? "", market: editTrade?.market ?? position?.market ?? "" },
    manual: false, sellContext: { maxQuantity, averagePrice }, interestDayOverrides: { ...(editTrade?.interestDayOverrides ?? {}) },
    positionAllocations: allocationArrayToObject(savedAllocations), allocationMethod: editTrade?.allocationMethod ?? ALLOCATION_SETTINGS.defaultMethod,
    allocationGroup: editTrade?.repaymentGroup ?? "", allocationTouched: savedAllocations.length > 0, availableCreditLots: [], availableCreditGroups: [],
    evaluationPrice: savedEvaluation.evaluationPrice ?? "",
    tradingUnit: savedEvaluation.tradingUnit ?? ALLOCATION_SETTINGS.defaultTradingUnit,
    evaluationProfitOverrides: { ...(savedEvaluation.profitOverrides ?? {}) },
    evaluationExpenseOverrides: { ...(savedEvaluation.expenseOverrides ?? {}) }
  };
  $("#modal-kicker").textContent = editTrade ? "EDIT CLOSE" : "CLOSE POSITION";
  $("#modal-title").textContent = editTrade ? "売却記録を修正" : "売却記録を登録";
  $("#price-label").textContent = "売却価格";
  $("#save-trade").textContent = editTrade ? "修正を保存" : "売却を記録";
  $("#security-field").classList.add("hidden");
  $("#fixed-security").classList.remove("hidden");
  $("#fixed-security").innerHTML = `<small>売却対象銘柄</small><strong>${esc(code)}　${esc(state.form.selected.name)}</strong><span>銘柄・運用スタイル・取引区分は、買付時の内容から変更できません</span>`;
  $("#trade-quantity").max = String(maxQuantity);
  setAccountType(accountType, true);
  $("#quantity-helper").innerHTML = `上限 ${maxQuantity.toLocaleString()}株 <button id="fill-all" type="button">全株を入力</button>`;
  $("#calculation-note").className = "calculation-note sale full";
  if (editTrade) {
    $("#trade-date").value = editTrade.date;
    $("#trade-style").value = editTrade.style;
    $("#trade-price").value = editTrade.price;
    $("#trade-quantity").value = editTrade.quantity;
    $("#transaction-fee").value = transactionFeeOf(editTrade);
    $("#trade-note").value = editTrade.note ?? "";
    $("#broker-fees").value = editTrade.brokerActuals?.fees ?? "";
    $("#broker-tax").value = editTrade.brokerActuals?.tax ?? "";
    $("#broker-settlement").value = editTrade.brokerActuals?.settlement ?? "";
  } else {
    $("#trade-style").value = style;
    if (defaultDate) $("#trade-date").value = defaultDate;
  }
  $("#trade-style").disabled = true;
  $("#broker-actuals").classList.toggle("hidden", accountType !== "信用");
  updateSalePreview();
  $("#modal-backdrop").classList.remove("hidden");
}

function allocationEvaluationSnapshot() {
  const context = allocationEvaluationContext();
  const evaluatedIds = new Set(Object.keys(context.evaluationProfitOverrides));
  const allLotsHaveDirectProfit = state.form.availableCreditLots.length > 0 && state.form.availableCreditLots.every((lot) => evaluatedIds.has(lot.id));
  return {
    evaluationPrice: context.evaluationPrice || null,
    tradingUnit: context.tradingUnit,
    profitOverrides: { ...context.evaluationProfitOverrides },
    expenseOverrides: { ...context.evaluationExpenseOverrides },
    source: evaluatedIds.size ? "sbi-position-profit" : context.evaluationPrice ? "sbi-evaluation-price" : "repayment-price-estimate",
    estimated: !allLotsHaveDirectProfit,
    note: allLotsHaveDirectProfit ? "SBI証券の建玉別評価損益を優先" : "未入力建玉は注文時評価損益の概算"
  };
}

function salePreviewTrade(price, quantity) {
  const existing = state.trades.find((trade) => trade.id === state.form.editId);
  return {
    id: existing?.id ?? "pending-preview", code: state.form.selected.code, name: state.form.selected.name, market: state.form.selected.market ?? "", action: "売却",
    style: $("#trade-style").value, accountType: $("#account-type").value, date: $("#trade-date").value, price, quantity,
    interestDayOverrides: { ...state.form.interestDayOverrides }, positionAllocations: allocationObjectToArray(state.form.positionAllocations),
    allocationMethod: state.form.allocationMethod, allocationConfirmed: true, brokerActuals: readBrokerActuals(), transactionFee: Number($("#transaction-fee").value || 0),
    repaymentGroup: state.form.allocationGroup, allocationEvaluation: allocationEvaluationSnapshot(),
    createdAt: existing?.createdAt ?? Date.now()
  };
}


function updateSalePreview() {
  if (state.form.action !== "売却" || !state.form.sellContext) return;
  const price = Number($("#trade-price").value);
  const quantity = Number($("#trade-quantity").value);
  refreshPositionAllocations(price, quantity);
  const { maxQuantity } = state.form.sellContext;
  let calculated = null;
  if (price > 0 && Number.isInteger(quantity) && quantity > 0 && quantity <= maxQuantity && $("#trade-date").value) {
    const draft = salePreviewTrade(price, quantity);
    const candidate = state.form.mode === "edit" ? state.trades.map((trade) => trade.id === state.form.editId ? draft : trade) : [...state.trades, draft];
    const preview = calculateLedger(candidate);
    if (!preview.invalid) calculated = preview.calculated.find((trade) => trade.id === draft.id);
  }
  const averagePrice = calculated?.averageCostAtSale ?? state.form.sellContext.averagePrice;
  const profit = calculated?.realisedProfit ?? null;
  const gross = calculated?.grossProfitBeforeInterest ?? null;
  const interest = calculated?.creditInterest ?? 0;
  const afterTaxProfit = calculated?.estimatedAfterTaxProfit ?? null;
  const isSpotSale = $("#account-type").value === "現物";
  const fee = calculated?.transactionFee ?? Number($("#transaction-fee").value || 0);
  const performanceProfit = calculated?.tradePerformanceProfit ?? null;
  $("#calculation-note").innerHTML = `<span><small>売却可能株数</small><strong>${maxQuantity.toLocaleString()}株</strong></span><span><small>取得価格</small><strong>${yen(averagePrice,false)}</strong>${gross === null ? "" : `<small>${isSpotSale ? "手数料控除前" : "金利控除前"} ${yen(gross)}</small>`}</span><span><small>${isSpotSale ? "売却手数料等" : "信用金利"}</small><strong>${yen(isSpotSale ? fee : interest, false)}</strong></span><span><small>${isSpotSale ? "税務上の実現損益" : "実現損益見込み"}</small><strong class="${profit === null ? "muted" : profit >= 0 ? "positive" : "negative"}">${profit === null ? "価格・株数を入力" : yen(profit)}</strong>${profit === null ? "" : `<small>税引後損益（概算） ${yen(afterTaxProfit)}</small>${isSpotSale && performanceProfit !== null ? `<small>取引成績上 ${yen(performanceProfit)}</small>` : ""}`}</span>`;
  renderCreditLotSelector(calculated, quantity, price);
  renderBrokerActualDifference(calculated);
}
function renderCreditLotSelector(calculated, targetQuantity, salePrice) {
  const details = $("#credit-interest-details");
  if ($("#account-type").value !== "信用") {
    details.classList.add("hidden");
    details.innerHTML = "";
    return;
  }
  const selectedQuantity = Object.values(state.form.positionAllocations).reduce((sum, quantity) => sum + Number(quantity || 0), 0);
  const quantitiesMatch = Number.isInteger(targetQuantity) && targetQuantity > 0 && selectedQuantity === targetQuantity;
  const editingLegacy = state.form.mode === "edit" && !(state.trades.find((trade) => trade.id === state.form.editId)?.positionAllocations?.length);
  const methodButtons = Object.entries(ALLOCATION_METHODS).map(([key, label]) => `<button class="${state.form.allocationMethod === key ? "active" : ""}" data-action="allocation-method" data-method="${key}" type="button">${esc(label)}</button>`).join("");
  const groupOptions = state.form.availableCreditGroups.map((group) => `<option value="${esc(group.key)}" ${group.key === state.form.allocationGroup ? "selected" : ""}>${esc(group.label)}</option>`).join("");
  const evaluationContext = allocationEvaluationContext(salePrice);
  let estimatedCalendar = false;
  let legacyCreditType = false;
  let estimatedSelection = false;
  const cards = state.form.availableCreditLots.map((lot) => {
    const selected = Number(state.form.positionAllocations[lot.id] ?? 0);
    const override = state.form.interestDayOverrides[lot.id] ?? "";
    const evaluationProfitOverride = state.form.evaluationProfitOverrides[lot.id] ?? "";
    const evaluationExpenseOverride = state.form.evaluationExpenseOverrides[lot.id] ?? "";
    const evaluation = creditLotEvaluation(lot, evaluationContext);
    const interest = calculateCreditInterest({ openDate: lot.date, closeDate: $("#trade-date").value, price: lot.price, quantity: selected, creditType: lot.creditType, annualRate: lot.annualInterestRate, overrideDays: override || null });
    const gross = Number(salePrice) > 0 ? (Number(salePrice) - lot.price) * selected : null;
    const net = gross === null ? null : gross - interest.amount;
    estimatedCalendar ||= !interest.calendarConfirmed;
    legacyCreditType ||= !lot.creditType;
    estimatedSelection ||= evaluation.estimated;
    const type = lot.creditType || "種別未設定（金利0%）";
    const sourceLabel = evaluation.source === "sbi-profit" ? "SBI入力" : "概算";
    return `<article class="credit-lot-card ${selected ? "selected" : ""}"><button class="credit-lot-toggle" data-action="toggle-credit-lot" data-lot-id="${esc(lot.id)}" type="button" aria-pressed="${Boolean(selected)}" aria-label="この建玉を${selected ? "選択解除" : "選択"}">${selected ? "✓" : "＋"}</button><div class="credit-lot-body"><div class="credit-lot-title"><strong>${esc(lot.date)}の建玉</strong><span>残り ${lot.remainingQuantity.toLocaleString()}株</span></div><div class="credit-lot-meta"><span>${esc(type)}・${esc(custodyTypeOf(lot))} ・ 建単価 ${yen(lot.price, false)} ・ 年率 ${(lot.annualInterestRate * 100).toFixed(2)}%</span><span>返済順の1単元評価損益 <strong class="${evaluation.perTradingUnitProfit >= 0 ? "positive" : "negative"}">${yen(evaluation.perTradingUnitProfit)}</strong>（${sourceLabel}）</span></div><details class="lot-evaluation-inputs"><summary>SBI評価損益・評価諸経費を入力（任意）</summary><div><label>建玉全体の評価損益<input data-evaluation-profit-lot-id="${esc(lot.id)}" inputmode="numeric" type="number" step="1" value="${esc(evaluationProfitOverride)}" placeholder="SBI表示値"></label><label>評価時諸経費<input data-evaluation-expense-lot-id="${esc(lot.id)}" inputmode="numeric" type="number" min="0" step="1" value="${esc(evaluationExpenseOverride)}" placeholder="未入力は0"></label></div><small>建玉別評価損益の入力を最優先します。評価時諸経費は返済順の概算だけに使い、最終損益へ重ねて控除しません。</small></details><div class="credit-lot-estimate"><span>金利控除前 <strong class="${gross === null ? "muted" : gross >= 0 ? "positive" : "negative"}">${gross === null ? "売却価格入力後" : yen(gross)}</strong></span><span>最終信用金利 <strong>${yen(interest.amount, false)}</strong></span><span>実現損益 <strong class="${net === null ? "muted" : net >= 0 ? "positive" : "negative"}">${net === null ? "売却価格入力後" : yen(net)}</strong></span></div><div class="credit-lot-inputs"><label><span>返済株数 <button data-action="fill-credit-lot" data-lot-id="${esc(lot.id)}" type="button">全株</button></span><input data-position-lot-id="${esc(lot.id)}" type="number" min="0" max="${lot.remainingQuantity}" step="1" value="${selected || ""}" placeholder="0"></label><label>最終金利日数<input data-interest-lot-id="${esc(lot.id)}" type="number" min="1" step="1" value="${esc(override)}" placeholder="自動 ${interest.automaticDays}日"><small>${override ? "手動設定" : `自動 ${interest.automaticDays}日`} ・ 約 ${yen(interest.amount, false)}</small></label></div></div></article>`;
  }).join("");
  details.classList.remove("hidden");
  details.innerHTML = `<div class="credit-interest-heading"><strong>返済する建玉を選択</strong><small>SBI証券と同じく、同一銘柄・信用種別（期日）・預り区分の建玉内で返済順を決めます。</small></div><div class="allocation-group-row"><label>一括返済グループ<select id="allocation-group">${groupOptions}</select></label><span>デイトレ／スイングが混在しても、損益は元の建玉へ配分します。</span></div><details class="allocation-evaluation-settings" ${state.form.evaluationPrice || Object.keys(state.form.evaluationProfitOverrides).length ? "open" : ""}><summary>注文時のSBI評価条件（任意）</summary><div><label>注文時の評価価格<input id="allocation-evaluation-price" inputmode="decimal" type="number" min="0.01" step="any" value="${esc(state.form.evaluationPrice)}" placeholder="SBI画面の現在値等"></label><label>1単元の株数<input id="allocation-trading-unit" inputmode="numeric" type="number" min="1" step="1" value="${esc(state.form.tradingUnit)}"></label></div><small>銘柄一覧に単元株数がないため初期値は${ALLOCATION_SETTINGS.defaultTradingUnit}株です。銘柄に合わせて変更できます。最も正確なのは各建玉のSBI評価損益入力です。</small></details><div class="allocation-toolbar"><div class="allocation-status"><strong>選択 ${selectedQuantity.toLocaleString()}株 / 売却 ${Number.isInteger(targetQuantity) && targetQuantity > 0 ? targetQuantity.toLocaleString() : "未入力"}株</strong><span class="${quantitiesMatch ? "matched" : "mismatched"}">${quantitiesMatch ? "一致" : "要確認"}</span></div><div class="allocation-methods">${methodButtons}</div></div>${editingLegacy ? '<p class="allocation-unconfirmed">この売却は従来方式で計算された「返済建玉未確認」の記録です。自動で割り当て直していません。保存すると、現在の選択内容を確定します。</p>' : ""}<div class="credit-lot-cards">${cards || '<div class="empty-state">この返済グループには、取引日より前に返済できる信用建玉がありません</div>'}</div>${estimatedSelection ? '<p class="credit-warning">SBI証券の建玉別評価損益が未入力の建玉は概算です。評価時点までの諸経費などにより、SBI画面の返済順と異なる場合があります。</p>' : ""}${legacyCreditType ? '<p class="credit-warning">既存の信用買いに信用種別がない建玉は、互換性のため金利0円・預り区分未設定で維持します。</p>' : ""}${estimatedCalendar ? '<p class="credit-warning">2026・2027年以外の休場日は推定です。SBI証券の取引明細と照合し、必要に応じて最終金利日数を修正してください。</p>' : ""}`;
}

function renderBrokerActualDifference(calculated) {
  const box = $("#broker-actual-difference");
  const actuals = readBrokerActuals();
  if (!actuals || actuals.settlement === null || calculated?.realisedProfit === null || calculated?.realisedProfit === undefined) {
    box.innerHTML = "実際の受渡金額・決済損益を入力すると、アプリ計算との差額を表示します。";
    return;
  }
  const reference = Math.round(calculated.estimatedAfterTaxProfit ?? calculated.realisedProfit);
  box.innerHTML = `アプリの税引後損益（概算） ${yen(reference)} ／ 実績との差 ${yen(actuals.settlement - reference)}`;
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
  const accountType = $("#account-type").value;
  const transactionFee = accountType === "現物" ? Number($("#transaction-fee").value || 0) : 0;
  if (!Number.isInteger(transactionFee) || transactionFee < 0) { error.textContent = "手数料等は0円以上の整数で入力してください。"; return; }
  const isCreditBuy = accountType === "信用" && state.form.action === "買付";
  const isCreditSale = accountType === "信用" && state.form.action === "売却";
  const creditType = isCreditBuy ? $("#credit-type").value : null;
  const custodyType = isCreditBuy ? $("#custody-type").value : null;
  if (isCreditBuy && !CREDIT_TYPES.includes(creditType)) { error.textContent = "信用種別を選択してください。"; return; }
  if (isCreditBuy && !CUSTODY_TYPES.includes(custodyType)) { error.textContent = "預り区分（特定／一般）を選択してください。"; return; }
  const positionAllocations = isCreditSale ? allocationObjectToArray(state.form.positionAllocations) : [];
  const allocatedQuantity = positionAllocations.reduce((sum, item) => sum + item.quantity, 0);
  if (isCreditSale && allocatedQuantity !== quantity) {
    error.textContent = `返済する建玉の株数合計を、売却株数の${quantity.toLocaleString()}株に合わせてください。`; return;
  }
  const trade = {
    code: security.code, name: security.name, market: security.market ?? "", action: state.form.action,
    style: $("#trade-style").value, accountType, date: $("#trade-date").value, price, quantity, transactionFee,
    creditType, custodyType, tradingUnit: isCreditBuy ? Number(state.form.tradingUnit) || ALLOCATION_SETTINGS.defaultTradingUnit : null,
    annualInterestRate: isCreditBuy ? rateForCreditType(creditType) : null,
    interestDayOverrides: isCreditSale ? { ...state.form.interestDayOverrides } : {},
    interestCalculationMethod: isCreditSale ? CREDIT_SETTINGS.calculationMethod : null,
    positionAllocations, allocationMethod: isCreditSale ? state.form.allocationMethod : null,
    repaymentGroup: isCreditSale ? state.form.allocationGroup : null,
    allocationEvaluation: isCreditSale ? allocationEvaluationSnapshot() : null,
    allocationConfirmed: isCreditSale,
    brokerActuals: isCreditSale ? readBrokerActuals() : null,
    note: $("#trade-note").value.trim(), createdAt: existing?.createdAt ?? Date.now(), updatedAt: Date.now()
  };
  const candidateId = state.form.mode === "edit" ? state.form.editId : `pending-${Date.now()}`;
  const candidate = state.form.mode === "edit" ? state.trades.map((item) => item.id === state.form.editId ? { ...trade, id: item.id } : item) : [...state.trades, { ...trade, id: candidateId }];
  const validation = calculateLedger(candidate);
  if (validation.invalid) { error.textContent = validation.invalid; return; }
  const calculated = validation.calculated.find((item) => item.id === candidateId);
  if (isCreditSale) trade.interestDayOverrides = Object.fromEntries((calculated?.creditAllocations ?? []).filter((item) => item.manualOverride).map((item) => [item.openingTradeId, item.interestDays]));
  button.disabled = true;
  try {
    const tradesRef = collection(db, "users", state.user.uid, "trades");
    const payload = {
      ...trade,
      creditInterestAmount: calculated?.creditInterest ?? 0,
      grossProfitBeforeInterest: calculated?.grossProfitBeforeInterest ?? null,
      realisedProfitAfterInterest: calculated?.realisedProfit ?? null,
      taxRealisedProfit: calculated?.taxRealisedProfit ?? null,
      tradePerformanceProfit: calculated?.tradePerformanceProfit ?? null,
      taxAcquisitionUnitPrice: calculated?.taxAcquisitionUnitPrice ?? null,
      taxYear: calculated?.taxYear ?? null,
      taxSettlementDate: calculated?.taxSettlementDate ?? null,
      estimatedTaxChange: calculated?.estimatedTaxChange ?? null,
      estimatedAfterTaxProfit: calculated?.estimatedAfterTaxProfit ?? null,
      creditInterestAllocations: calculated?.creditAllocations ?? [],
      positionAllocations: trade.positionAllocations,
      allocationMethod: trade.allocationMethod,
      repaymentGroup: trade.repaymentGroup,
      allocationEvaluation: trade.allocationEvaluation,
      styleProfits: calculated?.styleProfits ?? null,
      allocationConfirmed: trade.allocationConfirmed,
      applicableCreditTypes: calculated?.creditTypes ?? (creditType ? [creditType] : []),
      serverUpdatedAt: serverTimestamp()
    };
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
  const headers = ["取引日","受渡日","税計算年","銘柄コード","銘柄名","市場","運用スタイル","取引区分","信用種別","売買","約定価格","株数","取引手数料等","控除前損益","信用金利","税務上の取得単価","税務上の実現損益","取引成績上の損益","税務計算との差","源泉徴収・還付額（概算）","税引後損益（概算）","返済建玉状態","建玉選択方式","返済建玉明細","手数料・諸経費（実績）","課税額（実績）","受渡金額・決済損益（実績）","メモ"];
  const rows = [headers, ...[...ledger.calculated].sort(byTimeAsc).map((trade) => [
    trade.date, trade.taxSettlementDate ?? "", trade.taxYear ?? "", trade.code, trade.name, trade.market, trade.style,
    accountTypeOf(trade), creditTypeLabel(trade), trade.action, trade.price, trade.quantity, transactionFeeOf(trade),
    trade.grossProfitBeforeInterest ?? trade.grossProfitBeforeFees ?? "", trade.creditInterest ?? 0,
    trade.taxAcquisitionUnitPrice ?? "", trade.taxRealisedProfit ?? trade.realisedProfit ?? "",
    trade.tradePerformanceProfit ?? "", trade.realisedProfitDifference ?? "", trade.estimatedTaxChange ?? "",
    trade.estimatedAfterTaxProfit ?? "",
    trade.action === "売却" && accountTypeOf(trade) === "信用" ? (trade.allocationConfirmed ? "確認済み" : "返済建玉未確認") : "",
    trade.allocationMethod ?? "", JSON.stringify(trade.creditAllocations ?? []), trade.brokerActuals?.fees ?? "",
    trade.brokerActuals?.tax ?? "", trade.brokerActuals?.settlement ?? "", trade.note ?? ""
  ])];
  const blob = new Blob(["\uFEFF" + rows.map((row) => row.map(quote).join(",")).join("\r\n")], { type: "text/csv;charset=utf-8" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = "売買記録_" + localDate() + ".csv";
  link.click();
  URL.revokeObjectURL(link.href);
  showToast("CSVを書き出しました");
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
$("#sell-from-edit").addEventListener("click", () => { const trade = state.trades.find((item) => item.id === state.form.editId); if (!trade) return; closeModal(); openSell(trade.code, trade.style, accountTypeOf(trade), null, trade.date); });
$("#trade-form").addEventListener("submit", saveTrade);
$("#security-query").addEventListener("focus", showSecurityOptions);
$("#security-query").addEventListener("input", () => { state.form.selected = null; state.form.manual = false; $("#manual-fields").classList.add("hidden"); showSecurityOptions(); });
$("#trade-price").addEventListener("input", updateSalePreview);
$("#transaction-fee").addEventListener("input", updateSalePreview);
$("#credit-type").addEventListener("change", updateBuyCalculationNote);
$("#trade-date").addEventListener("change", updateSalePreview);
$("#credit-interest-details").addEventListener("change", (event) => {
  const allocationInput = event.target.closest("[data-position-lot-id]");
  if (allocationInput) {
    const value = Number(allocationInput.value);
    if (allocationInput.value === "" || !Number.isInteger(value) || value < 1) delete state.form.positionAllocations[allocationInput.dataset.positionLotId];
    else state.form.positionAllocations[allocationInput.dataset.positionLotId] = value;
    state.form.allocationTouched = true;
    state.form.allocationMethod = "manual";
    updateSalePreview();
    return;
  }
  if (event.target.id === "allocation-group") {
    state.form.allocationGroup = event.target.value;
    state.form.positionAllocations = {};
    state.form.allocationTouched = false;
    updateSalePreview();
    return;
  }
  if (event.target.id === "allocation-evaluation-price") {
    state.form.evaluationPrice = event.target.value;
    state.form.allocationTouched = state.form.allocationMethod === "manual";
    updateSalePreview();
    return;
  }
  if (event.target.id === "allocation-trading-unit") {
    const value = Number(event.target.value);
    state.form.tradingUnit = Number.isInteger(value) && value > 0 ? value : ALLOCATION_SETTINGS.defaultTradingUnit;
    state.form.allocationTouched = state.form.allocationMethod === "manual";
    updateSalePreview();
    return;
  }
  const evaluationProfitInput = event.target.closest("[data-evaluation-profit-lot-id]");
  if (evaluationProfitInput) {
    const id = evaluationProfitInput.dataset.evaluationProfitLotId;
    if (evaluationProfitInput.value === "") delete state.form.evaluationProfitOverrides[id];
    else state.form.evaluationProfitOverrides[id] = Number(evaluationProfitInput.value);
    state.form.allocationTouched = state.form.allocationMethod === "manual";
    updateSalePreview();
    return;
  }
  const evaluationExpenseInput = event.target.closest("[data-evaluation-expense-lot-id]");
  if (evaluationExpenseInput) {
    const id = evaluationExpenseInput.dataset.evaluationExpenseLotId;
    if (evaluationExpenseInput.value === "") delete state.form.evaluationExpenseOverrides[id];
    else state.form.evaluationExpenseOverrides[id] = Number(evaluationExpenseInput.value);
    state.form.allocationTouched = state.form.allocationMethod === "manual";
    updateSalePreview();
    return;
  }
  const input = event.target.closest("[data-interest-lot-id]");
  if (!input) return;
  const value = Number(input.value);
  if (input.value === "" || !Number.isInteger(value) || value < 1) delete state.form.interestDayOverrides[input.dataset.interestLotId];
  else state.form.interestDayOverrides[input.dataset.interestLotId] = value;
  updateSalePreview();
});
["#broker-fees", "#broker-tax", "#broker-settlement"].forEach((selector) => $(selector).addEventListener("input", updateSalePreview));

$("#trade-quantity").addEventListener("input", updateSalePreview);

$("#modal-backdrop").addEventListener("mousedown", (event) => { if (event.target === $("#modal-backdrop")) closeModal(); });
document.addEventListener("keydown", (event) => { if (event.key === "Escape" && !$("#modal-backdrop").classList.contains("hidden")) closeModal(); });
document.addEventListener("click", async (event) => {
  const target = event.target.closest("[data-action], .nav-item, #fill-all");
  if (!target) return;
  if (target.classList.contains("nav-item")) { switchView(target.dataset.view); return; }
  if (target.id === "fill-all") { $("#trade-quantity").value = state.form.sellContext.maxQuantity; updateSalePreview(); return; }
  const action = target.dataset.action;
  if (action === "summary-filter") {
    const key = target.dataset.filter;
    if (["period", "style", "accountType"].includes(key)) {
      state.summaryFilters[key] = target.dataset.value;
      render();
    }
    return;
  }
  if (action === "account-type-choice") { chooseAccountType(target.dataset.value); return; }
  if (action === "allocation-method") {
    state.form.allocationMethod = target.dataset.method;
    state.form.allocationTouched = target.dataset.method === "manual";
    if (target.dataset.method === "manual" && !Object.keys(state.form.positionAllocations).length) {
      state.form.positionAllocations = {};
    }
    updateSalePreview();
    return;
  }
  if (action === "toggle-credit-lot") {
    const id = target.dataset.lotId;
    if (state.form.positionAllocations[id]) delete state.form.positionAllocations[id];
    else {
      const lot = state.form.availableCreditLots.find((item) => item.id === id);
      const targetQuantity = Number($("#trade-quantity").value);
      const selectedQuantity = Object.values(state.form.positionAllocations).reduce((sum, quantity) => sum + Number(quantity), 0);
      if (lot) state.form.positionAllocations[id] = Math.min(lot.remainingQuantity, Math.max(1, targetQuantity - selectedQuantity || lot.remainingQuantity));
    }
    state.form.allocationTouched = true;
    state.form.allocationMethod = "manual";
    updateSalePreview();
    return;
  }
  if (action === "fill-credit-lot") {
    const lot = state.form.availableCreditLots.find((item) => item.id === target.dataset.lotId);
    if (lot) state.form.positionAllocations[lot.id] = lot.remainingQuantity;
    state.form.allocationTouched = true;
    state.form.allocationMethod = "manual";
    updateSalePreview();
    return;
  }
  if (action === "view-records") switchView("records");
  if (action === "pnl-period") { state.pnlPeriod = target.dataset.period; renderRecords(calculateLedger(state.trades)); }
  if (action === "sell") openSell(target.dataset.code, target.dataset.style ?? "スイング", target.dataset.accountType ?? "現物", null, target.dataset.date ?? null);
  if (action === "choose-security") { const security = state.securities.find((item) => item.code === target.dataset.code); state.form.selected = security; state.form.manual = false; $("#security-query").value = `${security.code}　${security.name}`; $("#security-options").classList.add("hidden"); $("#manual-fields").classList.add("hidden"); }
  if (action === "manual-security") { state.form.manual = true; state.form.selected = null; $("#security-options").classList.add("hidden"); $("#manual-fields").classList.remove("hidden"); $("#manual-code").focus(); }
  if (action === "edit") { const trade = state.trades.find((item) => item.id === target.dataset.id); if (trade) trade.action === "買付" ? openBuy(trade) : openSell(trade.code, trade.style, accountTypeOf(trade), trade); }
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

  switchView(state.activeView);
  subscribeTrades(user);
});
