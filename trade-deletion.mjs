const ACCOUNT_CREDIT = "\u4fe1\u7528";
const ACTION_BUY = "\u8cb7\u4ed8";

const MESSAGES = {
  notFound: "\u524a\u9664\u5bfe\u8c61\u306e\u7d04\u5b9a\u8a18\u9332\u304c\u898b\u3064\u304b\u308a\u307e\u305b\u3093\u3002",
  creditOpeningUsed: "\u3053\u306e\u4fe1\u7528\u5efa\u7389\u306f\u5f8c\u7d9a\u306e\u8fd4\u6e08\u8a18\u9332\u3067\u4f7f\u7528\u3055\u308c\u3066\u3044\u308b\u305f\u3081\u524a\u9664\u3067\u304d\u307e\u305b\u3093\u3002\u5148\u306b\u95a2\u9023\u3059\u308b\u8fd4\u6e08\u8a18\u9332\u3092\u78ba\u8a8d\u3057\u3066\u304f\u3060\u3055\u3044\u3002",
  spotOpeningInvalid: "\u3053\u306e\u8cb7\u4ed8\u3092\u524a\u9664\u3059\u308b\u3068\u3001\u5f8c\u7d9a\u306e\u58f2\u5374\u6642\u70b9\u3067\u4fdd\u6709\u682a\u6570\u304c\u4e0d\u8db3\u3059\u308b\u305f\u3081\u524a\u9664\u3067\u304d\u307e\u305b\u3093\u3002",
  invalidHistory: "\u3053\u306e\u7d04\u5b9a\u3092\u524a\u9664\u3059\u308b\u3068\u53d6\u5f15\u5c65\u6b74\u304c\u6210\u7acb\u3057\u306a\u3044\u305f\u3081\u524a\u9664\u3067\u304d\u307e\u305b\u3093\u3002"
};

const accountTypeOf = (trade) => trade?.accountType === ACCOUNT_CREDIT ? ACCOUNT_CREDIT : "\u73fe\u7269";

export function validateTradeDeletion(trades, id, calculateLedger) {
  const source = Array.isArray(trades) ? trades : [];
  const target = source.find((trade) => trade.id === id);
  if (!target) return { ok: false, error: MESSAGES.notFound, target: null, candidate: source, ledger: null };

  if (target.action === ACTION_BUY && accountTypeOf(target) === ACCOUNT_CREDIT) {
    const referenced = source.some((trade) =>
      trade.id !== id &&
      Array.isArray(trade.positionAllocations) &&
      trade.positionAllocations.some((allocation) => allocation.openingTradeId === id)
    );
    if (referenced) return { ok: false, error: MESSAGES.creditOpeningUsed, target, candidate: source, ledger: null };
  }

  const candidate = source.filter((trade) => trade.id !== id);
  const ledger = calculateLedger(candidate);
  if (ledger.invalid) {
    const error = target.action === ACTION_BUY && accountTypeOf(target) !== ACCOUNT_CREDIT
      ? MESSAGES.spotOpeningInvalid
      : `${MESSAGES.invalidHistory}\n${ledger.invalid}`;
    return { ok: false, error, target, candidate, ledger };
  }

  return { ok: true, error: "", target, candidate, ledger };
}

export async function deleteTradeOnce({ id, pendingIds, deleteDocument }) {
  if (pendingIds.has(id)) return { status: "pending", error: null };
  pendingIds.add(id);
  try {
    await deleteDocument(id);
    return { status: "deleted", error: null };
  } catch (error) {
    return { status: "failed", error };
  } finally {
    pendingIds.delete(id);
  }
}
