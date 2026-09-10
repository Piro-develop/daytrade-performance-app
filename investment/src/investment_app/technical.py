"""Reproducible closed-bar calculations and structure-based support/resistance."""
from __future__ import annotations
from datetime import datetime, time, timedelta
import math
import numpy as np
import pandas as pd
from .models import Band, Bundle, Evidence, JST, digest, plain, time_value

def number(value):
    return None if value is None or not math.isfinite(float(value)) else float(value)

def indicators(frame: pd.DataFrame, periods: list[int], cfg: dict) -> pd.DataFrame:
    out = frame.copy()
    if out.empty:
        for column in [*[f"ma{p}" for p in periods], "atr", "rsi", "bb_mid", "bb_upper", "bb_lower", "volume_ratio"]:
            out[column] = pd.Series(dtype=float)
        return out
    for period in periods:
        out[f"ma{period}"] = out.close.rolling(period).mean()
    prev = out.close.shift(1)
    tr = pd.concat([out.high-out.low, (out.high-prev).abs(), (out.low-prev).abs()], axis=1).max(axis=1)
    tr.iloc[0] = np.nan  # Previous close is required, never silently invented.
    out["atr"] = tr.rolling(cfg["atr_period"]).mean()
    center = out.close.rolling(cfg["bb_period"]).mean()
    std = out.close.rolling(cfg["bb_period"]).std(ddof=0)
    out["bb_mid"] = center
    out["bb_upper"] = center + cfg["bb_deviation"] * std
    out["bb_lower"] = center - cfg["bb_deviation"] * std
    delta = out.close.diff()
    gain = delta.clip(lower=0).rolling(cfg["rsi_period"]).mean()
    loss = (-delta.clip(upper=0)).rolling(cfg["rsi_period"]).mean()
    rs = gain / loss.replace(0, np.nan)
    out["rsi"] = 100 - 100 / (1 + rs)
    out.loc[(loss == 0) & (gain > 0), "rsi"] = 100
    out.loc[(loss == 0) & (gain == 0), "rsi"] = 50
    out["volume_mean20"] = out.volume.shift(1).rolling(cfg["comparison_days"]).mean()
    out["volume_ratio"] = out.volume / out.volume_mean20.replace(0, np.nan)
    return out

def weekly_bars(daily: pd.DataFrame, as_of: str, sessions: list[str]) -> pd.DataFrame:
    weekly = daily.resample("W-FRI").agg(
        {"open":"first","high":"max","low":"min","close":"last","volume":"sum"})
    weekly = weekly.dropna(subset=["close"])
    cutoff = time_value(as_of).astimezone(JST)
    keep = []
    for stamp in weekly.index:
        friday = stamp.date()
        closed_at = datetime.combine(friday, time(15,30), JST)
        # A supplied calendar covering this Friday can close a holiday week earlier.
        if sessions and max(sessions) >= friday.isoformat():
            monday = friday - timedelta(days=4)
            weekdays = [s for s in sessions if monday.isoformat() <= s <= friday.isoformat()]
            if weekdays:
                closed_at = datetime.combine(datetime.fromisoformat(max(weekdays)).date(), time(15,30), JST)
        keep.append(closed_at <= cutoff)
    return weekly.loc[keep]

def pivots(frame: pd.DataFrame, span: int, major_span: int) -> list[dict]:
    result = []
    for column, kind, extreme in [("high","high",np.max),("low","low",np.min)]:
        values = frame[column].to_numpy()
        for i in range(span, len(values)-span):
            window = values[i-span:i+span+1]
            best = extreme(window)
            if values[i] != best or np.flatnonzero(window == best)[-1] != span:
                continue
            previous = values[max(0,i-major_span+1):i+1]
            result.append({"kind":kind,"price":float(values[i]),"index":i,
                           "observed_at":frame.index[i].isoformat(),
                           "confirmed_at":frame.index[i+span].isoformat(),
                           "major":values[i] == extreme(previous)})
    return sorted(result, key=lambda p:(p["index"],p["kind"]))

def cluster_levels(levels: list[dict], daily: pd.DataFrame, atr: float | None,
                   tick: float, cfg: dict) -> list[Band]:
    tolerance = max(tick * cfg["min_cluster_ticks"], (atr or 0) * cfg["cluster_atr"])
    groups = []
    for level in sorted(levels, key=lambda l:(l["low"], l["id"])):
        if groups and max(max(x["high"] for x in groups[-1]),level["high"]) - min(x["low"] for x in groups[-1]) <= tolerance:
            groups[-1].append(level)
        else:
            groups.append([level])
    bands = []
    daily_lows, daily_highs = daily.low.to_numpy(), daily.high.to_numpy()
    for group in groups:
        low, high = min(x["low"] for x in group), max(x["high"] for x in group)
        family_strength = {}
        for x in group:
            weight = cfg["timeframe_weights"][x["timeframe"]] * cfg["source_weights"][x["source"]]
            family_strength[x["family"]] = max(weight, family_strength.get(x["family"], 0))
        reactions, last, touching = 0, None, False
        for i in range(len(daily)-1):
            contact = daily_lows[i] <= high and daily_highs[i] >= low
            away = daily_lows[i+1] > high or daily_highs[i+1] < low
            if contact and not touching:
                touching = True
            if touching and away:
                reactions += 1
                last = i+1
                touching = False
        age = len(daily)-1-last if last is not None else 10000
        recency = 1 if age <= cfg["recency_bars"][0] else .5 if age <= cfg["recency_bars"][1] else 0
        strength = (sum(family_strength.values()) + cfg["reaction_weight"] * min(reactions,cfg["reaction_cap"])
                    + recency + cfg["family_bonus"] * min(max(0,len(family_strength)-1),cfg["family_bonus_cap"]))
        refs = tuple(sorted({r for x in group for r in x["evidence_ids"]}))
        primary = any(x["timeframe"] == "1w" or x["source"] in {"major_pivot","volume_profile"} for x in group)
        bands.append(Band(digest(group)[:16], low, high, strength, tuple(sorted(family_strength)), refs, primary, reactions))
    return sorted(bands, key=lambda b:b.low)

def compute(bundle: Bundle, cfg: dict) -> dict:
    frame = pd.DataFrame(bundle.bars)
    frame.index = pd.to_datetime(frame.pop("timestamp"), utc=True).dt.tz_convert("Asia/Tokyo")
    frame = frame[["open","high","low","close","volume"]]
    # Input timestamps describe the bar close, so unclosed daily rows cannot enter the calculation.
    cutoff = time_value(bundle.as_of)
    frame = frame.loc[[x.to_pydatetime() <= cutoff for x in frame.index]]
    daily = indicators(frame, cfg["daily_ma"], cfg)
    weekly = indicators(weekly_bars(frame, bundle.as_of, bundle.metadata.get("calendar", [])),
                        cfg["weekly_ma"], cfg) if len(frame) else frame.copy()
    market_ref = bundle.metadata["market_evidence_id"]
    tech_id = "technical-" + digest({"bundle":bundle.bundle_id, "cfg":cfg})[:16]
    bundle.evidence[tech_id] = Evidence(tech_id, "テクニカル計算", "local:technical",
        bundle.bars[-1]["timestamp"], bundle.bars[-1]["timestamp"], bundle.as_of,
        "確定足からMA/BB/RSI/ATR/Fib/pivot/支持抵抗を計算", digest({"bars":bundle.bars,"cfg":cfg}),
        "calculation", 1, (market_ref,))
    levels, pivot_sets, fib = [], {}, []
    def add(price, timeframe, family, source, refs, token, high=None):
        if number(price) is None or price <= 0:
            return
        levels.append({"id":digest([token,price,timeframe])[:16], "low":float(price),
                       "high":float(high if high is not None else price),"timeframe":timeframe,
                       "family":family,"source":source,"evidence_ids":list(refs)})
    for interval, data, periods in [("1d",daily,cfg["daily_ma"]),("1w",weekly,cfg["weekly_ma"])]:
        data = data.tail(cfg["daily_lookback"] if interval=="1d" else cfg["weekly_lookback"])
        if data.empty:
            pivot_sets[interval] = []
            continue
        ps = pivots(data, cfg["pivot_span"], cfg["major_span"])
        pivot_sets[interval] = ps
        for p in ps:
            add(p["price"],interval,"price_structure","major_pivot" if p["major"] else "pivot",(tech_id,),p["observed_at"]+p["kind"])
        for period in periods:
            add(data.iloc[-1][f"ma{period}"],interval,"moving_average","ma",(tech_id,),"ma"+str(period))
        for band in ("bb_upper","bb_lower"):
            add(data.iloc[-1][band],interval,"volatility_band","bb",(tech_id,),band)
        for i in range(1,len(data)):
            if data.iloc[i].low > data.iloc[i-1].high:
                add(data.iloc[i-1].high,interval,"price_structure","gap",(tech_id,),"gap"+str(i),data.iloc[i].low)
            elif data.iloc[i].high < data.iloc[i-1].low:
                add(data.iloc[i].high,interval,"price_structure","gap",(tech_id,),"gap"+str(i),data.iloc[i-1].low)
        if len(ps) >= 2:
            end = ps[-1]
            start = next((p for p in reversed(ps[:-1]) if p["kind"] != end["kind"]), None)
            if start:
                for ratio in (.236,.382,.5,.618,.786):
                    price = end["price"] + (start["price"]-end["price"]) * ratio
                    fib.append({"timeframe":interval,"ratio":ratio,"price":price,"start":start,"end":end})
                    add(price,interval,"fibonacci","fib",(tech_id,),str(ratio))
    latest = float(daily.iloc[-1].close)
    step = cfg["round_number_step"]
    for price in range(max(step,int(latest*.7/step)*step),int(latest*1.3/step)*step+step,step):
        add(price,"1d","round_number","round_number",(tech_id,),str(price))
    for i, item in enumerate(bundle.metadata.get("volume_profile", [])):
        refs = tuple(item.get("evidence_ids", []))
        if item.get("measured") and refs and all(r in bundle.evidence for r in refs):
            low, high = float(item["low"]), float(item["high"])
            if 0 < low <= high and float(item.get("volume",0)) > 0:
                add(low,"1d","volume_profile","volume_profile",refs,"vp"+str(i),high)
    tick = bundle.metadata.get("tick_size")
    tick_valid = bool(tick and float(tick) > 0 and bundle.metadata.get("tick_evidence_id") in bundle.evidence)
    atr = number(daily.iloc[-1].atr)
    bands = cluster_levels(levels, daily.tail(cfg["daily_lookback"]), atr, float(tick) if tick_valid else 1, cfg) if tick_valid else []
    trend = "不明"
    slope = None
    if len(weekly) >= cfg["weekly_min"]:
        row = weekly.iloc[-1]
        slope = number(row.ma26-weekly.iloc[-1-cfg["slope_periods"]].ma26)
        trend = "上昇" if row.ma13 > row.ma26 > row.ma52 and slope > 0 else "下降" if row.ma13 < row.ma26 < row.ma52 and slope < 0 else "混在"
    return {"daily":daily,"weekly":weekly,"bands":bands,"pivots":pivot_sets,"fibonacci":fib,
            "latest":latest,"atr":atr,"rsi":number(daily.iloc[-1].rsi),"weekly_trend":trend,
            "weekly_slope":slope,"weekly_count":len(weekly),"technical_evidence_id":tech_id,
            "levels":levels,"tick_valid":tick_valid,"volume_ratio":number(daily.iloc[-1].volume_ratio)}
