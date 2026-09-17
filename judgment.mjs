// Native tracker feature. All investment decisions remain in the Python engine.
const esc = (v="") => String(v ?? "").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const obj = v => v && typeof v === "object" ? v : {};
const text = v => v == null ? "未評価" : typeof v === "object" ? JSON.stringify(v) : String(v);
const scoreText = v => v == null ? "未評価" : Number(v).toFixed(1)+" / 10";
const num = v => v == null ? "未評価" : Number(v).toLocaleString("ja-JP",{maximumFractionDigits:2});
const refs = v => String(v||"").split(/[,、\n]/).map(x=>x.trim()).filter(Boolean);
const names = {swing:"スイング",midlong:"中長期"};
const opt = (v,label=v) => '<option value="'+esc(v)+'">'+esc(label)+'</option>';
const input = (id,label,type="text",extra="") => '<label>'+label+'<input id="j-'+id+'" type="'+type+'" '+extra+'></label>';
const area = (id,label) => '<label>'+label+'<textarea id="j-'+id+'" rows="3"></textarea></label>';
const check = (id,label) => '<label class="j-check"><input id="j-'+id+'" type="checkbox">'+label+'</label>';
const detail = (title,body,open=false) => '<details class="j-detail" '+(open?"open":"")+'><summary>'+title+'</summary><div class="j-detail-body">'+body+'</div></details>';
const button = (id,label,primary=false) => '<button id="j-'+id+'" type="button" class="'+(primary?"primary-button":"secondary-button")+'">'+label+'</button>';
const metric = (label,value) => '<div class="j-metric"><span>'+esc(label)+'</span><strong>'+esc(value)+'</strong></div>';
const list = values => '<ul>'+((values||[]).map(v=>'<li>'+esc(text(v))+'</li>').join("")||"<li>情報なし</li>")+'</ul>';
const bytes64 = file => new Promise((resolve,reject)=>{
  if(file.type.startsWith("image/") && file.size>6000000) return reject(new Error("画像は6MB以内です。"));
  if(file.size>10000000) return reject(new Error("ファイルは10MB以内です。"));
  const r=new FileReader();r.onload=()=>resolve(String(r.result).split(",")[1]);r.onerror=reject;r.readAsDataURL(file);
});
const download = (name,value) => {
  const url=URL.createObjectURL(new Blob([JSON.stringify(value,null,2)],{type:"application/json"}));
  const a=document.createElement("a");a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
};

export function createJudgment(root,getUser,getSecurities) {
  let mounted=false,catalog=null,metadata={},csv="",results={},recommended=[],horizon="swing",scenario="",apiBase="",busy=false,generation=0;
  let inputVersion=0,resultVersion=-1;
  const $ = id => root.querySelector("#j-"+id);
  const val = id => $(id)?.value.trim()||"";
  const checked = id => $(id)?.checked===true;
  const set = (id,v) => {if($(id)) $(id).value=v??"";};
  const message = (value,error=false) => {if($("message")) {$("message").textContent=value;$("message").classList.toggle("j-error",error);}};
  const changed = () => {
    inputVersion++;
    if($("recommendation")) $("recommendation").textContent="推奨時間軸：入力変更後の再分析が必要";
    if($("verdict-label")&&!$("verdict-label").textContent.includes("入力変更前")) $("verdict-label").textContent+="（入力変更前）";
    if($("stale")) $("stale").textContent="入力を変更しました。表示中の分析は以前の入力です。再分析してください。";
    root.querySelectorAll("[data-approval]").forEach(b=>b.disabled=true);
  };
  async function api(action,payload) {
    const user=getUser(),epoch=generation;
    if(!user) throw new Error("Googleアカウントでログインしてください。");
    if(!apiBase) {
      const config=await fetch("./judgment-config.json",{cache:"no-cache"});
      if(!config.ok) throw new Error("判定サーバーの接続設定を読み込めません。");
      const data=await config.json(),url=new URL(data.apiBase,location.href);
      if(url.username||url.password||url.search||url.hash ||
         !(url.protocol==="https:" || (url.protocol==="http:" && ["localhost","127.0.0.1","[::1]"].includes(url.hostname))))
        throw new Error("判定サーバーにはHTTPSのURLが必要です。");
      apiBase=url.href.replace(/\/$/,"");
    }
    const token=await user.getIdToken();
    const slow=setTimeout(()=>{if(epoch===generation) message("取得・分析を続けています。初回はサーバーの起動にも時間がかかります…");},12000);
    const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),180000);
    try {
    const response=await fetch(apiBase+"/"+action,{method:payload===undefined?"GET":"POST",
      headers:{Authorization:"Bearer "+token,...(payload===undefined?{}:{"Content-Type":"application/json"})},
      body:payload===undefined?undefined:JSON.stringify(payload),cache:"no-store",credentials:"omit",redirect:"error",signal:controller.signal});
    if(epoch!==generation||getUser()?.uid!==user.uid) throw new Error("ログイン情報が変わりました。");
    let data;try {data=await response.json();} catch {throw new Error("判定サーバーに接続できません。公開先の設定を確認してください。");}
    if(!response.ok) throw new Error(data.error||"判定サーバーでエラーが発生しました。");
    return data;
    } catch(e) {
      if(e.name==="AbortError" || e instanceof TypeError) throw new Error("接続が完了しませんでした。保存済みの場合もあるため、履歴を確認してから再操作してください。");
      throw e;
    } finally {clearTimeout(slow);clearTimeout(timeout);}
  }
  async function work(task,success="") {
    if(busy) return;busy=true;
    root.setAttribute("aria-busy","true");
    root.querySelectorAll("button,input,select,textarea").forEach(b=>b.disabled=true);
    message("処理しています…");
    const epoch=generation;
    try {await task();if(epoch===generation && success) message(success);}
    catch(e) {if(epoch===generation) message(e.message||"処理できませんでした。",true);}
    finally {
      if(epoch===generation) {busy=false;root.removeAttribute("aria-busy");root.querySelectorAll("button,input,select,textarea").forEach(b=>b.disabled=false);
        if(inputVersion!==resultVersion) root.querySelectorAll("[data-approval]").forEach(b=>b.disabled=true);}
    }
  }
  const on = (id,fn) => $(id).addEventListener("click",()=>work(fn));
  function currentMeta() {
    const m=structuredClone(metadata);
    m.symbol=resolveSymbol().code;m.name=resolveSymbol().name;m.as_of=val("asof");
    m.tick_size=val("tick")?Number(val("tick")):null;m.tick_evidence_id=val("tick-ref");
    m.earnings_at=val("earnings")||null;m.earnings_evidence_ids=refs(val("earnings-ref"));
    m.latest_financial={...obj(m.latest_financial),latest_confirmed:checked("financial-confirm"),period:val("financial-period"),evidence_ids:refs(val("financial-ref"))};
    m.preflight_review={};
    ["negative_news","thesis","liquidity"].forEach(k=>m.preflight_review[k]={reviewed:checked("pf-"+k),evidence_ids:refs(val("pf-ref-"+k))});
    m.macro={...obj(m.macro),sector:val("sector"),sector_condition:val("sector-condition"),
      drivers:refs(val("drivers")).map(name=>(m.macro?.drivers||[]).find(d=>d.name===name)||({name})),company_sensitivity:val("sensitivity"),
      specific_factors:val("specific"),dominant_force:val("dominance"),evidence_ids:refs(val("macro-ref"))};
    m.exit_conditions=val("exit").split("\n").map(x=>x.trim()).filter(Boolean);
    return m;
  }
  function resolveSymbol() {
    const query=val("symbol").normalize("NFKC"), stocks=getSecurities();
    const match=stocks.find(s=>s.code===query||s.name===query||s.code+" "+s.name===query);
    if(match) return {code:match.code,name:match.name};
    if(!/^[0-9A-Za-z]{4,12}$/.test(query)) throw new Error("候補から銘柄を選択するか、銘柄コードを入力してください。");
    return {code:query,name:metadata.symbol===query?(metadata.name||query):query};
  }
  function hydrate(m) {
    metadata=structuredClone(m);
    set("symbol",m.symbol);set("asof",m.as_of||new Date().toISOString());
    set("tick",m.tick_size);set("tick-ref",m.tick_evidence_id);set("earnings",m.earnings_at);set("earnings-ref",(m.earnings_evidence_ids||[]).join(","));
    const f=obj(m.latest_financial);
    $("financial-confirm").checked=!!f.latest_confirmed;set("financial-period",f.period);set("financial-ref",(f.evidence_ids||[]).join(","));
    ["negative_news","thesis","liquidity"].forEach(k=>{
      const p=obj(obj(m.preflight_review)[k]);$("pf-"+k).checked=!!p.reviewed;set("pf-ref-"+k,(p.evidence_ids||[]).join(","));
    });
    const macro=obj(m.macro);
    [["sector","sector"],["sector-condition","sector_condition"],["sensitivity","company_sensitivity"],["specific","specific_factors"],["dominance","dominant_force"]].forEach(([a,b])=>set(a,macro[b]));
    set("drivers",(macro.drivers||[]).map(x=>typeof x==="string"?x:x.name).join(","));
    set("macro-ref",(macro.evidence_ids||[]).join(","));set("exit",(m.exit_conditions||[]).join("\n"));
    evidenceList();cardGuide();changed();
  }
  const imageButton = e => /^firestore:users\/[^/]+\/judgmentImages\/[a-f0-9]{32}$/.test(e.source_uri||"")
    ? '<button type="button" class="secondary-button" data-image="'+esc(e.source_uri.split("/").pop())+'">保存画像を表示</button>' : "";
  root.addEventListener("click",event=>{
    const b=event.target.closest("[data-image]");if(!b||!root.contains(b))return;
    work(async()=>{
      const value=await api("images/"+b.dataset.image);
      if(!["image/png","image/jpeg"].includes(value.mime))throw new Error("画像形式が不正です。");
      const img=document.createElement("img");img.alt="保存した判断根拠";img.style.maxWidth="100%";
      img.src="data:"+value.mime+";base64,"+value.data;b.replaceWith(img);
    });
  });
  function evidenceList() {
    $("evidence-list").innerHTML=(metadata.evidence||[]).map(e=>'<div class="j-evidence"><strong>'+esc(e.evidence_id)+'</strong><p>'+esc(e.summary)+'</p><small>'+esc(e.source_name)+" · "+esc(e.observed_at)+'</small>'+imageButton(e)+'</div>').join("")||'<p class="j-muted">根拠はまだ登録されていません。</p>';
    $("card-count").textContent=(metadata.assessments||[]).length+"件の手動採点";
  }
  function cardGuide() {
    const id=val("card"),c=catalog?.cards[id];
    if(!c) return;
    $("card-guide").innerHTML='<p>必要な根拠：'+esc(c.required_evidence)+'</p>'+list(Object.entries(c.anchors).map(([k,v])=>k+"："+v));
    const row=(metadata.assessments||[]).find(r=>r.criterion_id===id)||{};
    set("anchor",row.anchor||"");set("card-refs",(row.evidence_ids||[]).join(","));set("reason",row.reason);set("counter",row.counter_reason);
  }
  function renderResult() {
    const r=results[horizon];if(!r) return;
    const keys=Object.keys(r.decisions);
    if(!keys.includes(scenario)) scenario=keys.find(k=>k==="現値:avoid")||keys[0];
    const d=r.decisions[scenario]||{},kind=scenario.split(":")[0],s=r.scores[kind]||Object.values(r.scores)[0]||{};
    const p=r.plans.find(p=>p.kind===kind)||{};
    const planGaps=r.metadata.automatic?.card_gaps_by_plan?.[kind];
    const missingDetails=planGaps ? Object.entries(planGaps).map(([id,gap])=>
      id+" "+(catalog?.cards[id]?.label||id)+"："+gap.reason).concat((r.findings||[])
        .filter(f=>f.code.startsWith("unchecked_")||f.code.endsWith("_missing")).map(f=>f.reason))
      : r.metadata.automatic?.missing||[];
    const daily=r.technical.daily||[],price=daily.at(-1)?.close??r.technical.latest;
    const findings=[...(d.findings||r.findings||[])].sort((a,b)=>({Critical:0,Severe:1,Warning:2}[a.severity]??3)-({Critical:0,Severe:1,Warning:2}[b.severity]??3));
    const expired=p.expires_at && new Date(p.expires_at)<new Date();
    const preferred=inputVersion===resultVersion?recommended.filter(h=>Object.values(results[h]?.presentation||{}).some(v=>v.can_recommend&&!v.expired)):[];
    const recommendationText=preferred.length?preferred.map(h=>names[h]).join(" / "):Object.values(results).every(x=>Object.values(x.decisions||{}).every(d=>d.label==="見送り"))?"見送り":"未判定（必要情報が不足）";
    const view=r.presentation?.[scenario]||{};
    let label=view.label||d.label||d.status||"未評価";
    if(findings.some(f=>f.severity==="Critical"))label="評価保留";
    if(inputVersion!==resultVersion)label+="（保存済みの分析）";
    else if(expired&&!label.includes("期限切れ"))label+="（期限切れ・履歴）";
    const note=r.metadata.is_demo?"検証用の架空データ":expired?"価格プランの有効期限切れ":d.approval_required?"重大警告の確認が必要":d.status;
    const macro=obj(r.technical.macro);
    const horizonScore=h=>{const x=results[h];return x?.scores?.[scenario.split(":")[0]]||x?.scores?.["現値"]||Object.values(x?.scores||{})[0]||{};};
    $("result").hidden=false;
    $("result").innerHTML=[
      '<div class="j-result-head"><div><p class="section-kicker">判断サマリ</p><h2>'+esc(r.symbol+" "+r.name)+'</h2></div>'+'<span hidden>'+button("export-result","JSON保存")+'</span>'+'</div>',
      '<p id="j-recommendation" class="j-muted">推奨時間軸：'+esc(recommendationText)+'<br>表示中：'+esc(names[horizon]+" / "+kind)+'</p>',
      '<div class="j-verdict"><strong id="j-verdict-label">'+esc(label)+'</strong><span>'+esc(note)+'</span></div>',
      '<div class="j-metrics">'+[
        ["スイング投資妙味",scoreText(horizonScore("swing").investment)],["スイングEntry品質",scoreText(horizonScore("swing").entry)],
        ["中長期投資妙味",scoreText(horizonScore("midlong").investment)],["中長期Entry品質",scoreText(horizonScore("midlong").entry)],[expired||inputVersion!==resultVersion?"分析時の株価":"現在値（参考・遅延あり）",num(r.metadata.automatic?.current_quote?.price??price)],
        [label.startsWith("評価保留")?"Entry候補（未確定）":"推奨Entry",num(p.entry)],["第1利確",num(p.target1)],["最終利確",num(p.target2)],["Alert",num(p.alert)],
        ["第1損切",num(p.stop1)],["最終損切",num(p.stop2)],["RR",num(p.rr)],["データ信頼度",num(r.confidence?.value)+" / 100"]
      ].map(([k,v])=>metric(k,v)).join("")+'</div>',
      '<p class="j-concern"><b>最大懸念</b> '+esc(findings[0]?.reason||d.wait_reasons?.[0]||"記録された懸念なし")+'</p>',
      (label.startsWith("評価保留")?'<p class="j-muted">価格戦略は取得済み価格からの参考候補です。買い推奨は未確定です。</p>':""),
      (r.metadata.automatic?.current_quote?.observed_at?'<p class="j-muted">株価の観測日時：'+esc(new Date(r.metadata.automatic.current_quote.observed_at).toLocaleString("ja-JP",{timeZone:"Asia/Tokyo"}))+'（日本時間）</p>':""),
      detail("時間軸・価格条件を変更",'<div class="j-grid"><label>表示する時間軸<select id="j-horizon">'+Object.keys(results).map(h=>opt(h,names[h])).join("")+'</select></label>'+
      '<label>価格・決算方針<select id="j-scenario">'+keys.map(k=>opt(k,k.replace(":avoid","・決算を跨がない").replace(":allow","・決算を跨ぐ"))).join("")+'</select></label></div>'),
      '<p id="j-stale" class="j-error" role="status">'+(inputVersion!==resultVersion?"保存された分析です。現在の入力との一致を確認して再分析してください。":"")+'</p>',
      '<p class="j-muted">分析日時：'+esc(r.as_of)+' ／ 価格プラン有効期限：'+esc(p.expires_at||"未成立")+'</p>',
      detail("2つの時間軸を比較",'<div class="j-horizons">'+Object.entries(results).map(([h,x])=>{
        const ds=x.decisions["現値:avoid"]||Object.values(x.decisions)[0],sc=x.scores["現値"]||Object.values(x.scores)[0]||{};
        return '<div class="j-mini"><b>'+esc(names[h])+'</b><p>'+esc(x.presentation?.["現値:avoid"]?.label||ds?.label||ds?.status||"未評価")+'</p><p>投資妙味 '+num(sc.investment)+'</p><p>Entry品質 '+num(sc.entry)+'</p></div>';
      }).join("")+'</div><p class="j-muted">各時間軸は独立評価です。異なる時間軸の点数を単純に順位付けしません。</p>'),
      detail("今買う vs 待つ・撤退条件",'<div class="j-grid"><div><h3>今買う根拠</h3>'+list(d.buy_reasons)+'</div><div><h3>待つ根拠</h3>'+list(d.wait_reasons)+'</div></div><h3>投資前提が崩れた場合</h3>'+list(r.metadata.exit_conditions)+'<p>価格構造の無効化：'+esc(text(p.invalidation))+'</p><h3>支配的材料による補正</h3>'+list(d.overrides)),
      detail("独立した事前確認・Critical / Severe / Warning",findings.map(f=>'<div class="j-finding"><b>'+esc(f.severity+" · "+f.code)+'</b><p>'+esc(f.reason)+'</p><small>対応：'+esc(f.resolution||"根拠と条件を再確認")+' / Evidence: '+esc((f.evidence_ids||[]).join(", "))+'</small></div>').join("")||"<p>警告なし</p>"),
      d.approval_required?detail("重大警告を確認して記録",'<p>対象の条件判断：'+esc(d.candidate||d.label||d.status)+'</p><p>承認は対象分析と価格プランだけに有効です。注文は実行しません。</p><p id="j-approval-status"></p>'+(d.approval_eligible&&!r.metadata.is_demo&&!expired?check("approval-confirm","上の警告・残存リスク・撤退条件を確認した")+'<div class="j-actions"><button type="button" class="secondary-button" data-approval="approved">条件を承認して記録</button><button type="button" class="secondary-button" data-approval="rejected">拒否を記録</button></div>':"<p>現在の条件では承認できません。</p>")):"",
      detail("不足データ",list(missingDetails)+list((s.missing||[]).map(id=>catalog?.cards[id]?.label||id))),
      detail("判断材料・採点の根拠",'<p>構造化評価 '+num(s.structured)+' × 70% ＋ 定性コンテキスト '+num(s.context)+' × 30%</p><p>投資妙味：'+esc(s.status)+' ／ Entry品質：'+esc(s.entry_status)+'</p>'+Object.entries(s.items||{}).map(([id,row])=>'<div class="j-evidence"><b>'+esc(catalog?.cards[id]?.label||id)+' — '+num(row.score)+'</b><p>'+esc(row.reason)+'</p><p class="j-muted">反証：'+esc(row.counter_reason)+'</p><small>Evidence: '+esc((row.evidence_ids||[]).join(", "))+'</small></div>').join("")+'<h3>不足項目</h3>'+list(s.missing)),
      ...[
        ["業績・将来成長",["SW-A","ML-A","ML-B","ML-D","ML-F"]],
        ["カタリスト",["SW-C","ML-C"]],["市場期待・織り込み",["SW-B","ML-E"]],
        ["出来高・信用需給",["SW-E","ML-J"]],["バリュエーション・競争優位",["SW-I","SW-G","ML-H","ML-C"]]
      ].map(([title,prefixes])=>detail(title,list(Object.entries(s.items||{}).filter(([id])=>prefixes.some(k=>id.startsWith(k))).map(([id,row])=>(catalog?.cards[id]?.label||id)+"："+(row.score==null?"未評価":Number(row.score).toFixed(1))+" / "+(row.reason||"根拠不足"))))),
      detail("週足・日足・出来高",'<p>スイング：数日〜3か月／中長期：3か月以上。週足を主、日足をEntryの補助として評価</p><div class="j-metrics">'+metric("週足の大局",text(r.technical.weekly_trend))+metric("確定週足",num(r.technical.weekly_count))+metric("RSI",num(r.technical.rsi))+metric("出来高比",num(r.technical.volume_ratio))+'</div><p>支持・抵抗帯の根拠</p>'+list((r.technical.bands||[]).map(x=>JSON.stringify(x)))),
      detail("セクター・マクロ",'<ol>'+[
        ["セクター特定",macro.sector||r.metadata.automatic?.sector],["セクター地合い",macro.sector_condition],
        ["主要ドライバー",(macro.drivers||[]).map(x=>x.name||x).join("、")],
        ["企業の感応度",macro.company_sensitivity],["セクター要因と個別材料の強弱",macro.dominant_force]
      ].map(([k,v])=>'<li><b>'+esc(k)+'</b><p>'+esc(v||"不足")+'</p></li>').join("")+'</ol><p>個別材料：'+esc(macro.specific_factors||"不足")+'</p><p>根拠が揃っているか：'+(macro.valid?"確認済み":"不足")+'</p>'),
      detail("Evidence・データ信頼度・決算",'<p>'+esc(r.confidence?.note)+'</p><p>決算予定：'+esc(r.earnings?.scheduled_at||"未確認")+'</p>'+Object.values(r.evidence||{}).map(e=>'<div class="j-evidence"><b>'+esc(e.evidence_id)+'</b><p>'+esc(e.summary)+'</p><small>'+esc(e.source_name)+" / "+esc(e.source_uri)+" / "+esc(e.observed_at)+'</small>'+imageButton(e)+'</div>').join("")),
      '<p class="j-muted">分析ID：'+esc(r.run_id)+'<br>設定：'+esc(r.config_version)+'<br>判断支援用の記録です。自動売買は行いません。</p>'
    ].join("");
    set("horizon",horizon);set("scenario",scenario);
    $("horizon").onchange=()=>{horizon=val("horizon");scenario="";renderResult();};
    $("scenario").onchange=()=>{scenario=val("scenario");renderResult();};
    $("export-result").onclick=()=>download("analysis-"+r.run_id+".json",{schema_version:1,analysis_id:r.run_id,symbol:r.symbol,horizon,scenario,plan_id:p.plan_id||null,as_of:r.as_of,rule_version:r.config_version,approval_hash:r.approval_hash,is_demo:r.metadata.is_demo,trade_id:null,result:r});
    root.querySelectorAll("[data-approval]").forEach(b=>{
      b.disabled=inputVersion!==resultVersion;
      b.onclick=()=>work(async()=>{
        const status=await api("approval",{run_id:r.run_id,scenario,action:b.dataset.approval,
          confirmed:checked("approval-confirm"),target_hash:r.approval_hash,current_hash:r.approval_hash});
        $("approval-status").textContent=status==="approved"?"承認を記録しました（注文は実行しません）。":"拒否を記録しました。";
      });
    });
    if(d.approval_required) {
      const activeRun=r.run_id,activeScenario=scenario;
      api("approval?run_id="+encodeURIComponent(r.run_id)+"&scenario="+encodeURIComponent(scenario)).then(status=>{
        if(results[horizon]?.run_id===activeRun&&scenario===activeScenario&&$("approval-status"))
          $("approval-status").textContent="記録状態："+({approved:"承認済み",rejected:"拒否済み",expired:"期限切れ",pending:"未確認",not_requested:"対象外"}[status]||status);
      }).catch(()=>{});
    }
  }
  async function history() {
    const rows=(await api("history")).filter(r=>names[r.horizon||"swing"]);
    $("history").innerHTML=rows.length?rows.map(r=>'<button type="button" class="j-history-row" data-run="'+esc(r.run_id)+'"><span>'+esc(r.symbol+" "+r.name+" / "+names[r.horizon])+'</span><small>'+esc(r.as_of)+(r.is_demo?" / 架空データ":"")+'</small></button>').join(""):"<p>保存された分析はありません。</p>";
    root.querySelectorAll("[data-run]").forEach(b=>b.onclick=()=>work(async()=>{
      const r=await api("runs/"+encodeURIComponent(b.dataset.run));
      horizon=r.metadata.horizon||"swing";if(!names[horizon])throw new Error("現在の対象時間軸ではありません。");results={[horizon]:r};recommended=[];resultVersion=-1;scenario="";renderResult();
      $("result").scrollIntoView({behavior:"smooth",block:"start"});
    }));
  }
  function mount() {
    mounted=true;
    root.classList.add("judgment");
    root.innerHTML=[
      '<div id="j-result" class="panel j-result"><p class="j-muted">銘柄を入力すると、ここに結論・価格戦略を表示します。</p></div>',
      '<p id="j-message" role="status" aria-live="polite"></p>',
      '<div class="panel j-inputs"><h2>銘柄を判断する</h2><div class="j-grid">',
      input("symbol","銘柄名・銘柄コード","text",'list="j-securities" autocomplete="off" placeholder="例：7203 トヨタ自動車"'),
      '<datalist id="j-securities"></datalist>',
      input("entry","想定Entry価格（任意）","number",'min="0" step="any" inputmode="decimal"'),
      input("asof","分析基準日時","text",'placeholder="2026-09-11T16:00:00+09:00"'),
      '<label>決算を跨ぐ方針<select id="j-policy">'+opt("unspecified","未定（両方を比較）")+opt("avoid","跨がない")+opt("allow","跨ぐ")+'</select></label></div>',
      detail("1. 株価データ（無料取得 → CSV）",'<div class="j-grid">'+input("start","取得開始日","date")+input("end","取得終了日","date")+'</div>'+button("fetch","無料の公開日足を取得")+
        '<p id="j-source" class="j-muted">未取得。取得できない場合はCSVを読み込んでください。</p><div class="j-grid">'+input("csv","日足CSV","file",'accept=".csv"')+'</div>'+
        '<p class="j-muted">CSV列：symbol_code, timestamp, open, high, low, close, volume, adjustment_basis。日本語の銘柄コード・日時・始値・高値・安値・終値・出来高にも対応します。欠損価格を推測して補いません。</p>'+
        '<div class="j-grid">'+input("adjustment","価格調整基準","text",'placeholder="例：split_adjusted（分割調整済みと確認した場合）"')+input("close-time","日付だけのCSVに付ける確定時刻（日本時間）","time")+'</div>'+check("csv-confirm","選択した銘柄・価格調整基準・確定時刻がCSVと一致している"),true),
      detail("2. 根拠資料・スクリーンショット",'<p class="j-muted">Evidenceは判断の根拠資料です。画像は目視で確認し、読み取った内容を登録します。</p>'+
        '<div class="j-grid">'+input("ev-id","Evidence ID","text",'placeholder="例：financial-2026q2"')+input("ev-source","資料名")+input("ev-uri","出典URL・資料の所在")+input("ev-observed","対象日時（時差付き）")+input("ev-published","公表日時（時差付き）")+input("ev-until","有効期限（時差付き）")+
        '<label>出典の確認<select id="j-ev-quality">'+opt("unknown","未確認")+opt("original_verified","原資料を確認")+opt("secondary_verified","二次資料を確認")+opt("image_verified","画像を目視確認")+'</select></label>'+
        area("ev-summary","確認した事実・要約")+'</div>'+button("add-evidence","根拠を登録・更新")+
        '<div class="j-grid">'+input("image","スクリーンショット（PNG/JPEG・6MB以内）","file",'accept="image/png,image/jpeg"')+check("image-confirm","画像の銘柄・日時・内容を目視確認した")+'</div>'+button("add-image","画像を根拠として保存")+'<div id="j-evidence-list"></div>'),
      detail("3. 独立した事前確認（Preflight）",'<p class="j-muted">点数とは独立して確認します。チェックだけでなく、根拠IDを紐付けてください。</p>'+[
        ["negative_news","重大な悪材料を確認した"],["thesis","投資前提の崩れを確認した"],["liquidity","流動性・執行可能性を確認した"]
      ].map(([k,l])=>'<div class="j-grid">'+check("pf-"+k,l)+input("pf-ref-"+k,"根拠ID（カンマ区切り）")+'</div>').join("")+
        '<div class="j-grid">'+input("tick","呼値（価格の刻み）","number",'step="any" min="0"')+input("tick-ref","呼値の根拠ID")+input("earnings","次回決算日時（時差付き）")+input("earnings-ref","決算予定の根拠ID")+
        input("financial-period","最新決算の対象期")+input("financial-ref","最新決算の根拠ID")+'</div>'+check("financial-confirm","最新の決算資料であることを確認した")+area("exit","投資前提が崩れた場合の撤退条件（1行1条件）")),
      detail("4. マクロ（順番に確認）",'<div class="j-grid">'+input("sector","① セクター特定")+area("sector-condition","② セクター地合い")+area("drivers","③ 主要ドライバー（カンマ区切り）")+area("sensitivity","④ 当該企業の感応度")+area("specific","⑤ 個別材料")+area("dominance","⑤ セクター要因と個別材料のどちらが強いか")+input("macro-ref","マクロ評価の根拠ID（カンマ区切り）")+'</div>'),
      detail("公開のマクロ資料を取得",'<p class="j-muted">取得した資料はEvidenceへ追加します。企業への影響と強弱比較は上の順番で評価してください。</p><div class="j-actions">'+button("ecb","ECBの為替参考値")+button("fed","米国の金融政策ニュース")+'</div>'),
      detail("5. 判断材料を採点",'<p class="j-muted">将来業績、織り込み、カタリスト、需給、バリュエーション、競争優位などを正本の採点基準で入力します。自動計算項目は手動で上書きしません。</p>'+
        '<p id="j-card-count"></p><div class="j-grid"><label>採点項目<select id="j-card"></select></label><label>該当する基準<select id="j-anchor">'+opt("","未評価")+[1,4,6,8,10].map(x=>opt(x)).join("")+'</select></label></div><div id="j-card-guide"></div>'+
        input("card-refs","根拠ID（カンマ区切り）")+area("reason","採点理由")+area("counter","反証・リスク")+button("save-card","この採点を登録・更新")),
      detail("6. 補足情報の一括読込・詳細入力",'<p class="j-muted">既存の補足JSONに対応。確定分足の根拠、営業日カレンダー、バリュエーション式、Critical / Severe / Warning、定性オーバーライド、Severeの解消条件なども引き継ぎます。</p>'+
        input("metadata-file","補足JSON","file",'accept=".json"')+
        '<div class="j-actions">'+button("show-json","現在の入力を詳細欄に表示")+button("save-input","入力をJSONで保存")+'</div>'+
        area("metadata-json","詳細JSON（読み込んだ後に下のボタンで反映）")+button("apply-json","詳細JSONを入力へ反映")),
      detail("定性評価を外部AIとやり取り",'<p class="j-muted">選択した根拠だけをファイルに出力します。送信は手動です。株価・目標・損切や構造化採点はAIに生成させません。</p>'+input("ai-refs","外部に渡してよい根拠ID（カンマ区切り）")+button("ai-export","定性評価の依頼JSONを保存")+input("ai-file","AIの応答JSON","file",'accept=".json"')+button("ai-import","応答を検証して採点へ反映")),
      '<div class="j-actions">'+button("analyze","2つの時間軸で分析して保存",true)+button("retry","接続を再確認")+'</div><p class="j-muted">分析はログインした本人の履歴へ保存します。情報不足は未評価として表示します。</p></div>',
      detail("Firestoreの分析履歴（最新20件）",button("refresh","履歴を更新")+'<div id="j-history"></div>')
    ].join("");
    const legacy=root.querySelector(".j-inputs");
    const normal=document.createElement("div");normal.className="panel j-inputs";
    normal.innerHTML='<h2>銘柄を判断する</h2><div class="j-grid" id="j-basic"></div><div class="j-actions" id="j-submit"></div>';
    const basic=normal.querySelector("#j-basic");
    basic.append($("symbol").closest("label"),$("securities"),$("entry").closest("label"));
    const action=$("analyze");action.textContent="銘柄を判断する";normal.querySelector("#j-submit").append(action);
    const options=document.createElement("details");options.className="j-detail";
    options.innerHTML='<summary>詳細条件</summary><div class="j-detail-body"></div>';
    options.lastElementChild.append($("policy").closest("label"));normal.append(options);
    const supplement=document.createElement("details");supplement.id="j-supplement";supplement.className="j-detail";supplement.hidden=true;
    supplement.innerHTML='<summary>不足データを補完する</summary><div class="j-detail-body"><p id="j-missing-help"></p>'+
      input("extra-csv","自動取得できなかった日足をCSVで補完","file",'accept=".csv"')+
      '<p class="j-muted">銘柄・日時・OHLCV・価格調整基準を含むCSVに対応します。</p>'+
      area("extra-notes","追加で確認できた情報（資料名・公表日・出典と内容）")+
      input("extra-image","補完画像（PNG/JPEG・6MB以内）","file",'accept="image/png,image/jpeg"')+
      input("extra-image-date","画像を確認・取得した日時","datetime-local")+
      check("extra-image-confirm","画像の銘柄・日時を確認した。口座情報などは含めていない")+
      '<p class="j-muted">画像は根拠として保存します。数値の自動読取りには未対応です。</p>'+
      '<p class="j-muted">補足は根拠として保存します。未確認の事実や採点を自動で確定しません。</p></div>';
    normal.append(supplement);
    legacy.classList.remove("j-inputs");legacy.classList.add("j-development");legacy.hidden=true;
    legacy.before(normal);$("result").hidden=true;
    const historyDetails=$("history").closest("details");historyDetails.querySelector("summary").textContent="判定履歴";
    historyDetails.addEventListener("toggle",()=>{if(historyDetails.open&&!historyDetails.dataset.loaded)work(async()=>{await history();historyDetails.dataset.loaded="true";});});
    $("symbol").addEventListener("keydown",event=>{if(event.key==="Enter"){event.preventDefault();$("analyze").click();}});
    const now=new Date(),past=new Date(now);past.setFullYear(past.getFullYear()-4);
    set("asof",now.toISOString());set("start",past.toISOString().slice(0,10));set("end",now.toISOString().slice(0,10));
    root.querySelector(".j-inputs").addEventListener("input",changed);
    $("symbol").addEventListener("input",()=>{
      const q=val("symbol").normalize("NFKC").toLowerCase();
      $("securities").innerHTML=getSecurities().filter(s=>(s.code+" "+s.name).toLowerCase().includes(q)).slice(0,30).map(s=>opt(s.code+" "+s.name)).join("");
    });
    $("csv").onchange=()=>work(async()=>{const f=$("csv").files[0];if(!f)return;csv=await bytes64(f);$("source").textContent="CSV："+f.name;changed();message("日足CSVを読み込みました。");});
    $("metadata-file").onchange=()=>work(async()=>{const f=$("metadata-file").files[0];if(!f)return;if(f.size>10000000)throw new Error("JSONは10MB以内です。");const m=JSON.parse(await f.text());if(!m||Array.isArray(m)||typeof m!=="object")throw new Error("補足JSONの形式を確認してください。");hydrate(m);message("補足JSONを読み込みました。");});
    $("card").onchange=cardGuide;
    on("retry",async()=>{apiBase="";await connect();});
    on("fetch",async()=>{
      const stock=resolveSymbol(),r=await api("public",{source:"stooq",symbol:stock.code,start:val("start"),end:val("end")});
      csv=r.csv;metadata.price_source=r.source_uri;metadata.public_fetch={source_uri:r.source_uri,raw_hash:r.raw_hash,fetched_at:r.fetched_at};
      $("csv").value="";$("csv-confirm").checked=false;$("source").textContent="取得日時："+r.fetched_at+" / "+r.note;changed();message("公開日足を取得しました。価格調整基準と確定時刻を確認してください。");
    });
    on("add-evidence",async()=>{
      const id=val("ev-id");if(!id||!val("ev-summary")||!val("ev-source")||!val("ev-uri"))throw new Error("根拠ID・資料名・出典・要約を入力してください。");
      const e={evidence_id:id,source_name:val("ev-source"),source_uri:val("ev-uri"),observed_at:val("ev-observed"),
        published_at:val("ev-published"),fetched_at:new Date().toISOString(),summary:val("ev-summary"),source_type:"manual",confidence:0.5,fact_or_interpretation:"fact"};
      metadata.evidence=[...(metadata.evidence||[]).filter(e=>e.evidence_id!==id),e];
      metadata.evidence_quality={...obj(metadata.evidence_quality),[id]:{...obj(metadata.evidence_quality?.[id]),valid_until:val("ev-until")||null,source_quality:val("ev-quality")}};
      changed();evidenceList();message("根拠を登録しました。採点項目にこのIDを指定してください。");
    });
    on("add-image",async()=>{
      const f=$("image").files[0];if(!f)throw new Error("画像を選択してください。");
      const e=await api("image",{image:await bytes64(f),confirmed:checked("image-confirm"),source_name:val("ev-source"),
        observed_at:val("ev-observed"),published_at:val("ev-published"),as_of:val("asof"),summary:val("ev-summary")});
      metadata.evidence=[...(metadata.evidence||[]).filter(x=>x.evidence_id!==e.evidence_id),e];
      metadata.evidence_quality={...obj(metadata.evidence_quality),[e.evidence_id]:{valid_until:val("ev-until")||null,source_quality:"image_verified"}};
      changed();evidenceList();message("画像と目視確認内容を保存しました。");
    });
    for(const source of ["ecb","fed"]) on(source,async()=>{
      const out=await api("public",{source});
      for(const e of out.evidence) metadata.evidence=[...(metadata.evidence||[]).filter(x=>x.evidence_id!==e.evidence_id),e];
      changed();evidenceList();message("公開資料を取得しました。対象日時・鮮度・企業感応度を確認してください。");
    });
    on("ai-export",async()=>{
      const request=await api("ai",{metadata:currentMeta(),selected:refs(val("ai-refs"))});
      download("qualitative-request.json",request);message("定性評価の依頼を保存しました。");
    });
    on("ai-import",async()=>{
      const f=$("ai-file").files[0];if(!f||f.size>10000000)throw new Error("10MB以内の応答JSONを選んでください。");
      const out=await api("ai",{metadata:currentMeta(),selected:refs(val("ai-refs")),response:JSON.parse(await f.text())});
      const codes=new Set(out.assessments.map(x=>x.criterion_id));
      metadata.assessments=[...(metadata.assessments||[]).filter(x=>!codes.has(x.criterion_id)),...out.assessments];
      changed();evidenceList();cardGuide();message("検証済みの定性評価を反映しました。");
    });
    on("save-card",async()=>{
      const id=val("card");if(!id)throw new Error("採点項目を選んでください。");
      metadata.assessments=(metadata.assessments||[]).filter(c=>c.criterion_id!==id);
      if(val("anchor")) metadata.assessments.push({criterion_id:id,anchor:Number(val("anchor")),evidence_ids:refs(val("card-refs")),reason:val("reason"),counter_reason:val("counter"),rule_version:"cards-1.0.0",evaluator:"human"});
      changed();evidenceList();message("採点を反映しました。");
    });
    on("show-json",async()=>{set("metadata-json",JSON.stringify(currentMeta(),null,2));message("現在の補足情報を表示しました。");});
    on("save-input",async()=>download("judgment-input-"+resolveSymbol().code+".json",currentMeta()));
    on("apply-json",async()=>{const m=JSON.parse(val("metadata-json"));if(!m||Array.isArray(m)||typeof m!=="object")throw new Error("JSONオブジェクトを入力してください。");hydrate(m);message("詳細JSONを入力欄へ反映しました。");});
    on("analyze",async()=>{
      const query=val("symbol"),file=$("extra-csv").files[0],picture=$("extra-image").files[0];
      if(!query)throw new Error("日本株の銘柄名または銘柄コードを入力してください。");
      message("株価などを自動取得し、2つの時間軸を確認しています…");
      const payload={symbol:query,entry:val("entry"),policy:val("policy"),
        supplement:{csv:file?await bytes64(file):undefined,notes:val("extra-notes"),
          image:picture?await bytes64(picture):undefined,image_confirmed:checked("extra-image-confirm"),
          image_observed:picture&&val("extra-image-date")?new Date(val("extra-image-date")).toISOString():undefined}};
      const v=inputVersion,response=await api("automatic",payload);
      results=Object.fromEntries(Object.entries(response.results).filter(([h])=>names[h]));recommended=(response.recommended||[]).filter(h=>names[h]);horizon=recommended[0]||"swing";scenario="";resultVersion=v;
      if(!catalog){try{catalog=await api("catalog");}catch{}}
      $("supplement").hidden=false;
      $("missing-help").textContent=(response.missing||[]).join("、");
      if(Object.keys(results).length)renderResult();
      else {
        const horizonScore=h=>{const x=results[h];return x?.scores?.[scenario.split(":")[0]]||x?.scores?.["現値"]||Object.values(x?.scores||{})[0]||{};};
    $("result").hidden=false;
        $("result").innerHTML='<h2>'+esc(response.symbol+" "+response.name)+'</h2><div class="j-verdict"><strong>評価保留</strong></div><p>判断に必要な株価情報を取得できませんでした。</p>'+detail("不足データ",list(response.missing),true);
      }
      message((response.notices?.length?"一部データを自動取得できませんでした。取得済み情報で分析しています。 ":"")+
        (response.saved?"分析結果を履歴に保存しました。":"分析履歴はまだ保存されていません。"));
      $("result").scrollIntoView({behavior:"smooth",block:"start"});
      const hd=$("history").closest("details");delete hd.dataset.loaded;
    });
    on("refresh",history);
    evidenceList();
  }
  async function connect() {
    catalog=await api("catalog");
    $("card").innerHTML=Object.entries(catalog.cards).filter(([k])=>!catalog.automatic_cards.includes(k)).map(([k,c])=>opt(k,k+" "+c.label)).join("");
    cardGuide();message("銘柄判断を利用できます。");await history();
  }
  return {
    open() {if(!mounted) mount(); },
    reset() {generation++;mounted=false;catalog=null;metadata={};csv="";results={};recommended=[];busy=false;inputVersion=0;resultVersion=-1;root.removeAttribute("aria-busy");root.replaceChildren();},
  };
}
