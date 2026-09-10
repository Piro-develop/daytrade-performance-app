"""Offline providers. A missing connector never starts network or paid calls."""
from __future__ import annotations
from dataclasses import fields
from io import BytesIO
from pathlib import Path
from datetime import date
from typing import Protocol
import json
import pandas as pd
from .models import Bundle, Evidence, Finding, InputError, Severity, digest, time_value, JST

class Provider(Protocol):
    def capabilities(self) -> dict: ...
    def fetch(self, symbol: str, as_of: str) -> Bundle: ...

class MarketProvider(Protocol):
    def fetch(self, symbol: str, start: str, end: str, interval: str) -> dict: ...

class FinancialProvider(Protocol):
    def fetch(self, symbol: str, periods: list[str], as_of: str) -> dict: ...

class NewsProvider(Protocol):
    def search(self, symbol: str, as_of: str) -> dict: ...

class MacroProvider(Protocol):
    def fetch(self, driver_ids: list[str], as_of: str) -> dict: ...

class LocalCSVProvider:
    def __init__(self, csv_data: bytes, metadata: dict):
        self.csv_data = csv_data
        self.metadata = metadata

    def capabilities(self) -> dict:
        return {"market": True, "manual_evidence": True, "network": False,
                "intervals": ["1d"], "paid": False}

    def fetch(self, symbol: str, as_of: str) -> Bundle:
        validate_metadata(self.metadata,as_of)
        if not symbol.strip():
            raise InputError("銘柄コードを入力してください。")
        if symbol != str(self.metadata.get("symbol", "")):
            raise InputError("入力銘柄と補足情報の銘柄コードが一致しません。")
        time_value(as_of)
        if len(self.csv_data) > 10_000_000:
            raise InputError("CSVは10MB以内にしてください。")
        try:
            frame = pd.read_csv(BytesIO(self.csv_data), dtype={"symbol_code": str})
        except Exception as exc:
            raise InputError("CSVを読み取れません。UTF-8の共通形式を確認してください。") from exc
        required = {"symbol_code", "timestamp", "open", "high", "low", "close", "volume", "adjustment_basis"}
        if not required.issubset(frame.columns) or frame.empty:
            raise InputError("CSVの必須列または価格行が不足しています。")
        for key,expected in (("currency","JPY"),("interval","1d")):
            if key in frame and set(frame[key])!={expected}:
                raise InputError("初期版はJPY・確定日足のみです。通貨・時間足を確認してください。")
            if self.metadata.get(key,expected)!=expected:
                raise InputError("初期版はJPY・確定日足のみです。")
            frame[key]=expected
        if "is_closed" in frame and not frame["is_closed"].astype(str).str.lower().isin(["true","1"]).all():
            raise InputError("未確定日足は入力できません。")
        frame["is_closed"]=True
        if set(frame.symbol_code) != {symbol}:
            raise InputError("CSVには分析対象の1銘柄だけを含めてください。")
        if frame["adjustment_basis"].isna().any() or frame["adjustment_basis"].nunique() != 1:
            raise InputError("価格調整基準が混在または欠損しています。")
        for column in ["open", "high", "low", "close", "volume"]:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        if frame[["open", "high", "low", "close", "volume"]].isna().any().any():
            raise InputError("OHLCVの欠損・非数値を0で補完することはできません。")
        import numpy as np
        if not np.isfinite(frame[["open", "high", "low", "close", "volume"]]).all().all():
            raise InputError("無限大は価格に使用できません。")
        if ((frame[["open", "high", "low", "close"]] <= 0).any().any()
                or (frame.volume < 0).any()
                or (frame.high < frame[["open", "close", "low"]].max(axis=1)).any()
                or (frame.low > frame[["open", "close", "high"]].min(axis=1)).any()):
            raise InputError("OHLCの大小関係・価格・出来高を確認してください。")
        frame["timestamp"] = [time_value(str(x)) for x in frame.timestamp]
        if any(x > time_value(as_of) for x in frame.timestamp):
            raise InputError("分析時点より後の価格がCSVに含まれています。")
        distinct=frame[["timestamp"]].drop_duplicates()
        if len({x.astimezone(JST).date() for x in distinct.timestamp})!=len(distinct):
            raise InputError("同じ取引日に複数の日足時刻があります。確定した1本だけを入力してください。")
        findings = []
        duplicates = frame[frame.duplicated("timestamp", keep=False)]
        if not duplicates.empty:
            if any(group[["open","high","low","close","volume"]].drop_duplicates().shape[0] > 1
                   for _, group in duplicates.groupby("timestamp")):
                findings.append(Finding("conflicting_prices", Severity.CRITICAL, "all",
                    "同一日時に矛盾する価格が存在します。", resolution="原資料を確認して競合を解消"))
            else:
                findings.append(Finding("duplicate_rows", Severity.WARNING, "all",
                    "一致する重複行を取り除きました。"))
            frame = frame.drop_duplicates("timestamp", keep="first")
        frame = frame.sort_values("timestamp")
        frame["timestamp"] = [x.isoformat() for x in frame.timestamp]
        evidence = {}
        allowed = {f.name for f in fields(Evidence)}
        for item in self.metadata.get("evidence", []):
            try:
                values = {k: v for k, v in item.items() if k in allowed}
                values["derived_from"] = tuple(values.get("derived_from", []))
                record = Evidence(**values)
                record.validate(as_of)
            except (TypeError, KeyError) as exc:
                raise InputError("Evidenceの形式が不正です。") from exc
            if record.evidence_id in evidence:
                raise InputError("Evidence IDが重複しています。")
            evidence[record.evidence_id] = record
        bars = frame.to_dict("records")
        market_id = "market-" + digest(bars)[:16]
        market = Evidence(market_id, self.metadata.get("price_source", "利用者CSV"),
            "local:prices.csv", bars[-1]["timestamp"], bars[-1]["timestamp"], as_of,
            f"{symbol} 調整基準 {frame.adjustment_basis.iloc[0]} / 日足{len(bars)}行",
            digest(bars), "csv", 0.8)
        market.validate(as_of)
        evidence[market_id] = market
        for record in evidence.values():
            if any(ref not in evidence for ref in record.derived_from):
                raise InputError("Evidenceの派生元が見つかりません。")
        meta = dict(self.metadata, market_evidence_id=market_id)
        return Bundle(symbol, str(meta.get("name", symbol)), as_of, bars, evidence, meta, findings)

def read_metadata(data: bytes) -> dict:
    try:
        obj = json.loads(data.decode("utf-8-sig"))
    except (ValueError, UnicodeError) as exc:
        raise InputError("補足情報JSONを読み取れません。") from exc
    if not isinstance(obj, dict):
        raise InputError("補足情報はJSONオブジェクトです。")
    return obj

class AssessmentProvider(Protocol):
    """Future AI providers must return card anchors and Evidence, not free scores."""
    def assess(self, evidence: dict[str, Evidence], cards: dict, as_of: str) -> list[dict]: ...

def validate_metadata(meta: dict, as_of: str) -> None:
    if not isinstance(meta,dict):
        raise InputError("補足情報はJSONオブジェクトです。")
    for key in ("evidence","assessments","warnings","volume_profile"):
        if not isinstance(meta.get(key,[]),list) or any(not isinstance(x,dict) for x in meta.get(key,[])):
            raise InputError(key+"はオブジェクトの配列です。")
    for key in ("preflight_review","macro","dominant_factor","severe_conditions","evidence_quality"):
        if not isinstance(meta.get(key,{}),dict):
            raise InputError(key+"はオブジェクトです。")
    for key in ("preflight_review","severe_conditions","evidence_quality"):
        if any(not isinstance(v,dict) for v in meta.get(key,{}).values()):
            raise InputError(key+"の各項目はオブジェクトです。")
    sessions=meta.get("calendar",[])
    if not isinstance(sessions,list) or any(not isinstance(x,str) for x in sessions):
        raise InputError("calendarはYYYY-MM-DDの配列です。")
    try:
        if any(date.fromisoformat(x).isoformat()!=x for x in sessions) or len(set(sessions))!=len(sessions):
            raise ValueError()
    except ValueError as exc:
        raise InputError("カレンダーに不正な日付・重複があります。") from exc
    if meta.get("tick_size") is not None:
        try:
            import math
            tick=float(meta["tick_size"])
            if not math.isfinite(tick) or tick<=0:
                raise ValueError()
        except (ValueError,TypeError) as exc:
            raise InputError("呼値は正の有限数です。") from exc
    if meta.get("earnings_at"):
        time_value(meta["earnings_at"])
        refs=meta.get("earnings_evidence_ids",[])
        ids={x.get("evidence_id") for x in meta.get("evidence",[])}
        if not refs or any(x not in ids for x in refs):
            raise InputError("決算予定には存在するEvidenceの参照が必要です。")
    from .scoring import catalog
    cards=catalog()
    if any(x.get("criterion_id") not in cards for x in meta.get("assessments",[])):
        raise InputError("登録されていない採点カードIDです。スイングの採点表を確認してください。")
    for check in meta.get("evidence_quality",{}).values():
        if check.get("valid_until"):
            time_value(check["valid_until"])
    if not isinstance(meta.get("exit_conditions",[]),list):
        raise InputError("撤退条件は文字列の配列です。")
