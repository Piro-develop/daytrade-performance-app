import test from "node:test";
import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import vm from "node:vm";
import {afterTaxProfitOf,afterTaxTotalForTrades} from "../profit-display.mjs";

const source=await readFile(new URL("../app.js",import.meta.url),"utf8");
const styles=await readFile(new URL("../styles.css",import.meta.url),"utf8");
const slice=(start,end)=>source.slice(source.indexOf(start),source.indexOf(end));
const yen=value=>`${value}円`;
const dates=["2026-08-31","2026-09-01","2026-09-20","2026-09-21","2026-09-24","2026-09-25","2026-09-26","2026-09-30","2026-10-01"];
const trades=dates.map((date,i)=>({id:`t${i}`,date,code:i===4?"4461":"9449",name:"検証銘柄",action:i===3?"買付":"売却",accountType:"信用",price:100,realisedProfit:i===3?null:i===5?-200:1000,brokerActuals:i===4?{settlement:700}:null}));
const ledger={calculated:trades};
function setup(){
 const nodes=new Map();
 const $=selector=>{
  if(!nodes.has(selector)) nodes.set(selector,{innerHTML:"",textContent:"",events:{},addEventListener(name,fn){this.events[name]=fn;}});
  return nodes.get(selector);
 };
 const state={pnlPeriod:"all",pnlSelections:{day:"2026-09-24",week:"2026-09-21",month:"2026-09"},recordQuery:"",recordSecurityCode:null,trades};
 const context=vm.createContext({state,$,yen,afterTaxProfitOf,afterTaxTotalForTrades,Date,
  localDate:(date=new Date())=>`${date.getFullYear()}-${String(date.getMonth()+1).padStart(2,"0")}-${String(date.getDate()).padStart(2,"0")}`,
  PNL_WEEK_START:"2026-07-20",PNL_MONTH_START:"2026-07",PNL_HISTORY_START:"2026-07-01",
  recordSecurityCandidates:()=>[],securityMatchesSearch:(trade,query)=>!query||trade.code.includes(query),
  byTimeAsc:(a,b)=>a.date.localeCompare(b.date),esc:value=>String(value),accountTypeOf:trade=>trade.accountType,accountDetailLabel:()=>"信用",
  renderRecordSearchOptions:()=>{},calculateLedger:()=>ledger});
 vm.runInContext(slice("function parseLocalDate","function recordSecurityCandidates")+slice("function renderRecordSearchResults","function renderAnalytics"),context);
 return {state,$,render:()=>context.renderRecords(ledger)};
}

test("全期間・日・既存の月曜〜金曜・月・0件で期間損益と一覧が同時に一致し累計は不変",()=>{
 const {state,$,render}=setup();
 const before=JSON.stringify(trades);
 let cumulative;
 for(const [period,ids,label] of [["all",[0,1,2,3,4,5,6,7,8],"全期間"],["day",[4],"2026/9/24"],["week",[3,4,5],"9/21（月）〜9/25（金）"],["month",[1,2,3,4,5,6,7],"2026年9月1日〜30日"],["day",[],"2026/9/29"]]){
  state.pnlPeriod=period;
  if(!ids.length) state.pnlSelections.day="2026-09-29";
  render();
  const html=$("#records-view").innerHTML;
  const firstCard=html.match(/<article class="pnl-card">.*?<\/article>/s)[0];
  cumulative??=firstCard;
  assert.equal(firstCard,cumulative);
  assert.ok(html.includes(label));
  assert.equal(html.includes('id="pnl-period-picker"'),period!=="all");
  assert.deepEqual([...html.matchAll(/data-period="(.*?)"/g)].map(m=>m[1]),["all","day","week","month"]);
  const listed=[...$("#record-groups").innerHTML.matchAll(/data-id="t(\d+)"/g)].map(m=>Number(m[1]));
  assert.deepEqual(listed,ids.toReversed());
  const sales=ids.map(i=>trades[i]).filter(t=>t.action==="売却");
  const expected=afterTaxTotalForTrades(sales);
  assert.equal($("#record-period-profit").textContent,yen(expected));
  assert.equal($("#record-period-tax-before").textContent,`（税引前 ${yen(sales.reduce((sum,t)=>sum+t.realisedProfit,0))}）`);
  assert.ok($("#record-result-summary").innerHTML.includes(yen(expected)));
  if(!ids.length) assert.ok($("#record-groups").innerHTML.includes("この期間の取引はありません"));
 }
 assert.equal(JSON.stringify(trades),before);
});

test("対象日の変更と銘柄検索も期間損益・一覧を一緒に更新する",()=>{
 const {state,$,render}=setup();
 state.pnlPeriod="day";
 render();
 $("#pnl-period-picker").events.change({target:{value:"2026-09-25"}});
 assert.equal($("#record-period-profit").textContent,"-200円");
 assert.ok($("#record-groups").innerHTML.includes('data-id="t5"'));
 assert.ok($("#records-view").innerHTML.includes("2026/9/25"));
 state.pnlPeriod="month";
 render();
 $("#record-search").events.input({currentTarget:{value:"4461"}});
 assert.equal($("#record-period-profit").textContent,"700円");
 assert.equal([...$("#record-groups").innerHTML.matchAll(/data-id=/g)].length,1);
 assert.ok($("#record-groups").innerHTML.includes('data-id="t4"'));
 assert.match(source,/action === "pnl-period"[^\n]*renderRecords\(calculateLedger\(state.trades\)\)/);
});

test("スマホの期間切替は縮小可能な4等分でラベルを折り返さない",()=>{
 assert.match(styles,/\.pnl-period-switch\{[^}]*grid-template-columns:repeat\(4,minmax\(0,1fr\)\)/);
 assert.match(styles,/\.pnl-period-switch button\{[^}]*min-width:0;[^}]*white-space:nowrap;/);
});
