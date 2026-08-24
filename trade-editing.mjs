const accountTypeOf = (trade) => trade.accountType === "信用" ? "信用" : "現物";

const byTimeAsc = (a, b) => String(a.date).localeCompare(String(b.date))
  || (a.createdAt ?? 0) - (b.createdAt ?? 0)
  || String(a.id).localeCompare(String(b.id));

function createUsage(trade) {
  const quantity = Number(trade.quantity);
  return {
    trade,
    openingTradeId: trade.id,
    accountType: accountTypeOf(trade),
    originalQuantity: quantity,
    committedQuantity: 0,
    remainingQuantity: quantity
  };
}

function useQuantity(lot, quantity) {
  const used = Math.max(0, Number(quantity) || 0);
  lot.committedQuantity += used;
  lot.remainingQuantity -= used;
}

function useOldestLots(lots, quantity) {
  let remaining = Math.max(0, Number(quantity) || 0);
  for (const lot of lots) {
    if (remaining <= 0) break;
    const available = Math.max(0, lot.remainingQuantity);
    const used = Math.min(available, remaining);
    useQuantity(lot, used);
    remaining -= used;
  }
}

export function openingTradeUsage(trades) {
  const usage = new Map();
  const spotByCodeAndDate = new Map();

  [...trades].filter((trade) => accountTypeOf(trade) === "現物").sort(byTimeAsc).forEach((trade) => {
    const dates = spotByCodeAndDate.get(trade.code) ?? new Map();
    const day = dates.get(trade.date) ?? [];
    day.push(trade);
    dates.set(trade.date, day);
    spotByCodeAndDate.set(trade.code, dates);
  });

  spotByCodeAndDate.forEach((dates) => {
    const lots = [];
    dates.forEach((dayTrades) => {
      const sorted = [...dayTrades].sort(byTimeAsc);
      sorted.filter((trade) => trade.action === "買付").forEach((trade) => {
        const lot = createUsage(trade);
        usage.set(trade.id, lot);
        lots.push(lot);
      });
      sorted.filter((trade) => trade.action === "売却").forEach((trade) => useOldestLots(lots, trade.quantity));
    });
  });

  const creditLotsByCode = new Map();
  [...trades].filter((trade) => accountTypeOf(trade) === "信用").sort(byTimeAsc).forEach((trade) => {
    const lots = creditLotsByCode.get(trade.code) ?? [];
    if (trade.action === "買付") {
      const lot = createUsage(trade);
      usage.set(trade.id, lot);
      lots.push(lot);
      creditLotsByCode.set(trade.code, lots);
      return;
    }
    const allocations = Array.isArray(trade.positionAllocations) ? trade.positionAllocations : [];
    if (allocations.length) {
      allocations.forEach((allocation) => {
        const lot = usage.get(allocation.openingTradeId);
        if (lot) useQuantity(lot, allocation.quantity);
      });
      return;
    }
    useOldestLots(lots, trade.quantity);
  });

  return usage;
}

export function openingLotsForPosition(trades, code, accountType) {
  return [...openingTradeUsage(trades).values()]
    .filter((lot) => lot.trade.code === code && lot.accountType === accountType && lot.remainingQuantity > 0)
    .sort((a, b) => byTimeAsc(a.trade, b.trade));
}

export function openingQuantityChangeError(trades, openingTradeId, nextQuantity) {
  const lot = openingTradeUsage(trades).get(openingTradeId);
  if (!lot || Number(nextQuantity) >= lot.committedQuantity) return "";
  const completedLabel = lot.accountType === "信用" ? "返済" : "売却";
  return `すでに${lot.committedQuantity.toLocaleString()}株${completedLabel}済みのため、買付株数を${lot.committedQuantity.toLocaleString()}株未満には変更できません。`;
}
