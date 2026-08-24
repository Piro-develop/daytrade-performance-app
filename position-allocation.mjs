export const ALLOCATION_METHODS = Object.freeze({
  profit: "SBI標準：評価益順",
  loss: "評価損順",
  oldest: "建日古い順",
  newest: "建日新しい順",
  manual: "手動指定"
});

export const ALLOCATION_SETTINGS = Object.freeze({
  defaultMethod: "profit",
  defaultTradingUnit: 100
});

const byCreated = (a, b) => (a.createdAt ?? 0) - (b.createdAt ?? 0) || a.id.localeCompare(b.id);
const byOldest = (a, b) => a.date.localeCompare(b.date) || byCreated(a, b);
const byBuildDate = (a, b) => a.date.localeCompare(b.date);
const hasOwn = (object, key) => Object.prototype.hasOwnProperty.call(object ?? {}, key);
const positiveNumber = (value, fallback) => Number(value) > 0 ? Number(value) : fallback;

function normalizeEvaluationContext(context) {
  return typeof context === "object" && context !== null ? context : { fallbackPrice: Number(context) };
}

export function creditLotEvaluation(lot, context = {}) {
  const settings = normalizeEvaluationContext(context);
  const quantity = Number(lot.remainingQuantity);
  const tradingUnit = positiveNumber(settings.tradingUnit ?? lot.tradingUnit, ALLOCATION_SETTINGS.defaultTradingUnit);
  const unitCount = quantity > 0 ? quantity / tradingUnit : 0;
  const hasSbiProfit = hasOwn(settings.evaluationProfitOverrides, lot.id) && settings.evaluationProfitOverrides[lot.id] !== "" && Number.isFinite(Number(settings.evaluationProfitOverrides[lot.id]));
  const evaluationPrice = positiveNumber(settings.evaluationPrice, positiveNumber(settings.fallbackPrice, 0));
  const expenses = hasOwn(settings.evaluationExpenseOverrides, lot.id) && settings.evaluationExpenseOverrides[lot.id] !== "" && Number.isFinite(Number(settings.evaluationExpenseOverrides[lot.id]))
    ? Number(settings.evaluationExpenseOverrides[lot.id]) : 0;
  const totalProfit = hasSbiProfit
    ? Number(settings.evaluationProfitOverrides[lot.id])
    : evaluationPrice > 0 ? (evaluationPrice - Number(lot.price)) * quantity - expenses : 0;
  return {
    totalProfit,
    perTradingUnitProfit: unitCount > 0 ? totalProfit / unitCount : 0,
    tradingUnit,
    evaluationPrice,
    expenses,
    source: hasSbiProfit ? "sbi-profit" : settings.evaluationPrice > 0 ? "evaluation-price" : "fallback-price",
    estimated: !hasSbiProfit
  };
}

const perUnitProfit = (lot, context) => creditLotEvaluation(lot, context).perTradingUnitProfit;

export function sortCreditLots(lots, method, context = {}) {
  const sorted = [...lots];
  if (method === "newest") {
    return sorted.sort((a, b) => -byBuildDate(a, b) || perUnitProfit(b, context) - perUnitProfit(a, context) || byCreated(a, b));
  }
  if (method === "profit") {
    return sorted.sort((a, b) => perUnitProfit(b, context) - perUnitProfit(a, context) || byOldest(a, b));
  }
  if (method === "loss") {
    return sorted.sort((a, b) => perUnitProfit(a, context) - perUnitProfit(b, context) || byOldest(a, b));
  }
  return sorted.sort((a, b) => byBuildDate(a, b) || perUnitProfit(b, context) - perUnitProfit(a, context) || byCreated(a, b));
}

export function automaticPositionAllocations(lots, totalQuantity, method = ALLOCATION_SETTINGS.defaultMethod, context = {}) {
  let remaining = Number(totalQuantity);
  if (!Number.isInteger(remaining) || remaining < 1) return [];
  const allocations = [];
  for (const lot of sortCreditLots(lots, method, context)) {
    if (remaining <= 0) break;
    const quantity = Math.min(remaining, Number(lot.remainingQuantity));
    if (quantity <= 0) continue;
    allocations.push({ openingTradeId: lot.id, quantity });
    remaining -= quantity;
  }
  return allocations;
}

export function allocationObjectToArray(allocationObject = {}) {
  return Object.entries(allocationObject)
    .map(([openingTradeId, quantity]) => ({ openingTradeId, quantity: Number(quantity) }))
    .filter((item) => Number.isInteger(item.quantity) && item.quantity > 0);
}

export function allocationArrayToObject(allocations = []) {
  return Object.fromEntries(allocations.map((item) => [item.openingTradeId, Number(item.quantity)]));
}
