export const ALLOCATION_METHODS = Object.freeze({
  oldest: "建日が古い順",
  newest: "建日が新しい順",
  profit: "評価益が大きい順",
  loss: "評価損が大きい順",
  manual: "手動指定"
});

const byOldest = (a, b) => a.date.localeCompare(b.date) || (a.createdAt ?? 0) - (b.createdAt ?? 0) || a.id.localeCompare(b.id);
const evaluationProfit = (lot, salePrice) => (Number(salePrice) - Number(lot.price)) * Number(lot.remainingQuantity);

export function sortCreditLots(lots, method, salePrice) {
  const sorted = [...lots];
  if (method === "newest") {
    return sorted.sort((a, b) => -byOldest(a, b) || evaluationProfit(b, salePrice) - evaluationProfit(a, salePrice));
  }
  if (method === "profit") {
    return sorted.sort((a, b) => evaluationProfit(b, salePrice) - evaluationProfit(a, salePrice) || byOldest(a, b));
  }
  if (method === "loss") {
    return sorted.sort((a, b) => evaluationProfit(a, salePrice) - evaluationProfit(b, salePrice) || byOldest(a, b));
  }
  return sorted.sort((a, b) => byOldest(a, b) || evaluationProfit(b, salePrice) - evaluationProfit(a, salePrice));
}

export function automaticPositionAllocations(lots, totalQuantity, method = "oldest", salePrice = 0) {
  let remaining = Number(totalQuantity);
  if (!Number.isInteger(remaining) || remaining < 1) return [];
  const allocations = [];
  for (const lot of sortCreditLots(lots, method, salePrice)) {
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
