from __future__ import annotations
from pathlib import Path
import copy
import json
import os
from .models import InputError, digest

PROJECT = Path(__file__).resolve().parents[2]

def load_config(path: str | Path | None = None) -> dict:
    try:
        cfg = json.loads(Path(path or PROJECT / "config/default.json").read_text(encoding="utf-8"))
        validate_config(cfg)
    except (ValueError,TypeError,KeyError,OSError) as exc:
        raise InputError("設定ファイルを読み込めません。型・範囲・重みを確認してください。") from exc
    catalog = json.loads((PROJECT / "config/scoring_cards.json").read_text(encoding="utf-8"))
    cfg["card_catalog_hash"] = digest(catalog)
    return cfg

def validate_config(cfg: dict) -> None:
    for key in ("investment_weights", "entry_weights"):
        weights = cfg[key]
        if sum(weights.values()) != 100 or any(not isinstance(v, (int, float)) or v <= 0 for v in weights.values()):
            raise InputError("配点合計は100、各配点は正数である必要があります。")
    if cfg["mix"] != [1, 0]:
        raise InputError("投資妙味は構造化評価のみ。定性評価は独立した補足です。")
    if not 0 < cfg["coverage_min"] <= cfg["coverage_normal"] <= 1:
        raise InputError("coverage閾値は0超〜1の昇順で指定してください。")
    for key in ("rr_knots", "upside_knots"):
        points = cfg[key]
        if any(points[i][0] >= points[i+1][0] or points[i][1] > points[i+1][1] for i in range(len(points)-1)):
            raise InputError("補間節点が不正です。")
    if cfg["anchors"] != [1, 4, 6, 8, 10]:
        raise InputError("採点アンカーが正本と一致しません。")
    if cfg["rr_good"] != 2 or cfg["rr_conditional"] != 1.5:
        raise InputError("RR区分は確定要件です。")
    for key in ("atr_period", "rsi_period", "bb_period", "pivot_span", "strong_band"):
        if not isinstance(cfg[key], (int, float)) or cfg[key] <= 0:
            raise InputError("技術設定は正数が必要です。")
    import math
    def numbers(value):
        if isinstance(value,dict):
            for v in value.values(): yield from numbers(v)
        elif isinstance(value,list):
            for v in value: yield from numbers(v)
        elif isinstance(value,(int,float)):
            yield value
    if any(not math.isfinite(x) for x in numbers(cfg)):
        raise InputError("設定値にNaN・無限大は使えません。")
    for values in cfg["subweights"].values():
        if len(values)!=4 or sum(values)!=100 or min(values)<=0:
            raise InputError("下位カードの重み合計は100です。")
    if set(cfg["investment_weights"])!=set("ABCDEFGHIJ") or set(cfg["entry_weights"])!=set("ABCDEFG"):
        raise InputError("配点の参照カードが正本と一致しません。")
    for key in ("daily_ma","weekly_ma"):
        if not cfg[key] or any(not isinstance(p,int) or isinstance(p,bool) or p<=0 for p in cfg[key]):
            raise InputError("移動平均の期間は正の整数です。")
    if cfg["rsi_method"]!="rolling_simple":
        raise InputError("この版のRSIはrolling_simple方式です。")
    return None

def config_identity(cfg: dict) -> tuple[str, str]:
    return cfg["config_version"], digest(cfg)

def data_directory() -> Path:
    override = os.environ.get("INVESTMENT_APP_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local/share"))
    return base / "DaytradePerformanceUAT"
