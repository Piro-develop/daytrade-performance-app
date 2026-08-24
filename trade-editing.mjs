const accountTypeOf = (trade) => trade.accountType === "信用" ? "信用" : "現物";

const byTimeAsc = (a, b) => String(a.date).localeCompare(String(b.date))
  || (a.createdAt ?? 0) - (b.createdAt ?? 0)
  || String(a.id).localeCompare(String(b.id));

function createCreditUsage(trade) {
  const quantity = Number(trade.quantity);
  return {
    trade,
    openingTradeId: trade.id,
    accountType: "信用",
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

function useOldestCreditLots(lots, quantity) {
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
  const creditLotsByCode = new Map();

  [...trades].filter((trade) => accountTypeOf(trade) === "信用").sort(byTimeAsc).forEach((trade) => {
    const lots = creditLotsByCode.get(trade.code) ?? [];
    if (trade.action === "買付") {
      const lot = createCreditUsage(trade);
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
    useOldestCreditLots(lots, trade.quantity);
  });

  return usage;
}

export function spotOpeningTradesForCurrentCycle(trades, code) {
  const dates = new Map();
  [...trades]
    .filter((trade) => accountTypeOf(trade) === "現物" && trade.code === code)
    .sort(byTimeAsc)
    .forEach((trade) => {
      const day = dates.get(trade.date) ?? [];
      day.push(trade);
      dates.set(trade.date, day);
    });

  let holdingQuantity = 0;
  let cycleBuys = [];
  dates.forEach((dayTrades) => {
    const sorted = [...dayTrades].sort(byTimeAsc);
    const buys = sorted.filter((trade) => trade.action === "買付");
    const sales = sorted.filter((trade) => trade.action === "売却");
    if (holdingQuantity === 0) cycleBuys = [];
    cycleBuys.push(...buys);
    holdingQuantity += buys.reduce((sum, trade) => sum + Number(trade.quantity), 0);
    holdingQuantity -= sales.reduce((sum, trade) => sum + Number(trade.quantity), 0);
    if (holdingQuantity <= 0) cycleBuys = [];
  });
  return holdingQuantity > 0 ? cycleBuys : [];
}

export function openingLotsForPosition(trades, code, accountType) {
  if (accountType === "現物") {
    return spotOpeningTradesForCurrentCycle(trades, code).map((trade) => ({
      trade,
      openingTradeId: trade.id,
      accountType: "現物",
      originalQuantity: Number(trade.quantity),
      committedQuantity: null,
      remainingQuantity: null
    }));
  }
  return [...openingTradeUsage(trades).values()]
    .filter((lot) => lot.trade.code === code && lot.remainingQuantity > 0)
    .sort((a, b) => byTimeAsc(a.trade, b.trade));
}

export function openingQuantityChangeError(trades, openingTradeId, nextQuantity) {
  const openingTrade = trades.find((trade) => trade.id === openingTradeId);
  if (!openingTrade || accountTypeOf(openingTrade) !== "信用") return "";
  const lot = openingTradeUsage(trades).get(openingTradeId);
  if (!lot || Number(nextQuantity) >= lot.committedQuantity) return "";
  return `すでに${lot.committedQuantity.toLocaleString()}株返済済みのため、買付株数を${lot.committedQuantity.toLocaleString()}株未満には変更できません。`;
}
