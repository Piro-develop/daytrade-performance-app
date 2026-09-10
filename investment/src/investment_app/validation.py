"""Frozen real-symbol cohorts, independent human baselines and adjudicated differences."""
from datetime import datetime, timezone
from decimal import Decimal
from itertools import combinations
import json
import uuid
from .application import analyze
from .config import PROJECT, load_config
from .entry_exit import rr
from .models import InputError, canonical, digest, plain, time_value
from .providers import LocalCSVProvider
from .storage import History

CATEGORIES=("データ不足","採点基準","支持抵抗判定","RR","定性評価","Decision Engine")
JUDGMENTS=("今買う","条件付き","待つ","見送り","評価不能","暫定評価")

def policy():
    return json.loads((PROJECT/"config/validation.json").read_text(encoding="utf-8"))

def now():
    return datetime.now(timezone.utc).isoformat()

def checked_number(value, lower=0, upper=None):
    if value is None or str(value).strip()=="":
        return None
    try:
        number=Decimal(str(value))
        if not number.is_finite() or number<lower or (upper is not None and number>upper):
            raise ValueError()
        return float(number)
    except Exception as exc:
        raise InputError("数値の範囲・空欄を確認してください。") from exc

def human_values(data: dict, evidence: dict) -> dict:
    out=dict(data)
    if data.get("decision") not in JUDGMENTS or not str(data.get("reviewer","")).strip():
        raise InputError("評価者と人間の判断を入力してください。")
    reasons=[str(x).strip() for x in data.get("reasons",[]) if str(x).strip()]
    if not 1<=len(reasons)<=3 or not str(data.get("counter_reason","")).strip():
        raise InputError("主要理由1〜3件と主要反証を入力してください。")
    refs=data.get("evidence_ids",[])
    if not refs or any(r not in evidence for r in refs):
        raise InputError("人間評価には今回の入力に含まれるEvidenceが必要です。")
    out["reasons"]=reasons
    for key in ("investment","entry_score"):
        out[key]=checked_number(data.get(key),0,10)
    for key in ("investment_rank","entry_rank"):
        out[key]=checked_number(data.get(key),1)
        if out[key] is not None and not out[key].is_integer():
            raise InputError("順位は整数、同順位は同じ数値、比較不可は空欄です。")
    for key in ("entry","target1","target2","stop1","stop2"):
        out[key]=checked_number(data.get(key),0)
        if out[key]==0:
            raise InputError("価格は正数または空欄です。")
    out["rr"]=None
    if all(out[k] is not None for k in ("entry","target1","stop1")):
        value=rr(out["entry"],out["target1"],out["stop1"])
        if value is None:
            raise InputError("人間プランも 第1損切 < Entry < 第1利確 が必要です。")
        out["rr"]=str(value)
    if out["target2"] is not None and out["target1"] is not None and out["target2"]<out["target1"]:
        raise InputError("最終利確は第1利確以上です。")
    if out["stop2"] is not None and out["stop1"] is not None and out["stop2"]>=out["stop1"]:
        raise InputError("最終損切は第1損切未満です。")
    out["severe"]=bool(data.get("severe"))
    if data.get("approval_state","not_requested") not in {"not_requested","pending"}:
        raise InputError("比較前の承認状態は未要求または承認待ちです。")
    out["approval_state"]=data.get("approval_state","not_requested")
    if out["approval_state"]=="pending" and not out["severe"]:
        raise InputError("承認待ちはSevere条件判断にだけ指定できます。")
    return out

class ValidationStore:
    def __init__(self, history: History):
        self.history=history
        with history.connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS validation_groups(
                group_id TEXT PRIMARY KEY, name TEXT NOT NULL, as_of TEXT NOT NULL,
                config TEXT NOT NULL, is_test INTEGER NOT NULL, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS validation_cases(
                case_id TEXT PRIMARY KEY, group_id TEXT NOT NULL REFERENCES validation_groups(group_id),
                symbol TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS validation_baselines(
                baseline_id TEXT PRIMARY KEY, case_id TEXT NOT NULL REFERENCES validation_cases(case_id),
                scenario TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL,
                UNIQUE(case_id,scenario));
            CREATE TABLE IF NOT EXISTS validation_analyses(
                case_id TEXT PRIMARY KEY REFERENCES validation_cases(case_id),
                run_id TEXT NOT NULL REFERENCES runs(run_id), created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS validation_differences(
                difference_id TEXT PRIMARY KEY, baseline_id TEXT NOT NULL REFERENCES validation_baselines(baseline_id),
                run_id TEXT NOT NULL REFERENCES runs(run_id), payload TEXT NOT NULL, created_at TEXT NOT NULL);
            """)

    def create_group(self,name,as_of,is_test=False):
        if not str(name).strip():
            raise InputError("検証グループ名を入力してください。")
        time_value(as_of)
        gid=str(uuid.uuid4())
        with self.history.connect() as db:
            db.execute("INSERT INTO validation_groups VALUES(?,?,?,?,?,?)",
                (gid,name,time_value(as_of).isoformat(),canonical(load_config()),int(is_test),now()))
        return gid

    def groups(self):
        with self.history.connect() as db:
            rows=db.execute("SELECT group_id,name,as_of,is_test FROM validation_groups ORDER BY rowid DESC").fetchall()
        return [dict(zip(("group_id","name","as_of","is_test"),r)) for r in rows]

    def group(self,gid):
        with self.history.connect() as db:
            row=db.execute("SELECT name,as_of,config,is_test FROM validation_groups WHERE group_id=?",(gid,)).fetchone()
        if row is None:
            raise InputError("検証グループが見つかりません。")
        return dict(zip(("name","as_of","config","is_test"),(row[0],row[1],json.loads(row[2]),bool(row[3]))))

    def cases(self,gid):
        with self.history.connect() as db:
            rows=db.execute("SELECT case_id,symbol,payload FROM validation_cases WHERE group_id=? ORDER BY rowid",(gid,)).fetchall()
        latest={}
        for cid,symbol,payload in rows:
            latest[symbol]=dict(json.loads(payload),case_id=cid,symbol=symbol)
        return list(latest.values())

    def case(self,cid):
        with self.history.connect() as db:
            row=db.execute("SELECT payload FROM validation_cases WHERE case_id=?",(cid,)).fetchone()
        if row is None:
            raise InputError("検証入力が見つかりません。")
        return dict(json.loads(row[0]),case_id=cid)

    def save_case(self,gid,csv_data,metadata,revision_reason=""):
        group=self.group(gid)
        symbol=str(metadata.get("symbol","")).strip()
        bundle=LocalCSVProvider(csv_data,metadata).fetch(symbol,group["as_of"])
        if not group["is_test"] and (metadata.get("is_demo") or any(e.source_type=="fixture" or
            e.source_uri.startswith("fixture:") for e in bundle.evidence.values()) or
            any("synthetic" in str(bar.get("adjustment_basis","")).lower() for bar in bundle.bars)):
            raise InputError("架空データを実銘柄検証に混ぜることはできません。")
        existing=self.cases(gid)
        if symbol not in {c["symbol"] for c in existing} and len(existing)>=policy()["max_symbols"]:
            raise InputError("1グループは10銘柄までです。")
        previous=next((c for c in existing if c["symbol"]==symbol),None)
        if previous and not str(revision_reason).strip():
            raise InputError("同じ銘柄の再登録には訂正理由が必要です。旧入力・評価は保存します。")
        cid=str(uuid.uuid4())
        payload={"group_id":gid,"symbol":symbol,"metadata":metadata,"csv":csv_data.decode("utf-8-sig"),
                 "bundle_id":bundle.bundle_id,"revision_reason":revision_reason,
                 "supersedes":previous["case_id"] if previous else None}
        with self.history.connect() as db:
            db.execute("INSERT INTO validation_cases VALUES(?,?,?,?,?)",(cid,gid,symbol,canonical(payload),now()))
        return cid

    def bundle(self,cid):
        case=self.case(cid)
        group=self.group(case["group_id"])
        bundle=LocalCSVProvider(case["csv"].encode("utf-8"),case["metadata"]).fetch(case["symbol"],group["as_of"])
        if bundle.bundle_id!=case["bundle_id"]:
            raise InputError("凍結入力と再構成データが一致しません。")
        return bundle

    def baselines(self,cid):
        with self.history.connect() as db:
            rows=db.execute("SELECT baseline_id,scenario,payload FROM validation_baselines WHERE case_id=? ORDER BY rowid",(cid,)).fetchall()
        return [dict(json.loads(p),baseline_id=i,scenario=s) for i,s,p in rows]

    def save_baseline(self,cid,scenario,data,independent):
        if scenario not in {"allow","avoid"} or independent is not True:
            raise InputError("決算シナリオと、結果を見る前に評価したことの確認が必要です。")
        values=human_values(data,self.bundle(cid).evidence)
        bid=str(uuid.uuid4())
        with self.history.connect() as db:
            if db.execute("SELECT 1 FROM validation_analyses WHERE case_id=?",(cid,)).fetchone():
                raise InputError("分析後に独立評価を追加できません。事後の差分確認に記録してください。")
            if db.execute("SELECT 1 FROM validation_baselines WHERE case_id=? AND scenario=?",(cid,scenario)).fetchone():
                raise InputError("独立評価は保存済みです。訂正は入力の新版として残してください。")
            values.update(independent=True,bundle_id=self.case(cid)["bundle_id"])
            db.execute("INSERT INTO validation_baselines VALUES(?,?,?,?,?)",(bid,cid,scenario,canonical(values),now()))
        return bid

    def run(self,cid):
        with self.history.connect() as db:
            row=db.execute("SELECT run_id FROM validation_analyses WHERE case_id=?",(cid,)).fetchone()
        return self.history.get(row[0]) if row else None

    def analyze_case(self,cid):
        existing=self.run(cid)
        if existing:
            return existing
        if not self.baselines(cid):
            raise InputError("先にアプリ結果を見ずに人間評価を保存してください。")
        case=self.case(cid);group=self.group(case["group_id"])
        cfg=group["config"]
        if cfg["card_catalog_hash"]!=load_config()["card_catalog_hash"]:
            raise InputError("採点カードが変更されています。新しい検証グループを作成してください。")
        bundle=self.bundle(cid)
        result=analyze(bundle,cfg,earnings_policy="unspecified")
        self.history.save(result,bundle,cfg)
        with self.history.connect() as db:
            db.execute("INSERT INTO validation_analyses VALUES(?,?,?)",(cid,result.run_id,now()))
        return plain(result)

    def save_difference(self,bid,run_id,data):
        with self.history.connect() as db:
            row=db.execute("SELECT case_id,payload,scenario FROM validation_baselines WHERE baseline_id=?",(bid,)).fetchone()
        if row is None:
            raise InputError("比較する人間評価がありません。")
        result=self.run(row[0])
        if not result or result["run_id"]!=run_id:
            raise InputError("異なる入力・分析との比較はできません。")
        human=json.loads(row[1])
        candidate=next(v for k,v in result["decisions"].items() if k.endswith(":"+row[2]))
        mechanical=(decision_group(candidate)!=human["decision"] or bool(candidate["approval_required"])!=human["severe"] or
            ("pending" if candidate["approval_eligible"] else "not_requested")!=human["approval_state"])
        data=dict(data,has_difference=bool(data.get("has_difference") or mechanical))
        count=data.get("reason_match_count")
        if isinstance(count,bool) or not isinstance(count,int) or not 0<=count<=len(human["reasons"]):
            raise InputError("主要理由の一致数を確認してください。")
        categories=data.get("categories",[])
        if any(c not in CATEGORIES for c in categories) or not str(data.get("note","")).strip():
            raise InputError("差分分類と確認メモを入力してください。")
        if data.get("has_difference") and not categories:
            raise InputError("差分がある場合は6分類から原因を選んでください。")
        if data.get("critical_issue") and not categories:
            raise InputError("重大不一致には差分分類が必要です。")
        if data.get("resolved") and not str(data.get("resolution","")).strip():
            raise InputError("解消済みには確認根拠が必要です。")
        did=str(uuid.uuid4())
        with self.history.connect() as db:
            db.execute("INSERT INTO validation_differences VALUES(?,?,?,?,?)",
                (did,bid,run_id,canonical(data),now()))
        return did

    def latest_difference(self,bid):
        with self.history.connect() as db:
            row=db.execute("SELECT payload FROM validation_differences WHERE baseline_id=? ORDER BY rowid DESC LIMIT 1",(bid,)).fetchone()
        return json.loads(row[0]) if row else None

    def report(self,gid,scenario="allow"):
        group=self.group(gid);rows=[]
        for case in self.cases(gid):
            out=self.run(case["case_id"])
            human=next((b for b in self.baselines(case["case_id"]) if b["scenario"]==scenario),None)
            row={"symbol":case["symbol"],"case_id":case["case_id"],"run_id":out["run_id"] if out else None,
                 "human":human,"result":out,"difference":self.latest_difference(human["baseline_id"]) if human else None}
            if out and human:
                key=next((k for k in out["decisions"] if k.endswith(":"+scenario) and k.startswith("現値:")),None)
                key=key or next(k for k in out["decisions"] if k.endswith(":"+scenario))
                decision=out["decisions"][key];score=out["scores"][key.split(":")[0]]
                plan=next((p for p in out["plans"] if p["kind"]==key.split(":")[0]),{})
                coarse=decision_group(decision)
                row.update(app_decision=coarse,decision=decision,score=score,plan=plan,
                    judgment_match=(coarse==human["decision"] and bool(decision["approval_required"])==human["severe"]
                        and ("pending" if decision["approval_eligible"] else "not_requested")==human["approval_state"]),
                    investment_delta=None if score["investment"] is None or human["investment"] is None else score["investment"]-human["investment"],
                    entry_delta=None if score["entry"] is None or human["entry_score"] is None else score["entry"]-human["entry_score"])
            rows.append(row)
        suggestions=[]
        guidance={"データ不足":"資料・日時・不足カードを補完して同じ規則で再分析",
            "採点基準":"アンカーの解釈と必要Evidenceを正本13と照合",
            "支持抵抗判定":"採用帯・手前抵抗・週足優先・独立系統を原チャートと照合",
            "RR":"実支持の損切を固定し、Entryと第1利確・呼値・計算を確認",
            "定性評価":"個別とマクロの支配関係・作用時期・反証を確認",
            "Decision Engine":"警告・トリガー・例外・承認の適用順を確認"}
        for category in CATEGORIES:
            affected=[r["symbol"] for r in rows if r["difference"] and category in r["difference"].get("categories",[])
                      and not r["difference"].get("resolved")]
            if affected:
                suggestions.append({"category":category,"symbols":affected,"proposal":guidance[category],
                    "status":"要調査。規則・正本は自動変更しない"})
        return {"group":group,"scenario":scenario,"rows":rows,"metrics":metrics(rows,group["is_test"]),
                "proposals":suggestions}

def decision_group(decision):
    if decision["status"]=="評価不能":
        return "評価不能"
    if decision["status"]=="暫定評価":
        return "暫定評価"
    label=decision["candidate"] if decision["approval_required"] else decision["label"]
    if label in ("強気買い","買い"):
        return "今買う"
    if label in ("条件付き買い","打診買い"):
        return "条件付き"
    if label in ("押し目待ち","反転確認","ブレイク確認"):
        return "待つ"
    return "見送り" if label=="見送り" else "暫定評価"

def rank_metrics(rows, score_key, human_rank):
    candidates=[r for r in rows if r.get("score",{}).get(score_key) is not None and
        r["score"]["status" if score_key=="investment" else "entry_status"]=="評価可能" and
        r["human"].get(human_rank) is not None and
        (score_key=="investment" or (r["app_decision"] in ("今買う","条件付き") and
         not r["decision"]["approval_required"]))]
    if len(candidates)<5:
        return {"n":len(candidates),"concordance":None,"top3_overlap":None,"note":"比較可能な5銘柄が必要"}
    def order_key(row):
        if score_key=="investment": return (row["score"]["investment"],)
        return (row["score"]["investment"],row["score"]["entry"],row["result"]["confidence"]["value"])
    concordant=0;count=0
    for a,b in combinations(candidates,2):
        h=a["human"][human_rank]-b["human"][human_rank]
        if h==0:
            continue
        ka,kb=order_key(a),order_key(b)
        delta=(ka>kb)-(ka<kb)
        count+=1
        concordant+=int(h*delta<0)
    if count==0:
        return {"n":len(candidates),"concordance":None,"top3_overlap":None,"note":"人間評価が全同順位"}
    app_cut=sorted([order_key(r) for r in candidates],reverse=True)[2]
    human_cut=sorted([r["human"][human_rank] for r in candidates])[2]
    app_top={r["symbol"] for r in candidates if order_key(r)>=app_cut}
    human_top={r["symbol"] for r in candidates if r["human"][human_rank]<=human_cut}
    return {"n":len(candidates),"concordance":concordant/count,"pairs":count,
            "top3_overlap":len(app_top&human_top),"app_top":sorted(app_top),"human_top":sorted(human_top)}

def metrics(rows,is_test):
    compared=[r for r in rows if "judgment_match" in r]
    reviewed=[r for r in compared if r["difference"]]
    reasons=[]
    for row in reviewed:
        d=row["difference"];required=1 if len(row["human"]["reasons"])==1 else 2
        reasons.append(d["reason_match_count"]>=required and d.get("counter_evidence_preserved") is True)
    critical=sum(bool(r["difference"].get("critical_issue") and not r["difference"].get("resolved")) for r in reviewed)
    return {"distinct_symbols":len(rows),"compared":len(compared),"reviewed":len(reviewed),
        "judgment_agreement":sum(r["judgment_match"] for r in compared)/len(compared) if compared else None,
        "major_reason_agreement":sum(reasons)/len(reasons) if reasons else None,
        "unresolved_critical":critical,"unreviewed":len(rows)-len(reviewed),"investment_rank":rank_metrics(compared,"investment","investment_rank"),
        "entry_rank":rank_metrics(compared,"entry","entry_rank"),
        "status":"架空データの機能試験" if is_test else "実銘柄検証未実施" if not compared else
            "確認未完了" if len(compared)<5 or len(reviewed)<len(rows) else "比較記録済み（人間による総合判定が必要）",
        "thresholds":policy(),"score_difference_is_pass_fail":False}
