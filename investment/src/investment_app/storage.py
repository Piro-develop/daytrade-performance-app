"""Local append-only analysis history; approvals never alter AI decisions."""
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
import json
import sqlite3
import uuid
from contextlib import contextmanager
from .models import AnalysisResult, Bundle, InputError, canonical, plain, time_value

def validate_approval(result, scenario, action, target_hash, current_hash, now):
    if action not in {"approved", "rejected"}:
        raise InputError("承認または拒否の明示操作が必要です。")
    decision = result["decisions"].get(scenario, {})
    if not decision.get("approval_required") or not decision.get("approval_eligible"):
        raise InputError("根拠・価格プラン・評価が成立したSevere条件判断だけを承認できます。")
    if target_hash != result["approval_hash"] or current_hash != target_hash:
        raise InputError("承認対象が変わりました。再分析して確認してください。")
    plan = next((p for p in result["plans"] if p["kind"] == scenario.split(":")[0]), None)
    if plan is None or time_value(now) > time_value(plan["expires_at"]):
        raise InputError("価格プランの有効期限が切れています。")
    if any(x["severity"] == "Critical" for x in decision["findings"]):
        raise InputError("Criticalを承認で解除できません。")

class History:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            if db.execute("PRAGMA user_version").fetchone()[0] not in (0,1):
                raise InputError("この版が対応していないDB形式です。既存DBは変更しません。")
            db.executescript("""
            CREATE TABLE IF NOT EXISTS runs(
                run_id TEXT PRIMARY KEY, created_at TEXT NOT NULL, symbol TEXT NOT NULL,
                as_of TEXT NOT NULL, config_hash TEXT NOT NULL, approval_hash TEXT NOT NULL,
                payload TEXT NOT NULL, snapshot TEXT NOT NULL, config TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS evidence(
                run_id TEXT NOT NULL REFERENCES runs(run_id), evidence_id TEXT NOT NULL,
                payload TEXT NOT NULL, PRIMARY KEY(run_id,evidence_id));
            CREATE TABLE IF NOT EXISTS approvals(
                approval_id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(run_id),
                scenario TEXT NOT NULL, status TEXT NOT NULL, target_hash TEXT NOT NULL,
                user_id TEXT NOT NULL, decided_at TEXT NOT NULL, reason TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS failures(
                failure_id TEXT PRIMARY KEY, created_at TEXT NOT NULL, kind TEXT NOT NULL);
            """)
            db.execute("PRAGMA user_version=1")
    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def save(self, result: AnalysisResult, bundle: Bundle, config: dict) -> None:
        refs = {ref for plan in result.plans for ref in plan.evidence_ids}
        refs |= {ref for decision in result.decisions.values() for ref in decision.evidence_ids}
        if not refs.issubset(result.evidence):
            raise InputError("保存対象のEvidence参照が欠落しています。")
        with self.connect() as db:
            db.execute("INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?)",
                (result.run_id, datetime.now(timezone.utc).isoformat(), result.symbol,
                 result.as_of, result.config_hash, result.approval_hash, canonical(result),
                 canonical(bundle), canonical(config)))
            db.executemany("INSERT INTO evidence VALUES (?,?,?)",
                [(result.run_id, key, canonical(value)) for key, value in result.evidence.items()])

    def list_runs(self, limit: int = 30) -> list[dict]:
        with self.connect() as db:
            rows = db.execute("SELECT run_id,symbol,as_of FROM runs ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [dict(zip(("run_id","symbol","as_of"), row)) for row in rows]

    def get(self, run_id: str) -> dict:
        with self.connect() as db:
            row = db.execute("SELECT payload FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            raise InputError("分析履歴が見つかりません。")
        return json.loads(row[0])

    def approval(self, run_id: str, scenario: str, action: str, target_hash: str,
                 current_hash: str, now: str, user_id: str = "local_user") -> str:
        validate_approval(self.get(run_id), scenario, action, target_hash, current_hash, now)
        with self.connect() as db:
            db.execute("INSERT INTO approvals VALUES (?,?,?,?,?,?,?,?)",
                (str(uuid.uuid4()), run_id, scenario, action, target_hash, user_id, now,
                 "利用者の明示操作。注文は実行しない"))
        return action

    def approval_state(self, run_id: str, scenario: str, current_hash: str, now: str) -> str:
        result = self.get(run_id)
        decision=result["decisions"].get(scenario,{})
        if not decision.get("approval_required") or not decision.get("approval_eligible"):
            return "not_requested"
        if current_hash != result["approval_hash"]:
            return "expired"
        plan = next((p for p in result["plans"] if p["kind"] == scenario.split(":")[0]), None)
        if plan is None or time_value(now) > time_value(plan["expires_at"]):
            return "expired"
        with self.connect() as db:
            row = db.execute("SELECT status FROM approvals WHERE run_id=? AND scenario=? ORDER BY rowid DESC LIMIT 1",
                             (run_id, scenario)).fetchone()
        return row[0] if row else "pending"

    def failure(self, kind: str) -> None:
        with self.connect() as db:
            db.execute("INSERT INTO failures VALUES(?,?,?)",
                       (str(uuid.uuid4()), datetime.now(timezone.utc).isoformat(), kind))
