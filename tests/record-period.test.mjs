import test from "node:test";
import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import vm from "node:vm";
import {afterTaxProfitOf,afterTaxTotalForTrades} from "../profit-display.mjs";
import {calculateAnnualTaxEstimates} from "../tax-calculation.mjs";

const source=await readFile(new URL("../app.js",import.meta.url),"utf8");
const styles=await readFile(new URL("../styles.css",import.meta.url),"utf8");
const slice=(start,end)=>source.slice(source.indexOf(start),source.indexOf(end));
const yen=value=>`${value}円`;
const dates=["2026-08-31","2026-09-01","2026-09-20","2026-09-21","2026-09-24","2026-09-25","2026-09-26","2026-09-30","2026-10-01"];
const trades=dates.map((date,i)=>({id:`t${i}`,date,code:i===4?"4461":"9449",name:"検証銘柄",action:i===3?"買付":"売却",accountType:"信用",price:100,realisedProfit:i===3?null:i===5?-200:1000,brokerActuals:i===4?{settlement:700}:null}));
function setup(inputTrades=trades){
 const ledger={calculated:inputTrades};
 const nodes=new Map();
 const $=selector=>{
  if(!nodes.has(selector)) nodes.set(selector,{innerHTML:"",textContent:"",events:{},addEventListener(name,fn){this.events[name]=fn;}});
  return nodes.get(selector);
 };
 const state={recordFilters:{style:"all",accountType:"all"},pnlPeriod:"all",pnlSelections:{day:"2026-09-24",week:"2026-09-21",month:"2026-09"},recordQuery:"",recordSecurityCode:null,trades:inputTrades};
 const context=vm.createContext({state,$,yen,afterTaxProfitOf,afterTaxTotalForTrades,Date,calculateAnnualTaxEstimates,hasOwn:(object,key)=>Object.hasOwn(object,key),
  localDate:(date=new Date())=>`${date.getFullYear()}-${String(date.getMonth()+1).padStart(2,"0")}-${String(date.getDate()).padStart(2,"0")}`,
  PNL_WEEK_START:"2026-07-20",PNL_MONTH_START:"2026-07",PNL_HISTORY_START:"2026-07-01",
  recordSecurityCandidates:()=>[],securityMatchesSearch:(trade,query)=>!query||trade.code.includes(query),
  byTimeAsc:(a,b)=>a.date.localeCompare(b.date),esc:value=>String(value),accountTypeOf:trade=>trade.accountType,accountDetailLabel:()=>"信用",
  renderRecordSearchOptions:()=>{},calculateLedger:()=>ledger});
 vm.runInContext(slice("function summaryPeriodStart","function statsFor")+slice("function parseLocalDate","function recordSecurityCandidates")+slice("function renderRecordSearchResults","function renderAnalytics"),context);
 return {state,$,context,render:()=>context.renderRecords(ledger)};
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

test("期間・スタイル・区分の36通りで対象一覧と損益が一致し累計と元データは変わらない",()=>{
 const sample=[
  {id:"t0",date:"2026-08-31",style:"デイトレ",accountType:"現物",realisedProfit:10000},
  {id:"t1",date:"2026-09-21",style:"デイトレ",accountType:"現物",realisedProfit:1000},
  {id:"t2",date:"2026-09-24",style:"スイング",accountType:"現物",realisedProfit:-300},
  {id:"t3",date:"2026-09-25",style:"デイトレ",accountType:"信用",realisedProfit:2000,brokerActuals:{settlement:1600}},
  {id:"t4",date:"2026-09-30",style:"スイング",accountType:"信用",realisedProfit:-500,brokerActuals:{settlement:-400}},
  {id:"t5",date:"2026-10-01",style:"スイング",accountType:"信用",realisedProfit:5000},
  {id:"t6",date:"2026-09-24",style:"スイング",accountType:"現物",realisedProfit:null,action:"買付"}
 ].map(t=>({action:"売却",code:t.id==="t2"?"4461":"9449",name:"条件検証",price:100,...t}));
 const before=JSON.stringify(sample);
 const {state,$,render}=setup(sample);
 const periods={all:[0,1,2,3,4,5,6],day:[2,6],week:[1,2,3,6],month:[1,2,3,4,6]};
 const styles={all:[0,1,2,3,4,5,6],デイトレ:[0,1,3],スイング:[2,4,5,6]};
 const accounts={all:[0,1,2,3,4,5,6],現物:[0,1,2,6],信用:[3,4,5]};
 let cumulative;
 for(const [period,periodIds] of Object.entries(periods)) for(const [style,styleIds] of Object.entries(styles)) for(const [accountType,accountIds] of Object.entries(accounts)) {
  state.pnlPeriod=period;state.recordFilters={style,accountType};render();
  const ids=periodIds.filter(i=>styleIds.includes(i)&&accountIds.includes(i));
  const listed=[...$("#record-groups").innerHTML.matchAll(/data-id="t(\d+)"/g)].map(m=>Number(m[1])).sort();
  assert.deepEqual(listed,ids,`${period}/${style}/${accountType}`);
  const sales=ids.map(i=>sample[i]).filter(t=>t.action==="売却");
  assert.equal($("#record-period-profit").textContent,yen(afterTaxTotalForTrades(sales)));
  assert.equal($("#record-period-tax-before").textContent,`（税引前 ${yen(sales.reduce((sum,t)=>sum+t.realisedProfit,0))}）`);
  assert.ok($("#record-result-summary").innerHTML.includes(`${ids.length}件`));
  const card=$("#records-view").innerHTML.match(/<article class="pnl-card">.*?<\/article>/s)[0];
  cumulative??=card;assert.equal(card,cumulative);
 }
 assert.equal(JSON.stringify(sample),before);
});

test("混在した信用返済も選択スタイル分だけを集計しサマリと一致する",()=>{
 const mixed={id:"mixed",date:"2026-09-24",code:"4461",name:"混在",action:"売却",accountType:"信用",style:"スイング",price:100,realisedProfit:1000,styleProfits:{デイトレ:1500,スイング:-500},brokerActuals:{settlement:700}};
 const {state,$,context,render}=setup([mixed]);
 const before=JSON.stringify(mixed);
 for(const [style,profit] of [["デイトレ",1500],["スイング",-500]]) {
  state.recordFilters={style,accountType:"信用"};
  state.summaryFilters={period:"all",style,accountType:"信用"};
  render();
  assert.equal($("#record-period-tax-before").textContent,`（税引前 ${profit}円）`);
  const summary=context.completedForSummary([mixed]);
  assert.equal(summary[0].realisedProfit,profit);
  assert.equal($("#record-period-profit").textContent,yen(afterTaxTotalForTrades(summary)));
  assert.ok($("#record-groups").innerHTML.includes(`（税引前 ${profit}円）`));
  assert.ok($("#record-groups").innerHTML.includes('data-id="mixed"'));
 }
 assert.equal(JSON.stringify(mixed),before);
});

test("銘柄検索とクリアは取引条件を保ち0件でも損益と件数が一致する",()=>{
 const sample=trades.map((t,i)=>({...t,style:i%2?"デイトレ":"スイング"}));
 const {state,$,render}=setup(sample);
 state.recordFilters={style:"スイング",accountType:"信用"};
 state.pnlPeriod="month";render();
 $("#record-search").events.input({currentTarget:{value:"存在しない銘柄"}});
 assert.equal($("#record-period-profit").textContent,"0円");
 assert.ok($("#record-result-summary").innerHTML.includes("0件"));
 assert.ok($("#record-groups").innerHTML.includes("選択した条件に該当する取引はありません"));
 $("#record-search").events.input({currentTarget:{value:"4461"}});
 assert.ok($("#record-groups").innerHTML.includes('data-id="t4"'));
 assert.equal($("#record-period-profit").textContent,"700円");
 $("#record-search").events.input({currentTarget:{value:""}});
 assert.equal(state.pnlPeriod,"month");
 assert.deepEqual(state.recordFilters,{style:"スイング",accountType:"信用"});
 const listed=[...$("#record-groups").innerHTML.matchAll(/data-id="t(\d+)"/g)].map(m=>Number(m[1]));
 assert.deepEqual(listed,[6,4,2]);
});
