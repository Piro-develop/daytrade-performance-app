export const CREDIT_SETTINGS = Object.freeze({
  settlementBusinessDays: 2,
  calculationMethod: "FIFO・受渡日T+2・両端入れ・365日割",
  rates: Object.freeze({
    "制度信用": 0.028,
    "一般信用（無期限）": 0.028,
    "日計り信用": 0.018
  })
});

export const CREDIT_TYPES = Object.freeze(Object.keys(CREDIT_SETTINGS.rates));

const CONFIRMED_JPX_HOLIDAYS = new Set([
  "2026-01-01", "2026-01-02", "2026-01-03", "2026-01-12", "2026-02-11", "2026-02-23",
  "2026-03-20", "2026-04-29", "2026-05-03", "2026-05-04", "2026-05-05", "2026-05-06",
  "2026-07-20", "2026-08-11", "2026-09-21", "2026-09-22", "2026-09-23", "2026-10-12",
  "2026-11-03", "2026-11-23", "2026-12-31",
  "2027-01-01", "2027-01-02", "2027-01-03", "2027-01-11", "2027-02-11", "2027-02-23",
  "2027-03-21", "2027-03-22", "2027-04-29", "2027-05-03", "2027-05-04", "2027-05-05",
  "2027-07-19", "2027-08-11", "2027-09-20", "2027-09-23", "2027-10-11", "2027-11-03",
  "2027-11-23", "2027-12-31"
]);

const pad = (value) => String(value).padStart(2, "0");
const dateKey = (date) => `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
const parseDate = (value) => new Date(`${value}T00:00:00`);
const addDays = (date, days) => { const next = new Date(date); next.setDate(next.getDate() + days); return next; };
const nthMonday = (year, month, nth) => {
  const first = new Date(year, month - 1, 1);
  return 1 + ((8 - first.getDay()) % 7) + (nth - 1) * 7;
};

function estimatedJapaneseHolidays(year) {
  const holidays = new Set();
  const add = (month, day) => holidays.add(`${year}-${pad(month)}-${pad(day)}`);
  add(1, 1); add(1, nthMonday(year, 1, 2)); add(2, 11); add(2, 23);
  add(3, Math.floor(20.8431 + 0.242194 * (year - 1980) - Math.floor((year - 1980) / 4)));
  add(4, 29); add(5, 3); add(5, 4); add(5, 5); add(7, nthMonday(year, 7, 3));
  add(8, 11); add(9, nthMonday(year, 9, 3));
  add(9, Math.floor(23.2488 + 0.242194 * (year - 1980) - Math.floor((year - 1980) / 4)));
  add(10, nthMonday(year, 10, 2)); add(11, 3); add(11, 23);

  [...holidays].forEach((key) => {
    const holiday = parseDate(key);
    if (holiday.getDay() !== 0) return;
    let substitute = addDays(holiday, 1);
    while (holidays.has(dateKey(substitute))) substitute = addDays(substitute, 1);
    holidays.add(dateKey(substitute));
  });
  for (let date = new Date(year, 0, 2); date.getFullYear() === year; date = addDays(date, 1)) {
    if (date.getDay() === 0 || date.getDay() === 6 || holidays.has(dateKey(date))) continue;
    if (holidays.has(dateKey(addDays(date, -1))) && holidays.has(dateKey(addDays(date, 1)))) holidays.add(dateKey(date));
  }
  holidays.add(`${year}-01-02`); holidays.add(`${year}-01-03`); holidays.add(`${year}-12-31`);
  return holidays;
}

const estimatedHolidayCache = new Map();

export function isConfirmedMarketCalendar(value) {
  const year = Number(String(value).slice(0, 4));
  return year === 2026 || year === 2027;
}

export function isMarketBusinessDay(date) {
  if (date.getDay() === 0 || date.getDay() === 6) return false;
  const key = dateKey(date);
  if (isConfirmedMarketCalendar(key)) return !CONFIRMED_JPX_HOLIDAYS.has(key);
  const year = date.getFullYear();
  if (!estimatedHolidayCache.has(year)) estimatedHolidayCache.set(year, estimatedJapaneseHolidays(year));
  return !estimatedHolidayCache.get(year).has(key);
}

export function settlementDate(tradeDate) {
  let date = parseDate(tradeDate);
  let remaining = CREDIT_SETTINGS.settlementBusinessDays;
  while (remaining > 0) {
    date = addDays(date, 1);
    if (isMarketBusinessDay(date)) remaining -= 1;
  }
  return dateKey(date);
}

export function inclusiveCalendarDays(start, end) {
  return Math.max(1, Math.round((parseDate(end) - parseDate(start)) / 86400000) + 1);
}

export function rateForCreditType(creditType) {
  return CREDIT_SETTINGS.rates[creditType] ?? 0;
}

export function calculateCreditInterest({ openDate, closeDate, price, quantity, creditType, annualRate, overrideDays = null }) {
  const openSettlementDate = settlementDate(openDate);
  const closeSettlementDate = settlementDate(closeDate);
  const automaticDays = inclusiveCalendarDays(openSettlementDate, closeSettlementDate);
  const manualDays = Number.isInteger(Number(overrideDays)) && Number(overrideDays) >= 1 ? Number(overrideDays) : null;
  const interestDays = manualDays ?? automaticDays;
  const sameDayDayTrade = creditType === "日計り信用" && openDate === closeDate;
  const appliedAnnualRate = sameDayDayTrade ? 0 : typeof annualRate === "number" && Number.isFinite(annualRate) ? annualRate : rateForCreditType(creditType);
  const rawAmount = Number(price) * Number(quantity) * appliedAnnualRate * interestDays / 365;
  return {
    openSettlementDate,
    closeSettlementDate,
    automaticDays,
    interestDays,
    manualOverride: manualDays !== null,
    appliedAnnualRate,
    amount: Math.floor(rawAmount + Number.EPSILON),
    rawAmount,
    calendarConfirmed: isConfirmedMarketCalendar(openSettlementDate) && isConfirmedMarketCalendar(closeSettlementDate)
  };
}
