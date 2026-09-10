"""Tracker-facing presentation only; engines, prices and scores remain unchanged."""
import html
import json
from datetime import datetime, timezone
from pathlib import Path
import streamlit as st
from .models import time_value, canonical
from .uat_service import recommendation

LABELS={"swing":"スイング","midlong":"中長期","daytrade":"デイトレ"}

def fmt(value):
    return "未算出" if value is None else f"{float(value):,.2f}"

def setup():
    st.markdown("""<style>
    header[data-testid="stHeader"]{display:none}
    .workspace-nav{display:flex;gap:10px;margin:4px 0 12px}
    .workspace-nav a{padding:10px 16px;border:1px solid #365343;border-radius:8px;min-height:44px;box-sizing:border-box;text-decoration:none;color:#7cdbac}
    .internal-nav{display:inline-block;min-height:44px;padding:10px 4px;line-height:1.5}
    .block-container [data-testid="stVerticalBlock"]{gap:.7rem}
    .block-container{padding:1rem 1.1rem 2rem;max-width:1280px}
    .decision-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;margin:12px 0}
    .decision-cell{border:1px solid #365343;background:#10231a;border-radius:10px;padding:12px;min-width:0}
    .decision-cell span{display:block;font-size:12px;color:#b6c9bd;margin-bottom:5px}
    .decision-cell strong{font-size:20px;overflow-wrap:anywhere}
    .decision-conclusion{border-left:4px solid #7cdbac;background:#10231a;padding:14px;border-radius:6px}
    .decision-conclusion h3{margin:0;font-size:22px}
    .decision-concern{padding:12px;background:#32261c;border-radius:8px;overflow-wrap:anywhere}
    @media(max-width:640px){
      .block-container{padding:.65rem .65rem 1.5rem}
      .decision-grid{grid-template-columns:repeat(2,minmax(0,1fr))}
      .decision-cell{padding:10px}.decision-cell strong{font-size:19px}
      h1{font-size:1.65rem!important}h2{font-size:1.3rem!important}
      [data-testid="stTextInput"] input{font-size:16px}
      [data-testid="stButton"] button{min-height:44px}
    }</style>""",unsafe_allow_html=True)
    if st.query_params.get("embedded") != "1":
        st.markdown('<a href="/" target="_self">← 運用成績トラッカーへ戻る</a>',unsafe_allow_html=True)

def selected_result(results,horizon,scenario,now=None,stale=False):
    now=now or datetime.now(timezone.utc)
    result=results[horizon]
    decision=result["decisions"][scenario]
    kind=scenario.split(":")[0]
    score=result["scores"][kind]
    plan=next((p for p in result["plans"] if p["kind"]==kind),None)
    expired=bool(plan and time_value(plan["expires_at"])<now)
    findings=sorted(decision["findings"],key=lambda f:{"Critical":0,"Severe":1,"Warning":2}[f["severity"]])
    critical=any(f["severity"]=="Critical" for f in findings)
    label=decision["label"] or "未判定"
    if critical: label="評価不能"
    if stale: label+="（入力変更前の結果）"
    elif expired: label+="（期限切れ・履歴）"
    daily=result["technical"].get("daily") or [{}]
    return {
      "analysis_id":result["run_id"], "label":label,"status":decision["status"],
      "investment":score["investment"],"entry_quality":score["entry"],
      "current":result["technical"].get("latest",daily[-1].get("close")),
      "plan":plan,"findings":findings,"expired":expired,
      "concern":findings[0]["reason"] if findings else
          (decision["wait_reasons"][0] if decision["wait_reasons"] else "明示された重大警告なし。原資料で確認してください。"),
      "approval_required":decision["approval_required"],
      "can_recommend":not (stale or expired or critical or decision["approval_required"]) and
          decision["status"]=="評価可能" and kind=="現値" and label in ("買い","条件付き買い","打診買い")
    }

def summary(results,stale=False):
    top=st.container()
    h=st.radio("表示する時間軸",list(results),format_func=lambda x:LABELS[x],horizontal=True,key="uat_detail")
    result=results[h]
    scenarios=list(result["decisions"])
    scenario=st.selectbox("表示するEntry・決算シナリオ",scenarios,
        format_func=lambda x:x.replace(":avoid"," ／ 決算を跨がない").replace(":allow"," ／ 決算を跨ぐ"),
        key="summary_scenario_"+result["run_id"])
    view=selected_result(results,h,scenario,stale=stale)
    plan=view["plan"] or {}
    preferred=[] if stale else recommendation(results)
    with top:
        st.subheader("判定サマリ")
        st.markdown('<section class="decision-conclusion"><small>結論 · '+html.escape(LABELS[h]+" / "+view["status"])+'</small><h3>'+
                    html.escape(view["label"])+'</h3></section>',unsafe_allow_html=True)
        st.caption(("架空UATデータ · " if result["metadata"].get("is_demo") else "")+result["name"]+" / "+result["symbol"])
        st.write("推奨時間軸："+("・".join(LABELS[x] for x in preferred)+"（条件確認後の候補）" if preferred else "未推奨／条件・データ補完待ち"))
        if view["approval_required"]:
            st.warning("Severe：重大警告付き条件判断。詳細で条件確認・ユーザー承認が必要です。")
        values=[("投資妙味",view["investment"]),("Entry品質",view["entry_quality"]),
                ("現在値（分析時点）",view["current"]),("Entry候補",plan.get("entry")),
                ("第1利確",plan.get("target1")),("最終利確",plan.get("target2")),
                ("Alert",plan.get("alert")),("第1損切",plan.get("stop1")),
                ("最終損切",plan.get("stop2")),("RR",plan.get("rr"))]
        st.markdown('<div class="decision-grid">'+''.join('<div class="decision-cell"><span>'+
            html.escape(label)+'</span><strong>'+fmt(value)+'</strong></div>' for label,value in values)+'</div>',unsafe_allow_html=True)
        st.markdown('<div class="decision-concern"><strong>最大懸念</strong><br>'+
                    html.escape(view["concern"])+'</div>',unsafe_allow_html=True)
        notes=[]
        if result["metadata"].get("is_demo"): notes.append("架空データ。実在銘柄の判断には使えません。")
        if view["expired"]: notes.append("期限切れの価格は履歴です。最新データで再分析してください。")
        if notes: st.warning(" ".join(notes))
        st.caption("分析時点 "+result["as_of"]+" · 価格は円、スコアは10点満点")
        st.caption("Entryは比較用候補。RR＝第1利確までの利益余地 ÷ 第1損切までの距離。Alertは再評価の目安。")
    st.caption("分析ID："+view["analysis_id"])
    with st.expander("他の時間軸・警告一覧"):
        for other,r in results.items():
            other_view=selected_result(results,other,next(iter(r["decisions"])),stale=stale)
            st.write(LABELS[other]+"："+other_view["label"])
        for finding in view["findings"]:
            st.write(finding["severity"]+"："+finding["reason"])
    packet={"schema_version":1,"analysis_id":result["run_id"],"symbol":result["symbol"],
            "horizon":h,"scenario":scenario,"plan_id":plan.get("plan_id"),
            "as_of":result["as_of"],"rule_version":result["config_version"],
            "approval_hash":result["approval_hash"],"is_demo":result["metadata"].get("is_demo",False),
            "trade_id":None,"result":result}
    st.download_button("売買との比較用に判定を保存（JSON）",canonical(packet),
                       file_name="analysis-link-"+result["run_id"]+".json",mime="application/json")

@st.cache_data
def securities():
    path=Path(__file__).resolve().parents[3]/"stocks.json"
    return json.loads(path.read_text(encoding="utf-8"))["securities"]

def symbol_input():
    query=st.text_input("銘柄コード・銘柄名で検索",placeholder="例：7203、トヨタ")
    matches=[s for s in securities() if query.strip() and
             (query.strip().casefold() in str(s["code"]).casefold() or query.strip() in s["name"])][:30]
    selected=st.selectbox("トラッカーの銘柄一覧",[""]+[s["code"] for s in matches],
        format_func=lambda code:next((s["code"]+" "+s["name"] for s in matches if s["code"]==code),"手動で指定"))
    item=next((s for s in matches if s["code"]==selected),None)
    if item:
        return str(item["code"]),item["name"]
    return st.text_input("銘柄コード",placeholder="例：7203"),st.text_input("銘柄名（任意）")

def internal_link(label, query):
    """Keep internal navigation inside the tracker frame and on its base path."""
    from urllib.parse import parse_qsl, urlencode
    values=dict(parse_qsl(query.lstrip("?")))
    if st.query_params.get("embedded")=="1":
        values["embed"]="true"
        values["embedded"]="1"
    st.markdown('<a class="internal-nav" href="?'+html.escape(urlencode(values))+
                '" target="_self">'+html.escape(label)+'</a>',unsafe_allow_html=True)

def workspace_navigation():
    suffix="&amp;embed=true&amp;embedded=1" if st.query_params.get("embedded")=="1" else ""
    st.markdown('<nav class="workspace-nav" aria-label="判定メニュー">'
                '<a aria-label="新規判定・3時間軸" href="?workspace=uat'+suffix+'" target="_self">新規判定</a>'
                '<a aria-label="実銘柄検証（入力・人間比較）" href="?workspace=validation'+suffix+
                '" target="_self">実銘柄検証</a></nav>',unsafe_allow_html=True)
