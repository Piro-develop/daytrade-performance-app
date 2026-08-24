import { settlementDate } from "./credit-calculation.mjs";

export const TAX_SETTINGS = Object.freeze({
  incomeAndReconstructionRate: 0.15315,
  residentRate: 0.05,
  totalRate: 0.20315,
  yearBasis: "settlement-date",
  calculationType: "specified-account-withholding-estimate"
});

const byTaxTimeAsc = (a, b) => a.taxSettlementDate.localeCompare(b.taxSettlementDate)
  || a.date.localeCompare(b.date)
  || (a.createdAt ?? 0) - (b.createdAt ?? 0)
  || String(a.id).localeCompare(String(b.id));

export function estimatedTaxForAnnualProfit(profit) {
  const taxableProfit = Math.max(0, Math.trunc(Number(profit) || 0));
  const incomeTax = Math.floor(taxableProfit * TAX_SETTINGS.incomeAndReconstructionRate + Number.EPSILON);
  const residentTax = Math.floor(taxableProfit * TAX_SETTINGS.residentRate + Number.EPSILON);
  return { incomeTax, residentTax, totalTax: incomeTax + residentTax };
}

export function taxYearOf(trade) {
  return (trade.taxSettlementDate ?? settlementDate(trade.date)).slice(0, 4);
}

export function calculateAnnualTaxEstimates(calculatedTrades) {
  const taxResults = new Map();
  const annual = new Map();
  const completed = calculatedTrades
    .filter((trade) => trade.action === "売却" && Number.isFinite(Number(trade.realisedProfit)))
    .map((trade) => ({ ...trade, taxSettlementDate: settlementDate(trade.date) }))
    .sort(byTaxTimeAsc);

  completed.forEach((trade) => {
    const year = taxYearOf(trade);
    const summary = annual.get(year) ?? {
      year,
      realisedGains: 0,
      realisedLosses: 0,
      netRealisedProfit: 0,
      estimatedIncomeTax: 0,
      estimatedResidentTax: 0,
      estimatedTax: 0,
      estimatedAfterTaxProfit: 0
    };
    const profit = Math.trunc(Number(trade.realisedProfit));
    const previousTax = summary.estimatedTax;
    if (profit > 0) summary.realisedGains += profit;
    if (profit < 0) summary.realisedLosses += profit;
    summary.netRealisedProfit += profit;
    const tax = estimatedTaxForAnnualProfit(summary.netRealisedProfit);
    summary.estimatedIncomeTax = tax.incomeTax;
    summary.estimatedResidentTax = tax.residentTax;
    summary.estimatedTax = tax.totalTax;
    summary.estimatedAfterTaxProfit = summary.netRealisedProfit - tax.totalTax;
    annual.set(year, summary);
    const taxChange = tax.totalTax - previousTax;
    taxResults.set(trade.id, {
      taxYear: year,
      taxSettlementDate: trade.taxSettlementDate,
      annualProfitAfterTrade: summary.netRealisedProfit,
      estimatedTaxChange: taxChange,
      estimatedTaxBalance: tax.totalTax,
      estimatedAfterTaxProfit: profit - taxChange
    });
  });

  return { taxResults, annualSummaries: [...annual.values()].sort((a, b) => a.year.localeCompare(b.year)) };
}

export function estimatedAfterTaxForTrades(trades) {
  const yearlyProfits = new Map();
  trades.forEach((trade) => {
    const year = taxYearOf(trade);
    yearlyProfits.set(year, (yearlyProfits.get(year) ?? 0) + Math.trunc(Number(trade.realisedProfit) || 0));
  });
  return [...yearlyProfits.values()].reduce((sum, profit) => sum + profit - estimatedTaxForAnnualProfit(profit).totalTax, 0);
}
