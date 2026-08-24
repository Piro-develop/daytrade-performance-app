export const SPOT_SETTINGS = Object.freeze({
  defaultTransactionFee: 0,
  acquisitionUnitRounding: "ceil-to-yen",
  sameDayMethod: "all-buys-before-sales"
});

const byTimeAsc = (a, b) => a.date.localeCompare(b.date)
  || (a.createdAt ?? 0) - (b.createdAt ?? 0)
  || String(a.id).localeCompare(String(b.id));

const yenAmount = (value) => Math.round(Number(value) + Number.EPSILON);

export function transactionFeeOf(trade) {
  const value = trade.transactionFee ?? trade.fee
    ?? (trade.action === "買付" ? trade.buyFee : trade.sellFee)
    ?? SPOT_SETTINGS.defaultTransactionFee;
  const fee = Number(value);
  return Number.isFinite(fee) && fee >= 0 ? yenAmount(fee) : 0;
}

export function sbiAcquisitionUnitPrice(totalAcquisitionCost, quantity) {
  if (!(Number(quantity) > 0)) return 0;
  return Math.ceil(Number(totalAcquisitionCost) / Number(quantity) - 1e-10);
}

function groupedByCodeAndDate(trades) {
  const codes = new Map();
  [...trades].sort(byTimeAsc).forEach((trade) => {
    const dates = codes.get(trade.code) ?? new Map();
    const day = dates.get(trade.date) ?? [];
    day.push(trade);
    dates.set(trade.date, day);
    codes.set(trade.code, dates);
  });
  return codes;
}

export function calculateSpotLedger(trades) {
  const spotTrades = trades.filter((trade) => trade.accountType !== "信用");
  const results = new Map();
  const positions = [];
  let invalid = null;

  groupedByCodeAndDate(spotTrades).forEach((dates, code) => {
    let taxPosition = { quantity: 0, unitPrice: 0, totalCost: 0 };
    let performancePosition = { quantity: 0, unitPrice: 0 };
    let latestTrade = null;

    dates.forEach((dayTrades, date) => {
      const sortedDay = [...dayTrades].sort(byTimeAsc);
      const buys = sortedDay.filter((trade) => trade.action === "買付");
      const sales = sortedDay.filter((trade) => trade.action === "売却");
      const buyQuantity = buys.reduce((sum, trade) => sum + Number(trade.quantity), 0);
      const saleQuantity = sales.reduce((sum, trade) => sum + Number(trade.quantity), 0);
      const buyCost = buys.reduce((sum, trade) => sum + yenAmount(Number(trade.price) * Number(trade.quantity)) + transactionFeeOf(trade), 0);
      const availableQuantity = taxPosition.quantity + buyQuantity;

      if (saleQuantity > availableQuantity) {
        invalid ??= `${date}の${sortedDay[0]?.name ?? code}（現物）は、同日の買付を含む保有株数を${saleQuantity - availableQuantity}株超えて売却しています。`;
      }

      const carriedCost = taxPosition.totalCost;
      const taxUnitPrice = availableQuantity > 0
        ? sbiAcquisitionUnitPrice(carriedCost + buyCost, availableQuantity)
        : 0;

      sortedDay.forEach((trade) => {
        latestTrade = trade;
        const quantity = Number(trade.quantity);
        const fee = transactionFeeOf(trade);
        if (trade.action === "買付") {
          const performanceTotal = performancePosition.unitPrice * performancePosition.quantity
            + yenAmount(Number(trade.price) * quantity) + fee;
          performancePosition = {
            quantity: performancePosition.quantity + quantity,
            unitPrice: performanceTotal / (performancePosition.quantity + quantity)
          };
          results.set(trade.id, {
            realisedProfit: null,
            taxRealisedProfit: null,
            tradePerformanceProfit: null,
            transactionFee: fee,
            averageCostAtSale: null,
            taxAcquisitionUnitPrice: taxUnitPrice,
            performanceAverageCost: performancePosition.unitPrice,
            creditInterest: 0,
            creditAllocations: []
          });
          return;
        }

        const proceeds = yenAmount(Number(trade.price) * quantity);
        const taxRealisedProfit = proceeds - taxUnitPrice * quantity - fee;
        const performanceUnitPrice = quantity <= performancePosition.quantity
          ? performancePosition.unitPrice
          : taxUnitPrice;
        const tradePerformanceProfit = proceeds - performanceUnitPrice * quantity - fee;
        const remainingPerformanceQuantity = Math.max(0, performancePosition.quantity - quantity);
        results.set(trade.id, {
          realisedProfit: taxRealisedProfit,
          taxRealisedProfit,
          tradePerformanceProfit,
          realisedProfitDifference: taxRealisedProfit - tradePerformanceProfit,
          grossProfitBeforeFees: proceeds - taxUnitPrice * quantity,
          grossProfitBeforeInterest: proceeds - taxUnitPrice * quantity,
          transactionFee: fee,
          averageCostAtSale: taxUnitPrice,
          taxAcquisitionUnitPrice: taxUnitPrice,
          performanceAverageCost: performancePosition.unitPrice,
          creditInterest: 0,
          creditAllocations: []
        });
        performancePosition = {
          quantity: remainingPerformanceQuantity,
          unitPrice: remainingPerformanceQuantity ? performancePosition.unitPrice : 0
        };
      });

      const remainingTaxQuantity = Math.max(0, availableQuantity - saleQuantity);
      taxPosition = {
        quantity: remainingTaxQuantity,
        unitPrice: remainingTaxQuantity > 0 ? taxUnitPrice : 0,
        totalCost: remainingTaxQuantity > 0
          ? (saleQuantity > 0 ? taxUnitPrice * remainingTaxQuantity : carriedCost + buyCost)
          : 0
      };
      if (performancePosition.quantity !== remainingTaxQuantity) {
        performancePosition = {
          quantity: remainingTaxQuantity,
          unitPrice: remainingTaxQuantity > 0 ? taxUnitPrice : 0
        };
      }
    });

    if (taxPosition.quantity > 0 && latestTrade) {
      positions.push({
        code,
        name: latestTrade.name,
        market: latestTrade.market ?? "",
        accountType: "現物",
        style: latestTrade.style,
        quantity: taxPosition.quantity,
        averagePrice: taxPosition.unitPrice,
        performanceAveragePrice: performancePosition.unitPrice
      });
    }
  });

  return { invalid, results, positions };
}
