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
