const NICE_FACTORS = [1, 2, 5, 10];

function niceStep(rawStep) {
  const safeStep = Math.max(1, Number(rawStep) || 1);
  const power = 10 ** Math.floor(Math.log10(safeStep));
  const normalized = safeStep / power;
  const factor = NICE_FACTORS.find((candidate) => normalized <= candidate) ?? 10;
  return factor * power;
}

function axisBounds(dataMin, dataMax, step) {
  return {
    min: Math.floor(dataMin / step) * step,
    max: Math.ceil(dataMax / step) * step
  };
}

function tickCount(min, max, step) {
  return Math.round((max - min) / step) + 1;
}

export function createChartAxis(inputValues) {
  const values = inputValues.map(Number).filter(Number.isFinite);
  const dataMin = Math.min(0, ...values);
  const dataMax = Math.max(0, ...values);

  if (dataMin === dataMax) {
    return { min: -20000, max: 20000, step: 10000, ticks: [-20000, -10000, 0, 10000, 20000] };
  }

  const range = dataMax - dataMin;
  let step = niceStep(range / 5);
  let bounds = axisBounds(dataMin, dataMax, step);

  while (tickCount(bounds.min, bounds.max, step) > 6) {
    step = niceStep(step * 1.01);
    bounds = axisBounds(dataMin, dataMax, step);
  }

  while (tickCount(bounds.min, bounds.max, step) < 4) {
    if (dataMin < 0 && dataMax > 0) {
      if (Math.abs(bounds.min) <= bounds.max) bounds.min -= step;
      else bounds.max += step;
    } else if (dataMin < 0) bounds.min -= step;
    else bounds.max += step;
  }

  const ticks = [];
  for (let value = bounds.min; value <= bounds.max; value += step) {
    ticks.push(Object.is(value, -0) ? 0 : value);
  }
  return { ...bounds, step, ticks };
}

export function formatChartTick(value) {
  const amount = Math.round(Number(value));
  if (amount === 0) return "0円";
  const sign = amount < 0 ? "−" : "";
  const absolute = Math.abs(amount);
  if (absolute >= 100000000) {
    return `${sign}${(absolute / 100000000).toLocaleString("ja-JP", { maximumFractionDigits: 1 })}億円`;
  }
  if (absolute >= 10000) {
    return `${sign}${(absolute / 10000).toLocaleString("ja-JP", { maximumFractionDigits: 1 })}万円`;
  }
  return `${sign}${absolute.toLocaleString("ja-JP")}円`;
}
