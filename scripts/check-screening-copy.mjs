import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {buildChatGPTText,entryStrategiesHtml,visibleEntryPlans} from "../judgment.mjs";
if(process.argv[2]) {
 const results=JSON.parse(readFileSync(process.argv[2],"utf8"));
 for(const [h,r] of Object.entries(results)) {
  const visible=visibleEntryPlans(r),html=entryStrategiesHtml(r);
  const copy=buildChatGPTText({[h]:r});
  const entryCopy=copy.split("### Entry戦略")[1].split("投資前提崩れ：")[0];
  assert.equal(visible.length,(r.plans||[]).filter(p=>p.eligible).length);
  for(const p of r.plans||[]) {
   if(!p.eligible){ assert.ok(!html.includes('<h3>'+ (p.kind==='現値'?'現値Entry':p.kind)+'</h3>'));assert.ok(!entryCopy.includes('#### '+(p.kind==='現値'?'現値Entry':p.kind))); }
  }
  if(!visible.length){assert.ok(html.includes('見送り'));assert.ok(entryCopy.includes('見送り'));assert.ok(!entryCopy.includes('第1利確：'));}
  console.log(JSON.stringify({symbol:r.symbol,horizon:h,visible_entries:visible.map(p=>({kind:p.kind,entry:p.entry,upside:p.first_target_upside_pct,rr:p.rr})),price_strategy:visible.length?'候補あり':'見送り'}));
 }
 process.exit(0);
}
const r={
 symbol:"4461",name:"第一工業製薬",as_of:"2026-09-22T10:00:00+09:00",
 metadata:{secret:"PRIVATE_TEST",exit_conditions:["会社計画撤回時に再評価"],screening:{label:"要確認",daily_state:"混在",
 facts:["売上高: 100百万円"],chatgpt_checks:["市場期待"]}},
 scores:{"現値":{investment:7,entry:6,coverage:.5,entry_coverage:.8,items:{}}},
 technical:{daily:[{close:100,ma13:99}],weekly:[{ma13:90}],weekly_trend:"上昇",
 bands:[{band_id:"INTERNAL_SUPPORT_ID",low:80,high:85}]},
 plans:[{kind:"現値",entry:100,target1:130,target2:140,alert:85,stop1:79,stop2:70,rr:30/21,
 support_id:"INTERNAL_SUPPORT_ID",invalidation:"支持帯 INTERNAL_SUPPORT_ID を割る",expires_at:"2026-09-23"}],
 findings:[{code:"INTERNAL_FINDING",severity:"Warning",reason:"決算予定未確認",evidence_ids:["PRIVATE_REF"]}],
 evidence:{"PRIVATE_REF":{summary:"PRIVATE_TEST"}}
};
const out=buildChatGPTText({swing:r,midlong:structuredClone(r)});
for(const expected of ["一次判定：要確認","一次定量評価：7.0","coverage 50%","スイング","中長期","Entry品質：6.0",
 "第1利確：130","通常損切：79","支持帯 80〜85","会社計画撤回","市場期待","決算予定未確認"]) assert.ok(out.includes(expected),expected);
for(const forbidden of ["PRIVATE_TEST","PRIVATE_REF","INTERNAL_SUPPORT_ID","INTERNAL_FINDING","NaN","undefined"])
 assert.ok(!out.includes(forbidden),forbidden);
assert.equal(buildChatGPTText({swing:{metadata:{}}}),"");
console.log("ChatGPT copy: required data present, internal IDs and private fields excluded");

r.plans.push({...r.plans[0],kind:"第1押し目",entry:95,stop1:89,target1:110,rr:2.5,support_low:90,support_high:95,support_basis:["25日線","直近安値"],rr_evaluation:"良好"},
 {...r.plans[0],kind:"第2押し目",entry:90,stop1:84,target1:100,rr:10/6,support_low:86,support_high:90,support_basis:["13週線","過去反発帯"],rr_evaluation:"許容"});
const comparison=buildChatGPTText({swing:r});
const html=entryStrategiesHtml(r);
for(const label of ["現値Entry","第1押し目","第2押し目","25日線","13週線","良好","許容"]) {
 assert.ok(comparison.includes(label),label);assert.ok(html.includes(label),label);
}
assert.ok(!comparison.includes("INTERNAL_SUPPORT_ID"));
assert.ok(!html.includes("INTERNAL_SUPPORT_ID"));
console.log("All available Entry scenarios appear in copy and comparison UI");

// Prices from the 2026-09-24 actual-data checks; validate each scenario's own base.
const priceCases=[
 ["4461","現値",13860,15890,null,13410,12910,["+14.65%",null,"-3.25%","-6.85%"]],
 ["4461","第1押し目",13600,15890,null,13410,12910,["+16.84%",null,"-1.40%","-5.07%"]],
 ["4461","第2押し目",13100,13490,15890,12910,12710,["+2.98%","+21.30%","-1.45%","-2.98%"]],
 ["9449","現値",3919,3976,3994,3889,3865,["+1.45%","+1.91%","-0.77%","-1.38%"]],
 ["9449","第1押し目",3912,3976,3994,3889,3865,["+1.64%","+2.10%","-0.59%","-1.20%"]],
 ["9449","第2押し目",3881,3899,3976,3865,3820,["+0.46%","+2.45%","-0.41%","-1.57%"]],
];
for(const [symbol,kind,entry,target1,target2,stop1,stop2,rates] of priceCases){
 const result={...r,symbol,metadata:{...r.metadata,automatic:{current_quote:{price:symbol==="4461"?13860:3919}}},plans:[{kind,entry,target1,target2,stop1,stop2,rr:2}]};
 const before=JSON.stringify(result);
 for(const output of [entryStrategiesHtml(result),buildChatGPTText({swing:result})]){
  if(!visibleEntryPlans(result).length) {assert.ok(output.includes("見送り"));assert.ok(!output.includes("円（"));continue;}
  [target1,target2,stop1,stop2].forEach((price,i)=>{
   const expected=price==null?"該当なし":price.toLocaleString("ja-JP")+"円（"+rates[i]+"）";
   assert.ok(output.includes(expected),symbol+" "+kind+" "+expected);
  });
 }
 assert.equal(JSON.stringify(result),before,"Display must not mutate stored results");
}
const edge={...r,plans:[{kind:"現値",entry:100,target1:100.001,target2:null,stop1:99.999,stop2:null,rr:1}]};
for(const entry of [100,0,null]){
 edge.plans[0].entry=entry;
 for(const output of [entryStrategiesHtml(edge),buildChatGPTText({swing:edge})]){
  assert.ok(!/（[^）]*%）/.test(output),"No rounded zero or invalid-base percentage");
  assert.ok(!/NaN|Infinity/.test(output));
 }
}
console.log("4461 / 9449: all three scenario percentages, missing values and unchanged data passed");

const rejected={...r,plans:[{...r.plans[0],entry:1000,target1:1001,stop1:999.5,rr:2,
 eligible:false,first_target_upside_pct:.1,entry_reason:"上昇余地0.1%は5%以下のため不足"}]};
for(const output of [entryStrategiesHtml(rejected),buildChatGPTText({swing:rejected})]){
 assert.ok(output.includes("見送り"));
 assert.ok(!output.includes("上昇余地0.1%は5%以下のため不足"));
 assert.ok(!output.includes("1,001円"));
 assert.ok(!output.includes("採用候補・"));
}
console.log("Tiny upside remains rejected in UI and copy even with RR 2");

const abeja={...r,symbol:"5574",metadata:{...r.metadata,automatic:{current_quote:{price:3035}}},
 plans:[{kind:"現値",entry:3035,target1:3050,stop1:3025,rr:1.5,eligible:false},
 {kind:"第1押し目",entry:2065,target1:2300,stop1:2045,rr:11.75,eligible:true},
 {kind:"第2押し目",entry:1553,target1:1800,stop1:1543,rr:24.7,eligible:true}]};
for(const output of [entryStrategiesHtml(abeja),buildChatGPTText({swing:abeja})]) {
 assert.ok(output.includes("見送り"));
 for(const price of ["2,065円","1,553円","3,050円"]) assert.ok(!output.includes(price));
 assert.ok(!output.includes("#### 現値Entry"));
}
const boundary={...abeja,plans:[{kind:"第1押し目",entry:2850,target1:2992.5,stop1:2800,rr:2.85}]};
assert.equal(visibleEntryPlans(boundary).length,1);
const valid={...abeja,plans:[{kind:"第1押し目",entry:2850,target1:3020,stop1:2790,rr:170/60}]};
assert.equal(visibleEntryPlans(valid).length,1);
assert.ok(entryStrategiesHtml(valid).includes("2,850円"));
console.log("ABEJA deep plans and rejected current hidden; 5% boundary and valid nearby Entry shown");
