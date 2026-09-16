"""Bounded, independent public price sources. No scoring, credentials or gap filling."""
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
import hashlib
import json
import logging
import math
import re

import requests

JST = timezone(timedelta(hours=9))
CHARTS = ("https://query1.finance.yahoo.com/v8/finance/chart/",
          "https://query2.finance.yahoo.com/v8/finance/chart/")
MINKABU = "https://mkdd.net/api/v1/bar/"
ERRORS = (requests.RequestException, ValueError, KeyError, TypeError, IndexError, OverflowError)
LOG = logging.getLogger("uvicorn.error")


def download(url, params=None):
    with requests.get(url, params=params, timeout=(5, 12), stream=True,
                      allow_redirects=False, headers={"User-Agent": "TradingJournal/1.0"}) as response:
        response.raise_for_status()
        if response.status_code != 200:
            raise ValueError("unexpected_http_status")
        parts, size = [], 0
        for part in response.iter_content(65536):
            size += len(part)
            if size > 8_000_000:
                raise ValueError("response_limit")
            parts.append(part)
        return b"".join(parts)


def ohlcv(values):
    if any(isinstance(values[k], bool) for k in ("open", "high", "low", "close", "volume")):
        raise ValueError("invalid_ohlcv")
    out = {k: float(values[k]) for k in ("open", "high", "low", "close", "volume")}
    if not all(math.isfinite(v) for v in out.values()) or out["volume"] < 0:
        raise ValueError("invalid_ohlcv")
    if min(out[k] for k in ("open", "high", "low", "close")) <= 0:
        raise ValueError("invalid_ohlcv")
    if out["high"] < max(out["open"], out["close"], out["low"]) or out["low"] > min(out["open"], out["close"], out["high"]):
        raise ValueError("invalid_ohlcv")
    return out


def session_close(day):
    return datetime.combine(day, time(15, 30) if day >= date(2024, 11, 5) else time(15), JST)


def trading_minute(start):
    close = session_close(start.date()).time()
    return time(9) <= start.time() < time(11, 30) or time(12, 30) <= start.time() < close


def normalize_chart(data, symbol, interval, now):
    """Provider timestamps are bar starts; emit only closed bars, at bar end in JST."""
    if not isinstance(data, dict) or not isinstance(data.get("meta", {}), dict):
        raise ValueError("invalid_price_response")
    quotes = data["indicators"]["quote"][0]
    rows, omitted = {}, 0
    basis = data.get("meta", {}).get("adjustment_basis", "yahoo_split_adjusted")
    for i, stamp in enumerate(data.get("timestamp", [])):
        start = datetime.fromtimestamp(stamp, timezone.utc).astimezone(JST)
        if interval == "1d":
            end = session_close(start.date())
        else:
            if start.minute % 5 or start.second or start.microsecond or not trading_minute(start):
                continue
            end = start + timedelta(minutes=5)
        if end > now:
            continue
        try:
            values = ohlcv({k: quotes[k][i] for k in ("open", "high", "low", "close", "volume")})
        except (ValueError, TypeError, KeyError, IndexError):
            omitted += 1
            continue
        if interval != "1d" and values["volume"] == 0:
            # Some upstream bars repeat the prior close with zero trades.
            # They cannot establish an actual intraday price observation.
            omitted += 1
            continue
        row = {"symbol_code": symbol, "timestamp": end.isoformat(), **values, "adjustment_basis": basis}
        if end in rows and rows[end] != row:
            raise ValueError("conflicting_bars")
        rows[end] = row
    if not rows:
        raise ValueError("no_completed_bars")
    ordered = [rows[t] for t in sorted(rows)]
    if interval != "1d":
        # Retain the actual latest trading session on holidays/after midnight.
        # The existing daytrade engine separately rejects prior-day/stale data.
        latest_day = ordered[-1]["timestamp"][:10]
        ordered = [r for r in ordered if r["timestamp"][:10] == latest_day]
    return ordered, omitted


def minkabu_chart(symbol, interval, now, fetch):
    """Public chart feed used by minkabu.jp; independent of Yahoo's query hosts.

    The feed's 5m route is empty for these stocks. Aggregate its actual 1m OHLCV,
    requiring all five minutes. Its delayed feed is never labelled realtime.
    Keep the chart's OHLC and reported volume as published: no guessed split
    factors, no blending of Yahoo/Minkabu histories or adjustment conventions.
    """
    native = "daily" if interval == "1d" else "1m"
    params = {"ric": symbol + ".T", "limit": 1500 if interval == "1d" else 1000}
    url = MINKABU + native
    raw = fetch(url, params)
    items = json.loads(raw)
    if not isinstance(items, list) or not items:
        raise ValueError("empty_price_response")
    points, omitted = {}, 0
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("invalid_price_response")
        if item.get("ric") != symbol + ".T" or item.get("currency_code") != "JPY":
            raise ValueError("wrong_market")
        if interval == "1d":
            day = date.fromisoformat(item["date"])
            start = datetime.combine(day, time(9), JST)
            end = session_close(day)
        else:
            start = datetime.fromisoformat(item["date"])
            if start.tzinfo is None:
                raise ValueError("missing_timezone")
            start = start.astimezone(JST)
            if start.second or start.microsecond or not trading_minute(start):
                continue
            end = start + timedelta(minutes=1)
        # At least 15 minutes delayed; exclude the possibly updating last minute.
        if end > now - timedelta(minutes=15):
            continue
        try:
            values = ohlcv(item)
        except (ValueError, TypeError, KeyError):
            omitted += 1
            continue
        if start in points and points[start] != values:
            raise ValueError("conflicting_bars")
        points[start] = values
    if interval != "1d":
        groups = defaultdict(dict)
        for start, values in points.items():
            groups[start.replace(minute=start.minute // 5 * 5)][start] = values
        points = {}
        for start, group in groups.items():
            expected = [start + timedelta(minutes=i) for i in range(5)]
            if any(t not in group for t in expected):
                omitted += 1
                continue
            values = [group[t] for t in expected]
            points[start] = {"open": values[0]["open"], "high": max(v["high"] for v in values),
                             "low": min(v["low"] for v in values), "close": values[-1]["close"],
                             "volume": sum(v["volume"] for v in values)}
    if not points:
        raise ValueError("no_completed_bars")
    starts = sorted(points)
    meta = {"source": "みんかぶ公開チャート", "provider": "minkabu",
            "adjustment_basis": "minkabu_chart_as_published", "source_omitted": omitted,
            "source_note": "公開チャートのOHLC・出来高をそのまま使用。調整係数を推定せず、他社系列と継ぎ足さない。15分以上遅延。"}
    if interval != "1d":
        meta["source_note"] += " 実測1分足が5本揃った区間のみOHLC・出来高を集計。欠落区間は除外。"
    data = {"meta": meta, "timestamp": [int(t.timestamp()) for t in starts],
            "indicators": {"quote": [{k: [points[t][k] for t in starts] for k in ("open", "high", "low", "close", "volume")}]}}
    source_uri = requests.Request("GET", url, params=params).prepare().url
    return data, source_uri, hashlib.sha256(raw).hexdigest()


def failure_log(provider, symbol, interval, stage, exc):
    # No response body, arbitrary exception message, UID, bearer or user input.
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    known = {"wrong_market", "no_completed_bars", "empty_price_response", "conflicting_bars", "response_limit", "missing_timezone"}
    reason = str(exc) if str(exc) in known else "upstream_failure"
    LOG.warning("price_fetch source=%s symbol=%s interval=%s stage=%s status=failed http=%s error=%s reason=%s",
                provider, symbol, interval, stage, status, type(exc).__name__, reason)


def chart(symbol, interval, now=None, fetch=download):
    now = now or datetime.now(timezone.utc)
    if not re.fullmatch(r"[0-9][0-9A-Z]{3}", symbol):
        raise ValueError("invalid_symbol")
    if interval not in {"1d", "5m"}:
        raise ValueError("unsupported_interval")
    for i, base in enumerate(CHARTS):
        provider, stage = "yahoo-query" + str(i + 1), "download"
        try:
            params = {"range": "5y" if interval == "1d" else "5d", "interval": interval, "events": "splits"}
            url = base + symbol + ".T"
            raw = fetch(url, params)
            stage = "decode"
            data = json.loads(raw)["chart"]["result"][0]
            meta = data["meta"]
            if not isinstance(meta, dict):
                raise ValueError("invalid_price_response")
            if meta.get("symbol") != symbol + ".T" or meta.get("currency") != "JPY" or meta.get("instrumentType") != "EQUITY" or meta.get("exchangeName") not in {"JPX", "TYO", "OSA"}:
                raise ValueError("wrong_market")
            meta.update(provider=provider, source="Yahoo Finance 公開株価", adjustment_basis="yahoo_split_adjusted")
            stage = "completed_bars"
            rows, _ = normalize_chart(data, symbol, interval, now)
            LOG.info("price_fetch source=%s symbol=%s interval=%s status=ok bars=%s observed=%s",
                     provider, symbol, interval, len(rows), rows[-1]["timestamp"])
            return data, requests.Request("GET", url, params=params).prepare().url, hashlib.sha256(raw).hexdigest()
        except ERRORS as exc:
            failure_log(provider, symbol, interval, stage, exc)
    try:
        data, url, hash_value = minkabu_chart(symbol, interval, now, fetch)
        rows, _ = normalize_chart(data, symbol, interval, now)
        LOG.info("price_fetch source=minkabu symbol=%s interval=%s status=ok bars=%s observed=%s",
                 symbol, interval, len(rows), rows[-1]["timestamp"])
        return data, url, hash_value
    except ERRORS as exc:
        failure_log("minkabu", symbol, interval, "download_or_completed_bars", exc)
        raise ValueError("public prices unavailable") from exc
