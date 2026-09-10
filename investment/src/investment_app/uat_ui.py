"""Practical multi-horizon UAT workspace, with manual-first evidence review."""
import copy
import json
from datetime import datetime,timezone
from io import BytesIO
from pathlib import Path
import pandas as pd
import streamlit as st
from .config import PROJECT,data_directory
from .models import InputError,canonical,digest,plain,time_value
from .manual_input import normalize_csv,build_metadata,refs,AUTO_CARDS
from .validation_ui import evidence_seed,table_rows
from .uat_service import demo,bundle_from_input,run_all,recommendation
from .horizons import all_cards
from .public_data import StooqMarketProvider,PublicContextProvider
from .provider_registry import require_available
from .ai_bridge import export_request,import_response

LABELS={"swing":"スイング","midlong":"中長期","daytrade":"デイトレ"}
AUTO=AUTO_CARDS|{"ME-E","DE-C"}
def show_error(exc):
    st.error(str(exc) if isinstance(exc,InputError) else "入力形式または処理を確認してください。詳しくはローカルログに記録します。")
from .integration_ui import summary, symbol_input, internal_link

def set_work(csv,meta):
    for key in list(st.session_state):
        if key.startswith(("uat_evidence","uat_cards_","uat_pf_","uat_macro_","uat_ai_","uat_image_")) or key in ("uat_warnings","uat_results","uat_result_input"):
            del st.session_state[key]
    st.session_state.uat_work={"csv":csv,"meta":meta}

def load_input():
    if "uat_work" not in st.session_state:
        csv,meta=demo();st.session_state.uat_work={"csv":csv,"meta":meta}
    with st.expander("銘柄・データ入力",expanded=False):
        mode=st.radio("データの入口",["無料公開日足","CSV・表入力","開発用データ"],index=2,horizontal=True)
        if mode=="開発用データ":
            st.caption("固定日時の架空銘柄。実際の投資判断には使用しません。")
            if st.button("開発用データを読み込む"):
                csv,meta=demo();set_work(csv,meta);st.rerun()
            return
        symbol,name=symbol_input()
        asof=st.text_input("分析日時",value=datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"))
        supplement=st.file_uploader("保存済み補足情報JSON（任意）",type=["json"],key="uat_supp")
        adjustment=st.text_input("確認した価格調整基準",placeholder="例：株式分割調整済み／未調整")
        close_time=st.text_input("日付だけのデータに付ける確定時刻",value="15:30")
        confirmed=st.checkbox("銘柄・調整基準・対象期間の確定時刻を原資料で確認した")
        raw=b""
        if mode=="CSV・表入力":
            upload=st.file_uploader("日足CSV（UTF-8／CP932）",type=["csv"],key="uat_prices")
            if upload: raw=upload.getvalue()
            else:
                st.caption("CSVがない場合の貼付用。date,open,high,low,close,volume。中長期は月足24本を作れる履歴が必要です。")
                frame=st.data_editor(pd.DataFrame(columns=["date","open","high","low","close","volume"]),num_rows="dynamic",key="uat_price_table")
                if not frame.empty: raw=frame.to_csv(index=False).encode()
        else:
            st.caption("Stooqの無料公開日足。取得不可時はCSVで補完。調整基準を自動推測しません。")
            start=st.date_input("開始日",value=datetime(2022,1,1).date())
            if st.button("無料日足を取得"):
                try:
                    require_available("stooq")
                    result=StooqMarketProvider().fetch(symbol,str(start),asof[:10])
                    st.session_state.uat_download={"symbol":symbol,**result}
                    st.success("取得しました。調整基準等を確認して下の「入力を読み込む」を押してください。")
                except InputError as exc: st.error(str(exc))
            fetched=st.session_state.get("uat_download")
            if fetched and fetched["symbol"]==symbol:
                raw=fetched["csv"]
                st.caption(fetched["note"]+" / 取得日時："+fetched["fetched_at"])
                st.download_button("取得CSVを保存",raw,file_name="public_daily.csv")
        if st.button("入力を読み込む",type="primary"):
            try:
                if not raw: raise InputError("価格データがありません。")
                meta=json.loads(supplement.getvalue().decode("utf-8-sig")) if supplement else {}
                if not isinstance(meta,dict): raise InputError("補足情報はJSONオブジェクトです。")
                if meta.get("symbol") and str(meta["symbol"])!=symbol: raise InputError("補足情報の銘柄が一致しません。")
                normalized,provenance=normalize_csv(raw,symbol,adjustment,confirmed,close_time)
                meta.update(symbol=symbol,name=name or symbol,as_of=asof,is_demo=False,input_normalization=provenance)
                if mode=="無料公開日足":
                    meta.update(price_source="Stooq公開日足",public_download={k:v for k,v in st.session_state.uat_download.items() if k!="csv"})
                bundle_from_input(normalized,meta,symbol,asof)
                set_work(normalized,meta)
                st.session_state.pop("uat_results",None);st.rerun()
            except (InputError,ValueError,TypeError) as exc: st.error(str(exc))

def edit_metadata(base):
    meta=copy.deepcopy(base)
    with st.expander("Evidence・確認資料を追加／編集"):
        st.caption("Evidenceは判断根拠。資料日時、出典、該当箇所の要約、有効期限を記入します。未確認は未評価のまま残します。")
        rows=st.data_editor(pd.DataFrame(evidence_seed(meta)),num_rows="dynamic",key="uat_evidence")
        with st.popover("スクリーンショットを根拠に追加"):
            image=st.file_uploader("画像（口座情報を含めない）",type=["png","jpg","jpeg"],key="uat_image")
            title=st.text_input("画像の出典",key="uat_image_title")
            stamp=st.text_input("画像で確認した情報日時",value=meta["as_of"],key="uat_image_time")
            note=st.text_area("目視で確認した内容・該当箇所",key="uat_image_note")
            checked=st.checkbox("数値・銘柄・日時を目視確認した",key="uat_image_check")
            if st.button("画像を判定履歴の保存先へ追加"):
                try:
                    if not image or not title or not note or not checked: raise InputError("画像・出典・確認内容・目視確認が必要です。")
                    from PIL import Image
                    raw=image.getvalue()
                    if len(raw)>10_000_000: raise InputError("画像は10MB以内です。")
                    Image.open(BytesIO(raw)).verify()
                    from .models import Evidence
                    key="image-"+digest(raw.hex())[:20]
                    folder=data_directory()/"attachments";folder.mkdir(exist_ok=True)
                    path=folder/(key+Path(image.name).suffix.lower())
                    ev=Evidence(key,title,str(path),stamp,stamp,meta["as_of"],note,digest(raw.hex()),"image",.5)
                    ev.validate(meta["as_of"]);path.write_bytes(raw)
                    current_rows=table_rows(rows)
                    refreshed=build_metadata(meta,current_rows,[],cards=all_cards())
                    refreshed["assessments"]=meta.get("assessments",[])
                    refreshed["is_demo"]=meta.get("is_demo",False)
                    if ev.evidence_id not in {e["evidence_id"] for e in refreshed["evidence"]}:
                        refreshed["evidence"].append(plain(ev))
                    st.session_state.uat_work["meta"]=refreshed
                    st.session_state.pop("uat_evidence",None)
                    st.rerun()
                except Exception as exc: show_error(exc)
        evrows=table_rows(rows)
    with st.expander("採点カード（時間軸別・Evidenceと理由が必須）"):
        h=st.selectbox("編集する時間軸",list(LABELS),format_func=lambda h:LABELS[h],key="uat_card_h")
        prefixes={"swing":("SW-","SE-","SC-"),"midlong":("ML-","ME-","MC-"),"daytrade":("DT-","DE-","DC-")}[h]
        old={r["criterion_id"]:r for r in meta.get("assessments",[])}
        cards={k:v for k,v in all_cards().items() if k.startswith(prefixes) and k not in AUTO}
        values=[]
        for code,card in cards.items():
            r=old.get(code,{})
            values.append({"criterion_id":code,"項目":card["label"],"anchor":str(r.get("anchor","未評価")),
                "evidence_ids":",".join(r.get("evidence_ids",[])),"reason":r.get("reason",""),"counter_reason":r.get("counter_reason","")})
        edited=st.data_editor(pd.DataFrame(values),hide_index=True,disabled=["criterion_id","項目"],
            column_config={"anchor":st.column_config.SelectboxColumn("評価アンカー",options=["未評価","1","4","6","8","10"])},key="uat_cards_"+h)
        code=st.selectbox("採点基準を確認",list(cards),format_func=lambda c:c+" "+cards[c]["label"])
        st.write("必要根拠："+cards[code]["required_evidence"])
        st.json(cards[code]["anchors"],expanded=False)
        cardrows=table_rows(edited)
        # Only this horizon's edited cards replace previous entries.
        retained=[r for r in meta.get("assessments",[]) if r["criterion_id"] not in cards]
    meta=build_metadata(meta,evrows,cardrows,cards=all_cards())
    for row in meta["assessments"]:
        original=next((r for r in base.get("assessments",[]) if r["criterion_id"]==row["criterion_id"]),{})
        if all(row.get(k)==original.get(k) for k in ("anchor","reason","counter_reason","evidence_ids")):
            row.update({k:original[k] for k in ("evaluator","request_id") if k in original})
    meta["assessments"]=retained+meta["assessments"];meta["is_demo"]=base.get("is_demo",False)
    with st.expander("Preflight・決算・マクロ・デイトレ補完"):
        ids=list(e["evidence_id"] for e in meta["evidence"])
        tick=st.text_input("呼値（未確認なら空欄）",value=str(meta.get("tick_size") or ""))
        meta["tick_size"]=float(tick) if tick.strip() else None
        meta["tick_evidence_id"]=st.selectbox("呼値のEvidence",[""]+ids,index=([""]+ids).index(meta.get("tick_evidence_id","")) if meta.get("tick_evidence_id","") in ids else 0)
        review=meta.setdefault("preflight_review",{})
        for key,label in (("negative_news","重大悪材料"),("thesis","投資前提"),("liquidity","流動性")):
            item=review.setdefault(key,{})
            item["reviewed"]=st.checkbox(label+"を独立確認済み",value=item.get("reviewed",False),key="uat_pf_"+key)
            item["evidence_ids"]=refs(st.text_input(label+"の根拠ID（カンマ区切り）",value=",".join(item.get("evidence_ids",[])),key="uat_pf_ev_"+key))
        wr=[{**r,"evidence_ids":",".join(r.get("evidence_ids",[]))} for r in meta.get("warnings",[])]
        warnings=st.data_editor(pd.DataFrame(wr,columns=["code","severity","scope","reason","evidence_ids","resolution"]),
            num_rows="dynamic",key="uat_warnings",column_config={"severity":st.column_config.SelectboxColumn(options=["Critical","Severe","Warning"])})
        meta["warnings"]=[{**r,"evidence_ids":refs(r.get("evidence_ids"))} for r in table_rows(warnings) if r.get("reason")]
        meta["earnings_at"]=st.text_input("次回決算日時（未確認なら空欄）",value=meta.get("earnings_at") or "") or None
        meta["earnings_evidence_ids"]=refs(st.text_input("決算の根拠ID",value=",".join(meta.get("earnings_evidence_ids",[]))))
        financial=meta.setdefault("latest_financial",{})
        financial["latest_confirmed"]=st.checkbox("最新の公式決算等を確認済み",value=financial.get("latest_confirmed",False))
        financial["period"]=st.text_input("対象期",value=financial.get("period",""))
        financial["evidence_ids"]=refs(st.text_input("公式決算等の根拠ID",value=",".join(financial.get("evidence_ids",[]))))
        macro=meta.setdefault("macro",{})
        for key,label in (("sector","1. セクター特定"),("sector_condition","2. セクター地合い")):
            macro[key]=st.text_input(label,value=macro.get(key,""),key="uat_macro_"+key)
        driver_text=st.text_area("3. 主要ドライバー（為替・金利・原油・商品・指数・地政学等）",
            value="\n".join(x.get("name",str(x)) if isinstance(x,dict) else str(x) for x in macro.get("drivers",[])))
        old_drivers=macro.get("drivers",[])
        macro["drivers"]=[next((x for x in old_drivers if isinstance(x,dict) and x.get("name")==s),{"name":s}) for s in driver_text.splitlines() if s.strip()]
        for key,label in (("company_sensitivity","4. 企業感応度"),("specific_factors","5. 個別要因"),("dominant_force","6. 個別とセクターの強弱比較")):
            macro[key]=st.text_input(label,value=macro.get(key,""),key="uat_macro_"+key)
        macro["evidence_ids"]=refs(st.text_input("マクロ経路の根拠ID",value=",".join(macro.get("evidence_ids",[]))))
        meta["exit_conditions"]=st.text_area("撤退条件（1行1条件）",value="\n".join(meta.get("exit_conditions",[]))).splitlines()
        intraday=st.file_uploader("当日の確定5分足CSV（timestampは足の終了日時、OHLCV）",type=["csv"],key="uat_intraday")
        if intraday: meta["intraday_bars"]=pd.read_csv(intraday).to_dict("records")
        meta["intraday_interval"]="5m"
        meta["intraday_closed_confirmed"]=st.checkbox("分足が確定5分足・終了日時であることを確認",value=meta.get("intraday_closed_confirmed",False))
        for key,label in (("intraday_evidence_id","分足の根拠ID"),("today_material_evidence_ids","当日材料の根拠ID"),
             ("same_time_volume_evidence_ids","出来高の同時刻比較の根拠ID"),("execution_evidence_ids","約定環境の直接根拠ID")):
            val=meta.get(key,"" if key=="intraday_evidence_id" else [])
            text=st.text_input(label,value=val if isinstance(val,str) else ",".join(val))
            meta[key]=text if key=="intraday_evidence_id" else refs(text)
        with st.popover("支配的材料・Severe例外根拠・カレンダー等"):
            st.caption('中長期の抵抗帯がない場合のみvaluation_planを使用可。formula: EPS*PE、currency: JPY、eps、multiple_first、multiple_final（任意）、period、assumptions、sector_suitable_confirmed: true、evidence_idsを指定。赤字のPER評価は不可。')
            extras=st.text_area("詳細補足JSON",value=json.dumps({k:meta.get(k,[] if k in ("calendar","volume_profile") else {}) for k in ("dominant_factor","severe_conditions","calendar","volume_profile","valuation_plan")},ensure_ascii=False,indent=2),height=220)
            obj=json.loads(extras)
            if not isinstance(obj,dict) or set(obj)-{"dominant_factor","severe_conditions","calendar","volume_profile","valuation_plan"}: raise InputError("詳細補足の項目が不正です。")
            meta.update(obj)
    return meta

def supplementary_tools(meta):
    with st.expander("無料の最新情報・AI用データ"):
        st.caption("取得はボタン操作時だけ。公開ニュースは根拠の候補として追加し、企業への作用はマクロ経路と採点カードで確認します。")
        source=st.selectbox("公開情報",["ecb","fed"],format_func=lambda s:{"ecb":"ECB 為替参考レート","fed":"Federal Reserve 金融政策ニュース"}[s])
        if st.button("公開情報を取得"):
            try:
                require_available("public_context")
                st.session_state.uat_context=PublicContextProvider().fetch(source)
            except InputError as exc: st.error(str(exc))
        if st.session_state.get("uat_context"):
            context=st.session_state.uat_context
            st.json(context["data"],expanded=False)
            ids=[e["evidence_id"] for e in context["evidence"]]
            selected=st.multiselect("分析に採用する根拠",ids,format_func=lambda r:next(e["summary"][:100] for e in context["evidence"] if e["evidence_id"]==r))
            if st.button("選択情報をEvidenceへ追加"):
                existing={e["evidence_id"] for e in meta["evidence"]}
                meta["evidence"] += [e for e in context["evidence"] if e["evidence_id"] in selected and e["evidence_id"] not in existing]
                st.session_state.uat_work["meta"]=meta
                st.session_state.pop("uat_evidence",None);st.rerun()
        st.link_button("企業IR・決算の原資料を確認（JPX）","https://www.jpx.co.jp/listing/disclosure/01.html")
        st.caption("企業IR、業績予想、カタリスト、セクター、金利・商品・指数・地政学は出典と観測日時をEvidence表へ追記できます。")
        evidence={e["evidence_id"]:e for e in meta.get("evidence",[])}
        selected=st.multiselect("外部AIへ渡してよい公開・分析用Evidence",list(evidence),key="uat_ai_ids")
        if st.button("AI用の定性評価依頼を作る"):
            try: st.session_state.uat_ai_request=export_request(meta["symbol"],meta["as_of"],evidence,selected)
            except InputError as exc: st.error(str(exc))
        request=st.session_state.get("uat_ai_request")
        if request:
            st.download_button("AI用依頼JSONを保存",canonical(request),file_name="context_request.json")
            st.caption("外部AIへの自動送信は未接続です。依頼内容を確認して使用するAIへ渡し、返答JSONを下から取り込めます。")
            response=st.file_uploader("AIの定性評価応答JSON",type=["json"],key="uat_ai_response")
            if st.button("AI応答を検査して採用"):
                try:
                    current=export_request(meta["symbol"],meta["as_of"],evidence,list(request["evidence"]))
                    if current["request_id"]!=request["request_id"]: raise InputError("根拠が変わっています。AI用依頼を作り直してください。")
                    if response is None: raise InputError("応答JSONを指定してください。")
                    imported=import_response(json.loads(response.getvalue()),request)
                    codes={r["criterion_id"] for r in imported}
                    meta["assessments"]=[r for r in meta["assessments"] if r["criterion_id"] not in codes]+imported
                    st.session_state.uat_work["meta"]=meta
                    for k in list(st.session_state):
                        if k.startswith("uat_cards_"): del st.session_state[k]
                    st.rerun()
                except (InputError,ValueError) as exc: st.error(str(exc))

def render_uat(history,detail_renderer,logger):
    top=st.container()
    load_input()
    work=st.session_state.uat_work
    st.caption("読込中："+work["meta"]["name"]+" / "+work["meta"]["symbol"]+" / "+work["meta"]["as_of"])
    if work["meta"].get("is_demo"): st.warning("架空データを読込中です。実在銘柄の評価ではありません。")
    try:
        meta=edit_metadata(work["meta"])
        supplementary_tools(meta)
        policy_label=st.selectbox("決算跨ぎ方針",["未指定（両方比較）","跨ぐ","跨がない"],key="uat_policy")
        policy={"未指定（両方比較）":"unspecified","跨ぐ":"allow","跨がない":"avoid"}[policy_label]
        entry=st.text_input("想定Entry（任意・空欄なら現在値）",key="uat_entry")
        request_hash=digest([digest(work["csv"].hex()),meta,entry,policy])
        col1,col2=st.columns(2)
        if col1.button("3時間軸で分析・履歴保存",type="primary"):
            try:
                bundle=bundle_from_input(work["csv"],meta,meta["symbol"],meta["as_of"])
                with st.spinner("価格構造と時間軸ごとの根拠を分析中"):
                    results=run_all(bundle,history,policy,entry.strip() or None)
                st.session_state.uat_results=results;st.session_state.uat_result_input=request_hash
                st.session_state.uat_work["meta"]=meta
                logger.info("uat_analysis_completed symbol=%s",meta["symbol"])
            except Exception as exc:
                logger.exception("uat_analysis_failed");show_error(exc)
        col2.download_button("補足入力をJSON保存",canonical(meta),file_name="analysis_input.json",mime="application/json")
        if st.button("編集した入力を保持"):
            st.session_state.uat_work["meta"]=meta;st.success("この画面内の入力を保持しました。永続保存にはJSON保存を使用してください。")
    except (ValueError,TypeError,KeyError,InputError) as exc:
        st.error("入力の形式を修正してください："+str(exc));request_hash="invalid"
    if st.session_state.get("uat_results"):
        results=st.session_state.uat_results
        same=request_hash==st.session_state.get("uat_result_input")
        with top:
            if not same: st.warning("入力が変更されています。以下は前回の分析結果です。再分析してください。")
            summary(results,stale=not same)
        h=st.session_state.get("uat_detail","swing")
        r=results[h]
        with st.expander(LABELS[h]+"の判断理由・価格候補・採点内訳・Evidence",expanded=False):
            detail_renderer(r,r["approval_hash"] if same else "changed")
        st.download_button("3時間軸の分析結果を保存",canonical(results),file_name="multi_analysis.json")
    else:
        with top: st.info("銘柄・資料を読み込み「3時間軸で分析」を押してください。開発用データでも操作できます。")
    with st.expander("分析履歴"):
        for run in history.list_runs(15):
            r=history.get(run["run_id"])
            internal_link(LABELS.get(r["metadata"].get("horizon","swing"),"スイング")+" / "+run["symbol"]+" / "+run["as_of"],"?run="+run["run_id"])
    internal_link("従来のスイング試用画面","?workspace=legacy")
