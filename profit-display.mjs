import { calculateAnnualTaxEstimates, estimatedAfterTaxForTrades } from "./tax-calculation.mjs";

function finiteNumber(value) {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

export function brokerActualAfterTaxProfitOf(trade) {
  if (trade?.action !== "売却" || trade?.accountType !== "信用") return null;
  return finiteNumber(trade.brokerActuals?.settlement);
}

export function afterTaxProfitOf(trade) {
  return brokerActualAfterTaxProfitOf(trade)
    ?? finiteNumber(trade?.estimatedAfterTaxProfit)
    ?? finiteNumber(trade?.realisedProfit)
    ?? 0;
}

export function afterTaxSourceLabel(trade) {
  return brokerActualAfterTaxProfitOf(trade) === null ? "概算" : "SBI実績";
}

export function afterTaxTotalForTrades(trades) {
  const scopedTax = calculateAnnualTaxEstimates(trades);
  const scopedTrades = trades.map((trade) => ({ ...trade, ...(scopedTax.taxResults.get(trade.id) ?? {}) }));
  const estimatedTotal = estimatedAfterTaxForTrades(scopedTrades);
  return scopedTrades.reduce((total, trade) => {
    const actual = brokerActualAfterTaxProfitOf(trade);
    if (actual === null) return total;
    return total + actual - afterTaxProfitOf({ ...trade, brokerActuals: null });
  }, estimatedTotal);
}
