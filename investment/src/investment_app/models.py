"""Immutable evidence, configuration identity and safe JSON serialization."""
from __future__ import annotations
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from enum import StrEnum
import hashlib
import json
import math
import numpy as np
from typing import Any

JST = timezone(timedelta(hours=9))

class InputError(ValueError):
    """利用者へ安全に表示できる入力エラー。"""

class EvaluationStatus(StrEnum):
    EVALUABLE = "評価可能"
    PROVISIONAL = "暫定評価"
    UNAVAILABLE = "評価不能"

class Severity(StrEnum):
    CRITICAL = "Critical"
    SEVERE = "Severe"
    WARNING = "Warning"

def time_value(value: str | datetime) -> datetime:
    try:
        result = value if isinstance(value, datetime) else datetime.fromisoformat(value)
        if result.tzinfo is None:
            raise ValueError("timezone")
        return result.astimezone(timezone.utc)
    except (ValueError, TypeError) as exc:
        raise InputError("日時にはタイムゾーン（例 +09:00）が必要です。") from exc

def plain(value: Any) -> Any:
    if isinstance(value, np.generic):
        return plain(value.item())
    if is_dataclass(value):
        return plain(asdict(value))
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value

def canonical(value: Any) -> str:
    return json.dumps(plain(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)

def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()

@dataclass(frozen=True)
class Evidence:
    evidence_id: str
    source_name: str
    source_uri: str
    observed_at: str
    published_at: str
    fetched_at: str
    summary: str
    content_hash: str
    source_type: str = "manual"
    confidence: float = 0.5
    derived_from: tuple[str, ...] = ()
    fact_or_interpretation: str = "fact"

    def validate(self, as_of: str) -> None:
        if not all((self.evidence_id, self.source_name, self.source_uri, self.summary, self.content_hash)):
            raise InputError("Evidenceの出所・内容・ハッシュが不足しています。")
        for value in (self.observed_at, self.published_at, self.fetched_at):
            time_value(value)
        if time_value(self.published_at) > time_value(as_of):
            raise InputError("分析時点より後に公表されたEvidenceは採用できません。")
        if time_value(self.observed_at) > time_value(as_of):
            raise InputError("分析時点より後の観測値は採用できません。")
        if not 0 <= self.confidence <= 1:
            raise InputError("Evidence信頼度は0〜1です。")

@dataclass(frozen=True)
class Finding:
    code: str
    severity: Severity
    scope: str
    reason: str
    evidence_ids: tuple[str, ...] = ()
    resolution: str = ""

@dataclass(frozen=True)
class Assessment:
    criterion_id: str
    anchor: int
    evidence_ids: tuple[str, ...]
    reason: str
    counter_reason: str
    evaluator: str = "human"

@dataclass
class Bundle:
    symbol: str
    name: str
    as_of: str
    bars: list[dict]
    evidence: dict[str, Evidence]
    metadata: dict
    findings: list[Finding] = field(default_factory=list)

    @property
    def bundle_id(self) -> str:
        return digest({"symbol": self.symbol, "as_of": self.as_of, "bars": self.bars,
                       "evidence": {k:v for k,v in self.evidence.items() if v.source_type != "calculation"}, "metadata": self.metadata})

@dataclass(frozen=True)
class Band:
    band_id: str
    low: float
    high: float
    strength: float
    families: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    primary: bool
    reactions: int

@dataclass(frozen=True)
class EntryPlan:
    plan_id: str
    kind: str
    entry: Decimal
    target1: Decimal
    stop1: Decimal
    rr: Decimal
    target2: Decimal | None
    stop2: Decimal | None
    alert: Decimal | None
    support_id: str
    resistance_id: str
    evidence_ids: tuple[str, ...]
    invalidation: str
    expires_at: str
    trigger_confirmed: bool
    rr_reason: str = ""

@dataclass
class ScoreResult:
    structured: float | None
    context: float | None
    investment: float | None
    entry: float | None
    status: EvaluationStatus
    entry_status: EvaluationStatus
    items: dict
    missing: list[str]
    coverage: float

@dataclass
class Decision:
    label: str | None
    status: EvaluationStatus
    candidate: str | None
    buy_reasons: list[str]
    wait_reasons: list[str]
    findings: list[Finding]
    overrides: list[dict]
    evidence_ids: list[str]
    approval_required: bool = False
    approval_eligible: bool = False

@dataclass
class AnalysisResult:
    run_id: str
    bundle_id: str
    as_of: str
    symbol: str
    name: str
    config_version: str
    config_hash: str
    evidence: dict
    technical: dict
    plans: list[EntryPlan]
    scores: dict[str, ScoreResult]
    decisions: dict[str, Decision]
    earnings: dict
    confidence: dict
    metadata: dict
    findings: list[Finding]
    approval_hash: str = ""
