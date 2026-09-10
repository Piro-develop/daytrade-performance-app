"""Practical offline validation workspace."""
from datetime import datetime, timezone
import json
import pandas as pd
import streamlit as st
from .config import PROJECT
from .integration_ui import internal_link
from .manual_input import AUTO_CARDS, build_metadata, card_template, csv_table, normalize_csv, readiness, refs
from .models import InputError, canonical, digest, plain
from .providers import LocalCSVProvider, read_metadata
from .scoring import catalog
from .validation import ValidationStore, JUDGMENTS, CATEGORIES

def table_rows(frame):
    return frame.fillna("").to_dict("records")

def safe_action(action):
    try:
        return action()
    except (InputError,ValueError,KeyError,TypeError) as exc:
        st.error(str(exc))
        return None

def evidence_seed(meta):
    rows=[]
    for ev in meta.get("evidence",[]):
        q=meta.get("evidence_quality",{}).get(ev["evidence_id"],{})
        rows.append({**{k:ev.get(k,"") for k in ("evidence_id","source_name","source_uri","observed_at",
            "published_at","fetched_at","summary","fact_or_interpretation")},
            "valid_until":q.get("valid_until",""),"source_quality":q.get("source_quality","unknown")})
    return rows or [{k:"" for k in ("evidence_id","source_name","source_uri","observed_at","published_at",
        "fetched_at","summary","fact_or_interpretation","valid_until","source_quality")}]

def input_page(store,gid,group):
    st.subheader("1. 実銘柄の入力を保存")
    st.caption("価格・根拠・採点を保存します。この段階ではアプリのスコアや結論を表示しません。")
    uploaded=st.file_uploader("日足CSV（UTF-8 / CP932）",type=["csv"],key="prices_"+gid)
    supplement=st.file_uploader("既存の補足JSONを読み込む（任意）",type=["json"],key="supplement_"+gid)
    meta=safe_action(lambda:read_metadata(supplement.getvalue())) if supplement else {}
    meta=meta or {}
    prefix=gid+digest(meta)[:8]
    symbol=st.text_input("実銘柄コード",value=meta.get("symbol",""),key="symbol_"+prefix)
    name=st.text_input("会社名",value=meta.get("name",""),key="name_"+prefix)
    source=st.text_input("価格の出所・取得元",value=meta.get("price_source",""),key="source_"+prefix)
    adjustment=st.text_input("価格調整基準（銘柄列・基準列がCSVにない場合）",
        value="",placeholder="出所で確認した調整方法",key="adjustment_"+prefix)
    close_time=st.text_input("日付しかないCSVの確定時刻（任意・HH:MM）",value="",
        help="原資料で全入力期間の確定時刻を確認した場合だけ指定。空欄から時刻を推測しません。",key="closetime_"+prefix)
    confirmed=st.checkbox("CSVの銘柄・確定日足・価格調整基準と、指定した日時変換を確認しました",key="confirm_"+prefix)
    with st.expander("根拠（Evidence）を入力",expanded=True):
        st.caption("日時は +09:00 等の時差付き。summaryに原資料のページ・該当箇所と事実を記載。空行は未入力です。")
        evfile=st.file_uploader("Evidence CSVを読み込む（任意）",type=["csv"],key="evfile_"+prefix)
        seed=safe_action(lambda:csv_table(evfile.getvalue())) if evfile else evidence_seed(meta)
        evdf=st.data_editor(pd.DataFrame(seed or evidence_seed({})),num_rows="dynamic",hide_index=True,
            key="evidence_"+prefix, width="stretch",
            column_config={"source_quality":st.column_config.SelectboxColumn(options=["unknown","original_verified","secondary_verified","image_verified"]),
                "fact_or_interpretation":st.column_config.SelectboxColumn(options=["fact","interpretation","hypothesis"])})
    evidence_rows=table_rows(evdf)
    ids=[r["evidence_id"] for r in evidence_rows if r.get("evidence_id")]
    with st.expander("構造化・定性コンテキストの採点カード",expanded=False):
        st.caption("未評価から開始します。未取得を中立点にしません。プログラム計算の8カードは入力対象外です。")
        cardfile=st.file_uploader("採点カードCSVを読み込む（任意）",type=["csv"],key="cardfile_"+prefix)
        seed=card_template()
        for row in seed:
            existing=next((a for a in meta.get("assessments",[]) if a["criterion_id"]==row["criterion_id"]),None)
            if existing:
                row.update(anchor=str(existing["anchor"]),evidence_ids=",".join(existing["evidence_ids"]),
                    reason=existing["reason"],counter_reason=existing["counter_reason"])
        if cardfile:
            supplied=safe_action(lambda:csv_table(cardfile.getvalue()))
            if supplied is not None:
                seed=supplied
        carddf=st.data_editor(pd.DataFrame(seed),hide_index=True,key="cards_"+prefix,width="stretch",
            disabled=["criterion_id","項目"],column_config={"anchor":st.column_config.SelectboxColumn(options=["未評価","1","4","6","8","10"])})
        code=st.selectbox("アンカーの説明を確認",list(catalog()),format_func=lambda c:catalog()[c]["label"],key="cardhelp_"+prefix)
        st.write("必要な根拠："+catalog()[code]["evidence"])
        st.table(pd.DataFrame([{"アンカー":k,"基準":v} for k,v in catalog()[code]["anchors"].items()]))
    with st.expander("Preflight・イベント・マクロ・価格の補足",expanded=False):
        reviews={}
        for key,label in [("negative_news","重大悪材料"),("thesis","投資前提"),("liquidity","流動性")]:
            old=meta.get("preflight_review",{}).get(key,{})
            reviewed=st.checkbox(label+"を独立に確認した",value=bool(old.get("reviewed")),key=key+prefix)
            selected=st.multiselect(label+"の根拠ID",ids,default=[r for r in old.get("evidence_ids",[]) if r in ids],key="refs_"+key+prefix)
            reviews[key]={"reviewed":reviewed,"evidence_ids":selected}
        tick=st.text_input("検証済み呼値（空欄なら未設定）",value=str(meta.get("tick_size") or ""),key="tick_"+prefix)
        tickref=st.selectbox("呼値の根拠",[""]+ids,index=([""]+ids).index(meta.get("tick_evidence_id","")) if meta.get("tick_evidence_id","") in [""]+ids else 0,key="tickref_"+prefix)
        earnings=st.text_input("次回決算の発表日時（不明は空欄）",value=meta.get("earnings_at") or "",key="earnings_"+prefix)
        earningsrefs=st.multiselect("決算予定の根拠",ids,default=[r for r in meta.get("earnings_evidence_ids",[]) if r in ids],key="earningsrefs_"+prefix)
        calendar=st.text_area("公式取引カレンダー：取引日を1行ずつ YYYY-MM-DD",value="\n".join(meta.get("calendar",[])),key="calendar_"+prefix)
        calendar_source=st.text_input("カレンダーの出所・版",value=meta.get("calendar_note",""),key="calsource_"+prefix)
        macro={}
        labels={"sector":"セクター","sector_condition":"セクターの状況","drivers":"主要ドライバー",
            "company_sensitivity":"企業の感応度","specific_factors":"個別材料との強弱比較","dominant_force":"支配する要因・理由"}
        for key,label in labels.items():
            value=meta.get("macro",{}).get(key,"")
            macro[key]=st.text_area(label,value=value if isinstance(value,str) else json.dumps(value,ensure_ascii=False),key="macro_"+key+prefix)
        macro["evidence_ids"]=st.multiselect("マクロ伝播の根拠",ids,default=[r for r in meta.get("macro",{}).get("evidence_ids",[]) if r in ids],key="macrorefs_"+prefix)
        exits=st.text_area("価格以外の撤退条件（1行ずつ）",value="\n".join(meta.get("exit_conditions",[])),key="exits_"+prefix)
        warnings_seed=[dict(w,evidence_ids=",".join(w.get("evidence_ids",[]))) for w in meta.get("warnings",[])]
        warningdf=st.data_editor(pd.DataFrame(warnings_seed or [{"code":"","severity":"","scope":"decision","reason":"","evidence_ids":"","resolution":""}]),
            num_rows="dynamic",hide_index=True,key="warnings_"+prefix,
            column_config={"severity":st.column_config.SelectboxColumn(options=["Critical","Severe","Warning"]),
                "scope":st.column_config.SelectboxColumn(options=["all","investment","entry","decision"])})
        st.caption("支配的材料・Severe条件・実測出来高分布の詳細は、既存補足JSONがあれば保持します。")
    reason=st.text_input("同じ銘柄を訂正する場合の理由",key="revision_"+prefix)
    base=dict(meta,symbol=symbol.strip(),name=name.strip(),price_source=source.strip(),preflight_review=reviews,
        earnings_at=earnings.strip() or None,earnings_evidence_ids=earningsrefs,tick_evidence_id=tickref,
        calendar=[x.strip() for x in calendar.splitlines() if x.strip()],calendar_note=calendar_source,
        macro=macro,exit_conditions=[x.strip() for x in exits.splitlines() if x.strip()])
    base["warnings"]=[dict(r,evidence_ids=refs(r.get("evidence_ids"))) for r in table_rows(warningdf) if r.get("code") or r.get("severity")]
    if tick.strip():
        base["tick_size"]=tick.strip()
    else:
        base.pop("tick_size",None)
    def prepare():
        if not uploaded or not confirmed or not source.strip() or not symbol.strip() or not name.strip():
            raise InputError("CSV・銘柄・会社名・出所・日足確認を入力してください。")
        if base["calendar"] and not calendar_source.strip():
            raise InputError("カレンダーの出所・版を入力してください。")
        content,origin=normalize_csv(uploaded.getvalue(),symbol.strip(),adjustment,confirmed,close_time.strip() or None)
        prepared=build_metadata(base,evidence_rows,table_rows(carddf))
        prepared["import_provenance"]=origin
        bundle=LocalCSVProvider(content,prepared).fetch(symbol.strip(),group["as_of"])
        return content,prepared,bundle
    if st.button("入力の不足・形式を確認",key="validate_"+prefix):
        ready=safe_action(prepare)
        if ready:
            st.dataframe(pd.DataFrame(readiness(ready[2])),hide_index=True)
            st.success("形式検査完了。不足は表示のまま保持します。まだ分析していません。")
    if st.button("この入力を凍結保存",key="savecase_"+prefix,type="primary"):
        ready=safe_action(prepare)
        if ready:
            cid=safe_action(lambda:store.save_case(gid,ready[0],ready[1],reason))
            if cid:
                st.success("入力を保存しました。次に「2. 人間評価」を開いてください。")
                st.code(cid)

def human_page(store,gid,cases):
    st.subheader("2. アプリ結果を見る前の人間評価")
    if not cases:
        st.info("先に銘柄入力を保存してください。");return
    cid=st.selectbox("評価する銘柄",[c["case_id"] for c in cases],format_func=lambda cid:next(c["symbol"] for c in cases if c["case_id"]==cid),key="human_case")
    bundle=store.bundle(cid)
    if store.run(cid):
        st.warning("この入力は分析済みです。独立評価は追加できません。差分確認を使用してください。");return
    st.caption("同じ資料を使って判断します。可能なら採点カード入力者とは別の人が評価してください。")
    with st.expander("凍結した原データ・Evidence（アプリ結果なし）"):
        st.dataframe(pd.DataFrame(bundle.bars).tail(80),hide_index=True)
        st.dataframe(pd.DataFrame([plain(e) for e in bundle.evidence.values()]),hide_index=True)
    scenario=st.selectbox("比較する決算シナリオ",["allow","avoid"],format_func=lambda x:"跨ぐ" if x=="allow" else "跨がない",key="human_scenario")
    st.write("保存済みシナリオ："+", ".join(x["scenario"] for x in store.baselines(cid)))
    with st.form("baseline_"+cid+scenario):
        reviewer=st.text_input("評価者名")
        judgment=st.selectbox("人間の最終判断",JUDGMENTS,index=None,placeholder="選択してください")
        severe=st.checkbox("Severe警告付きの判断")
        approval=st.selectbox("想定する承認状態",["not_requested","pending"],format_func=lambda x:"未要求" if x=="not_requested" else "ユーザー承認待ち")
        reasons=st.text_area("主要理由（1〜3行）")
        counter=st.text_area("主要な反証・最大懸念")
        evidence=st.multiselect("判断根拠のEvidence",list(bundle.evidence))
        st.caption("点数・順位・価格は任意。同順位は同じ数値、比較不能は空欄。RRは価格から計算します。")
        values={}
        for key,label in [("investment","人間の投資妙味（0〜10）"),("entry_score","人間のEntry品質（0〜10）"),
                          ("investment_rank","投資妙味順位"),("entry_rank","現在のEntry候補順位"),
                          ("entry","人間Entry"),("target1","人間の第1利確"),("target2","人間の最終利確"),
                          ("stop1","人間の第1損切"),("stop2","人間の最終損切")]:
            values[key]=st.text_input(label)
        independent=st.checkbox("この入力のアプリ結果を見る前に、自分の判断を記録しました")
        submitted=st.form_submit_button("独立した人間評価を保存")
    if submitted:
        data=dict(values,reviewer=reviewer,decision=judgment,severe=severe,approval_state=approval,
            reasons=reasons.splitlines(),counter_reason=counter,evidence_ids=evidence)
        if safe_action(lambda:store.save_baseline(cid,scenario,data,independent)):
            st.success("人間評価を保存しました。比較するもう一方のシナリオがあれば、分析前に保存してください。")

def analysis_page(store,gid,cases):
    st.subheader("3. 保存済み入力をまとめて分析")
    st.write(f"登録：{len(cases)}銘柄 / 比較目安5〜10銘柄。同じ銘柄の訂正版は最新1件だけを対象にします。")
    if st.button("人間評価保存済みの銘柄を分析",type="primary"):
        for case in cases:
            if not store.baselines(case["case_id"]):
                st.warning(case["symbol"]+"：独立した人間評価待ち");continue
            with st.spinner(case["symbol"]+"を分析"):
                out=safe_action(lambda:store.analyze_case(case["case_id"]))
                if out:
                    st.success(case["symbol"]+"：分析保存済み")
    rows=[]
    for case in cases:
        result=store.run(case["case_id"])
        rows.append({"銘柄":case["symbol"],"状態":"分析済み" if result else "人間評価保存済み" if store.baselines(case["case_id"]) else "人間評価待ち"})
        if result:
            internal_link(case["symbol"]+"の採点・Evidence・価格を開く","?run="+result["run_id"])
    st.dataframe(pd.DataFrame(rows),hide_index=True)

def difference_page(store,gid):
    st.subheader("4. 人間評価との差分を確認")
    scenario=st.selectbox("比較シナリオ",["allow","avoid"],format_func=lambda x:"跨ぐ" if x=="allow" else "跨がない",key="diffscenario")
    report=store.report(gid,scenario)
    paired=[r for r in report["rows"] if "judgment_match" in r]
    m=report["metrics"]
    def percent(value):
        return "未算出" if value is None else f"{value:.0%}"
    st.write("検証状態："+m["status"])
    st.dataframe(pd.DataFrame([
        {"項目":"登録銘柄数","結果":str(m["distinct_symbols"])},
        {"項目":"比較済み銘柄数","結果":str(m["compared"])},
        {"項目":"差分確認がまだの銘柄数","結果":str(m["unreviewed"])},
        {"項目":"最終判断の一致率","結果":percent(m["judgment_agreement"])},
        {"項目":"主要理由の一致率","結果":percent(m["major_reason_agreement"])},
        {"項目":"確認済みの未解消重大不一致","結果":str(m["unresolved_critical"])},
        {"項目":"投資妙味の順位整合","結果":percent(m["investment_rank"]["concordance"])},
        {"項目":"Entry候補の順位整合","結果":percent(m["entry_rank"]["concordance"])}
    ]),hide_index=True)
    with st.expander("順位の対象・同順位・比較基準"):
        st.json(m)
    if report["proposals"]:
        st.write("差分に基づく確認・修正候補（未採用）")
        st.dataframe(pd.DataFrame(report["proposals"]),hide_index=True)
    st.caption("判断・順位・主要理由を優先します。点差は補助指標で、合否の足切りには使いません。")
    rows=[]
    for row in paired:
        p=row["plan"];s=row["score"]
        rows.append({"銘柄":row["symbol"],"投資妙味":s["investment"],"Entry品質":s["entry"],
            "Entry":p.get("entry"),"第1利確":p.get("target1"),"最終利確":p.get("target2"),
            "第1損切":p.get("stop1"),"最終損切":p.get("stop2"),"RR":p.get("rr"),
            "アプリ判断":row["app_decision"],"人間判断":row["human"]["decision"],
            "判断一致":row["judgment_match"],"投資妙味の点差":row["investment_delta"],"Entry品質の点差":row["entry_delta"]})
    st.dataframe(pd.DataFrame(rows),hide_index=True)
    st.download_button("比較表CSVを保存",pd.DataFrame(rows).to_csv(index=False).encode("utf-8-sig"),"validation_summary.csv","text/csv")
    st.download_button("根拠・人間評価・差分を含むJSON",canonical(report),"validation_report.json","application/json")
    if not paired:
        st.info("人間評価とアプリ分析が揃うと比較できます。実銘柄の妥当性検証はまだ完了していません。");return
    symbol=st.selectbox("差分を記録する銘柄",[r["symbol"] for r in paired],key="diffsymbol")
    row=next(r for r in paired if r["symbol"]==symbol)
    internal_link("アプリの採点内訳・Evidenceを開く","?run="+row["run_id"])
    with st.expander("人間評価とアプリの価格・判断根拠",expanded=True):
        st.json({"人間":row["human"],"アプリ価格":row["plan"],"アプリ判断":row["decision"]})
        st.dataframe(pd.DataFrame(list(row["result"]["evidence"].values())),hide_index=True)
    with st.form("difference_"+row["human"]["baseline_id"]):
        different=st.checkbox("差分がある",value=not row["judgment_match"])
        categories=st.multiselect("差分原因（複数選択可）",CATEGORIES)
        reason_count=st.number_input("人間の主要理由のうち一致した数",0,len(row["human"]["reasons"]),0,1)
        counter=st.checkbox("主要な反証がアプリ側でも保持されている")
        critical=st.checkbox("重大不一致（Critical無視・未承認買い・重大悪材料見落とし・根拠捏造等）")
        note=st.text_area("差分の具体例・Evidence・原因・修正案")
        resolved=st.checkbox("解消を確認した")
        resolution=st.text_area("解消根拠・再確認結果（解消済みの場合）")
        submitted=st.form_submit_button("差分確認を追記保存")
    if submitted:
        data={"has_difference":different,"categories":categories,"reason_match_count":int(reason_count),
            "counter_evidence_preserved":counter,"critical_issue":critical,"note":note,
            "resolved":resolved,"resolution":resolution}
        if safe_action(lambda:store.save_difference(row["human"]["baseline_id"],row["run_id"],data)):
            st.success("差分を追記しました。元の採点・人間評価・判断は変更していません。")

def render_validation(history):
    store=ValidationStore(history)
    st.header("実銘柄検証")
    st.info("外部接続なし。まず5銘柄を同じ時点・資料条件で比較します。実データ未入力を架空値で補いません。")
    with st.expander("準備するデータ・テンプレート",expanded=True):
        st.write("同時点の5〜10銘柄、確定日足、公式財務・材料・需給・比較資料、呼値・取引カレンダーを用意します。")
        st.write("詳細は docs/REAL_DATA_VALIDATION_GUIDE.md。スコアの完全一致ではなく判断・順位・理由を比較します。")
        packet=PROJECT/"data/validation_templates.zip"
        if packet.exists():
            st.download_button("空の入力テンプレート一式をダウンロード",packet.read_bytes(),"validation_templates.zip","application/zip")
    with st.expander("検証グループを作る",expanded=not bool(store.groups())):
        with st.form("new_validation_group"):
            name=st.text_input("グループ名",placeholder="例：初回スイング検証")
            asof=st.text_input("共通の分析時点（時差付き）",placeholder="YYYY-MM-DDT16:00:00+09:00")
            submitted=st.form_submit_button("検証グループを作成")
        if submitted and safe_action(lambda:store.create_group(name,asof)):
            st.rerun()
    groups=store.groups()
    if not groups:
        st.info("検証グループは未登録です。データの準備後に作成してください。");return
    gid=st.selectbox("検証グループ",[g["group_id"] for g in groups],format_func=lambda g:next(x["name"] for x in groups if x["group_id"]==g),key="validation_group")
    group=store.group(gid)
    if group["is_test"]:
        st.warning("このグループは架空データの機能試験用です。実銘柄検証の成績に含めません。")
    st.caption("固定した分析時点："+group["as_of"]+" / 規則："+group["config"]["config_version"])
    cases=store.cases(gid)
    step=st.radio("作業",["1. 銘柄入力","2. 人間評価","3. 分析","4. 差分確認"],horizontal=True)
    if step.startswith("1"): input_page(store,gid,group)
    elif step.startswith("2"): human_page(store,gid,cases)
    elif step.startswith("3"): analysis_page(store,gid,cases)
    else: difference_page(store,gid)
