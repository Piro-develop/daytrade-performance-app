import assert from "node:assert/strict";
import {buildChatGPTText,entryStrategiesHtml} from "../judgment.mjs";
const r={
 symbol:"4461",name:"第一工業製薬",as_of:"2026-09-22T10:00:00+09:00",
 metadata:{secret:"PRIVATE_TEST",exit_conditions:["会社計画撤回時に再評価"],screening:{label:"要確認",daily_state:"混在",
 facts:["売上高: 100百万円"],chatgpt_checks:["市場期待"]}},
 scores:{"現値":{investment:7,entry:6,coverage:.5,entry_coverage:.8,items:{}}},
 technical:{daily:[{close:100,ma13:99}],weekly:[{ma13:90}],weekly_trend:"上昇",
 bands:[{band_id:"INTERNAL_SUPPORT_ID",low:80,high:85}]},
 plans:[{kind:"現値",entry:100,target1:120,target2:130,alert:85,stop1:79,stop2:70,rr:20/21,
 support_id:"INTERNAL_SUPPORT_ID",invalidation:"支持帯 INTERNAL_SUPPORT_ID を割る",expires_at:"2026-09-23"}],
 findings:[{code:"INTERNAL_FINDING",severity:"Warning",reason:"決算予定未確認",evidence_ids:["PRIVATE_REF"]}],
 evidence:{"PRIVATE_REF":{summary:"PRIVATE_TEST"}}
};
const out=buildChatGPTText({swing:r,midlong:structuredClone(r)});
for(const expected of ["一次判定：要確認","一次定量評価：7.0","coverage 50%","スイング","中長期","Entry品質：6.0",
 "第1利確：120","通常損切：79","支持帯 80〜85","会社計画撤回","市場期待","決算予定未確認"]) assert.ok(out.includes(expected),expected);
for(const forbidden of ["PRIVATE_TEST","PRIVATE_REF","INTERNAL_SUPPORT_ID","INTERNAL_FINDING","NaN","undefined"])
 assert.ok(!out.includes(forbidden),forbidden);
assert.equal(buildChatGPTText({swing:{metadata:{}}}),"");
console.log("ChatGPT copy: required data present, internal IDs and private fields excluded");

r.plans.push({...r.plans[0],kind:"第1押し目",entry:85,stop1:79,target1:100,rr:2.5,support_low:80,support_high:85,support_basis:["25日線","直近安値"],rr_evaluation:"良好"},
 {...r.plans[0],kind:"第2押し目",entry:70,stop1:65,target1:79,rr:1.8,support_low:66,support_high:70,support_basis:["13週線","過去反発帯"],rr_evaluation:"許容"});
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
 const result={...r,symbol,plans:[{kind,entry,target1,target2,stop1,stop2,rr:2}]};
 const before=JSON.stringify(result);
 for(const output of [entryStrategiesHtml(result),buildChatGPTText({swing:result})]){
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
