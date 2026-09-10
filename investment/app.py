"""Streamlit UI for the offline swing vertical slice."""
from pathlib import Path
import copy
import json
import sys
from datetime import datetime, timezone
import pandas as pd
import streamlit as st

sys.path.insert(0,str(Path(__file__).resolve().parent/"src"))
from investment_app.application import analyze
from investment_app.config import PROJECT, data_directory, load_config
from investment_app.logging_setup import setup_logging
from investment_app.models import InputError, canonical, digest, plain, time_value
from investment_app.providers import LocalCSVProvider, read_metadata
from investment_app.scoring import catalog
from investment_app.storage import History

st.set_page_config(page_title="新規銘柄判定 | 投資運用記録",layout="wide")
from investment_app.integration_ui import setup, summary, internal_link, workspace_navigation
setup()
if st.query_params.get("embedded")!="1":
    st.title("新規銘柄判定")
    st.caption("保有する価値と、今の価格で入る価値を分けて確認します。注文は行いません。")
cfg=load_config()
directory=data_directory()
history=History(directory/"history.sqlite")
logger=setup_logging(directory)
workspace_navigation()
if st.query_params.get("workspace")=="validation":
    from investment_app.validation_ui import render_validation
    render_validation(history)
    st.stop()

def fmt(value, suffix=""):
    return "未算出" if value is None else f"{float(value):,.2f}{suffix}"

def render(result: dict, current_hash: str | None = None):
    if result["metadata"].get("is_demo"):
        st.warning("架空テストデータです。実在銘柄・実在株価の評価ではありません。")
    st.subheader(result["name"]+"（"+result["symbol"]+"）")
    st.caption("分析時点："+result["as_of"]+" / 保存された時点の結果")
    choices=list(result["decisions"])
    scenario=st.session_state.get("summary_scenario_"+result["run_id"])
    if scenario not in choices:
        scenario=st.selectbox("比較する価格・決算シナリオ",choices,
            format_func=lambda x:x.replace(":allow"," ／ 決算を跨ぐ").replace(":avoid"," ／ 決算を跨がない"),
            key="view_scenario_"+result["run_id"])
    else:
        st.caption("表示シナリオ："+scenario+"（上段の選択と共通）")
    decision=result["decisions"][scenario]
    kind=scenario.split(":")[0]
    scores=result["scores"][kind]
    plan=next((p for p in result["plans"] if p["kind"]==kind),None)
    label=decision["label"] or "未判定"
    if any(f["severity"]=="Critical" for f in decision["findings"]):
        st.error("評価不能：必須の確認・情報が不足しています。")
    elif decision["approval_required"]:
        st.warning(label)
    else:
        st.info("結論："+label)
    st.write("評価状態："+decision["status"])
    cols=st.columns(4)
    cols[0].metric("投資妙味",fmt(scores["investment"]," / 10"))
    cols[1].metric("Entry品質",fmt(scores["entry"]," / 10"))
    cols[2].metric("データ信頼度",fmt(result["confidence"]["value"]," / 100"))
    cols[3].metric("RR",fmt(plan["rr"]) if plan else "未算出")
    st.caption("構造化評価："+fmt(scores["structured"])+" × 70% ＋ 定性コンテキスト評価："+fmt(scores["context"])+" × 30%")
    st.caption("RRは第1利確までの利益余地 ÷ 第1損切までの距離。スコアとRRだけでは買いを確定しません。")
    if scores["investment"] is None or scores["entry"] is None:
        st.warning("欠損は0点にしていません。未評価カード："+", ".join(scores["missing"]))
    left,right=st.columns(2)
    with left:
        st.markdown("**買う理由**")
        for reason in decision["buy_reasons"]:
            st.write("・"+reason)
        if not decision["buy_reasons"]:
            st.write("根拠未確認")
    with right:
        st.markdown("**待つ理由**")
        for reason in decision["wait_reasons"]:
            st.write("・"+reason)
    st.markdown("**Entry・利確・損切**")
    labels={"entry":"Entry候補","target1":"第1利確","target2":"最終利確","alert":"Alert",
            "stop1":"第1損切","stop2":"最終損切","rr":"RR"}
    table=[{"項目":label,"値":fmt(plan.get(key)) if plan else "未算出"} for key,label in labels.items()]
    st.dataframe(pd.DataFrame(table),hide_index=True,width="stretch")
    st.caption("Alertは再評価を開始する価格です。根拠のない第2価格は未算出のまま表示します。")
    if plan:
        st.write("プラン失効時刻："+plan["expires_at"])
        if datetime.now(timezone.utc)>time_value(plan["expires_at"]):
            st.warning("この価格プランは期限切れです。履歴として表示しています。現在の判断には最新データで再分析してください。")
    comparison=[]
    for p in result["plans"]:
        comparison.append({"プラン":p["kind"],"Entry":float(p["entry"]),"第1利確":float(p["target1"]),
            "第1損切":float(p["stop1"]),"RR":float(p["rr"]),
            "Entry品質":result["scores"][p["kind"]]["entry"],
            "条件":"トリガー確認済み" if p["trigger_confirmed"] else "価格到達・反転・出来高の確認待ち"})
    st.markdown("**今買う vs 待つ**")
    st.dataframe(pd.DataFrame(comparison),hide_index=True,width="stretch")
    st.markdown("**決算情報**")
    earnings=result["earnings"]
    st.write("次回決算："+(earnings["scheduled_at"] or "不明"))
    st.write("残り営業日："+("未算出（カレンダーまたは予定日不足）" if earnings["business_days"] is None else str(earnings["business_days"])))
    st.write("方針："+{"unspecified":"未指定：跨ぐ／跨がないを両方表示","allow":"跨ぐ想定","avoid":"跨がない想定"}[earnings["policy"]])
    st.markdown("**最大懸念**")
    severity_order={"Critical":0,"Severe":1,"Warning":2}
    warnings=sorted(decision["findings"],key=lambda f:severity_order[f["severity"]])
    st.write(warnings[0]["reason"] if warnings else "明示された重大警告なし。未発見のリスクがないことを保証するものではありません。")
    for warning in warnings:
        st.write(f"{warning['severity']}：{warning['reason']}")
        if warning["resolution"]:
            st.caption("確認・解除条件："+warning["resolution"])
    st.markdown("**撤退条件**")
    for condition in result["metadata"]["exit_conditions"]:
        st.write("・"+condition)
    if plan:
        st.write("・"+plan["invalidation"])
    if decision["overrides"]:
        with st.expander("支配的材料・判断上書きの記録",expanded=True):
            st.json(decision["overrides"])
    if decision["approval_required"]:
        st.markdown("**Severeのユーザー判断**")
        st.write("AIの条件候補："+str(decision["candidate"]))
        readonly=current_hash is None or result["metadata"].get("is_demo")
        state=history.approval_state(result["run_id"],scenario,current_hash or "read-only",datetime.now(timezone.utc).isoformat())
        st.write("承認状態："+state)
        if readonly:
            st.caption("保存履歴・架空データは参照表示です。買い承認操作は行いません。")
        else:
            confirmed=st.checkbox("重大警告・残るリスク・この価格プランを確認しました",key="confirm_"+result["run_id"]+scenario)
            a,b=st.columns(2)
            if a.button("この条件で買い判断を承認",disabled=not confirmed or not decision["approval_eligible"],key="approve_"+scenario):
                try:
                    history.approval(result["run_id"],scenario,"approved",result["approval_hash"],current_hash,datetime.now(timezone.utc).isoformat())
                    st.success("買い判断を記録しました。Severe警告は継続します。注文は行っていません。")
                except InputError as exc:
                    st.error(str(exc))
            if b.button("買い判断を承認しない",disabled=not decision["approval_eligible"],key="reject_"+scenario):
                try:
                    history.approval(result["run_id"],scenario,"rejected",result["approval_hash"],current_hash,datetime.now(timezone.utc).isoformat())
                    st.info("拒否を記録しました。元のAI判断は変更していません。")
                except InputError as exc:
                    st.error(str(exc))
    with st.expander("チャート・週足の大局",expanded=True):
        st.write("週足の大局："+result["technical"]["weekly_trend"]+
                 " ／ 確定週足："+str(result["technical"]["weekly_count"])+"本")
        horizon=result["metadata"].get("horizon","swing")
        available=[k for k in ("weekly","monthly","daily") if k in result["technical"]] if horizon=="midlong" else [k for k in ("daily","weekly") if k in result["technical"]]
        interval=st.selectbox("価格の時間軸",available,format_func=lambda k:{"daily":"5分足" if horizon=="daytrade" else "日足","weekly":"週足","monthly":"月足"}[k],key="chart_"+result["run_id"])
        chart=pd.DataFrame(result["technical"][interval])
        if not chart.empty:
            if "timestamp" not in chart: chart=chart.rename(columns={chart.columns[0]:"timestamp"})
            chart["timestamp"]=pd.to_datetime(chart["timestamp"])
            columns=["close"]+[c for c in ("ma13","ma25","ma26","ma50","ma52","ma75") if c in chart]
            st.line_chart(chart.set_index("timestamp")[columns])
        st.write("RSI："+fmt(result["technical"]["rsi"])+" ／ ATR："+fmt(result["technical"]["atr"]))
    with st.expander("マクロの伝播経路"):
        st.json(result["technical"]["macro"])
    with st.expander("採点内訳・Evidence",expanded=False):
        rows=[{"カード":key,"得点":value.get("score"),"理由":value.get("reason"),
               "反証":value.get("counter_reason"),"Evidence":", ".join(value.get("evidence_ids",[])),
               "評価者":value.get("evaluator")} for key,value in scores["items"].items()]
        st.dataframe(pd.DataFrame(rows),hide_index=True,width="stretch")
        st.markdown("**Evidence（根拠）**")
        st.dataframe(pd.DataFrame(list(result["evidence"].values())),hide_index=True,width="stretch")
        st.json(result["confidence"])
    with st.expander("分析履歴と採点規則"):
        st.write("履歴ID："+result["run_id"])
        st.write("採点規則："+result["config_version"])
        st.write("設定ハッシュ："+result["config_hash"])
        st.write("入力データ束："+result["bundle_id"])
        st.write("評価方式：根拠付き採点カード＋プログラム計算。定性AI応答は検査後に取込可能。外部AIへの自動送信は未接続。")
        st.download_button("分析結果JSONを保存",canonical(result),file_name="analysis.json",mime="application/json",key="download_"+result["run_id"])

view_run=st.query_params.get("run")
if view_run:
    try:
        restored=history.get(view_run)
        summary({restored["metadata"].get("horizon","swing"):restored})
        with st.expander("判断理由・採点内訳・Evidence"):
            render(restored)
    except InputError as exc:
        st.error(str(exc))
    internal_link("新しい分析を入力","?workspace=uat")
    st.stop()

if st.query_params.get("workspace")!="legacy":
    from investment_app.uat_ui import render_uat
    render_uat(history,render,logger)
    st.stop()

mode=st.radio("入力方法",["テストデータ（架空1銘柄）","CSV・手動入力"],horizontal=True)
is_demo=mode.startswith("テスト")
if is_demo:
    csv_data=(PROJECT/"data/demo_prices.csv").read_bytes()
    metadata=read_metadata((PROJECT/"data/demo_evidence.json").read_bytes())
    st.warning("テスト専用の架空銘柄です。分析時点は2026-09-09の固定データです。")
    symbol=st.text_input("銘柄コード",value="TEST0001",key="symbol_demo")
    as_of=metadata["as_of"]
else:
    symbol=st.text_input("銘柄コード",key="symbol_manual",placeholder="銘柄コードを文字列で入力")
    as_of=st.text_input("分析時点（タイムゾーン付き）",value=datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"))
    upload=st.file_uploader("日足CSV",type=["csv"])
    supplement=st.file_uploader("補足情報・Evidence・採点カードJSON（任意）",type=["json"])
    csv_data=upload.getvalue() if upload else b""
    metadata={"symbol":symbol,"name":symbol,"evidence":[],"assessments":[],"is_demo":False}
    if supplement:
        try:
            metadata=read_metadata(supplement.getvalue())
        except InputError as exc:
            st.error(str(exc))
    metadata["is_demo"]=False
    with st.expander("入力形式・手動補完"):
        st.write("CSV列：symbol_code, timestamp, open, high, low, close, volume, adjustment_basis")
        st.write("OHLCは始値・高値・安値・終値です。日時には +09:00 等のタイムゾーンを付けます。")
        st.write("補足情報がなくても読み込めますが、未確認項目は暫定／評価不能となり、点数を補いません。")
        text=st.text_area("補足情報JSONを手動で編集",value=json.dumps(metadata,ensure_ascii=False,indent=2),height=240)
        try:
            metadata=read_metadata(text.encode("utf-8"))
            metadata["is_demo"]=False
        except InputError as exc:
            st.error(str(exc))
            metadata={"symbol":symbol,"name":symbol,"evidence":[],"assessments":[],"is_demo":False}
entry_text=st.text_input("想定Entry価格（任意）",placeholder="空欄ならCSVの最新価格")
policy_label=st.selectbox("決算跨ぎ方針",["未指定（両シナリオ）","跨ぐ","跨がない"])
policy={"未指定（両シナリオ）":"unspecified","跨ぐ":"allow","跨がない":"avoid"}[policy_label]
request_hash=digest({"csv":digest(csv_data.hex()),"metadata":metadata,"symbol":symbol,"as_of":as_of,
                     "entry":entry_text,"policy":policy,"config":cfg})
if st.button("分析する",type="primary"):
    if not csv_data:
        st.error("CSVを入力してください。")
    else:
        try:
            with st.spinner("根拠・価格構造・スコアを確認しています…"):
                bundle=LocalCSVProvider(csv_data,metadata).fetch(symbol.strip(),as_of)
                out=analyze(bundle,cfg,entry_text.strip() or None,policy)
                history.save(out,bundle,cfg)
                st.session_state["result"]=plain(out)
                st.session_state["request_hash"]=request_hash
                logger.info("analysis_completed run_id=%s",out.run_id)
        except InputError as exc:
            st.error(str(exc))
            logger.warning("input_validation_failed")
        except Exception as exc:
            logger.error("analysis_failed kind=%s",type(exc).__name__)
            history.failure(type(exc).__name__)
            st.error("分析処理に失敗しました。入力形式とローカルログを確認してください。")
if "result" in st.session_state:
    same=request_hash==st.session_state.get("request_hash")
    if not same:
        st.warning("入力が変わっています。表示は変更前の結果です。再分析してください。以前の承認は流用できません。")
    render(st.session_state["result"],st.session_state["result"]["approval_hash"] if same else "changed")
with st.expander("保存した分析履歴"):
    for run in history.list_runs(10):
        internal_link(run["symbol"]+" / "+run["as_of"],"?run="+run["run_id"])
