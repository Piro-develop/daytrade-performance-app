from __future__ import annotations
from datetime import datetime, time, timedelta
from dataclasses import replace
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from .models import Band, Bundle, EntryPlan, digest, time_value, JST

D = lambda value: Decimal(str(value))

def rr(entry, target, stop) -> Decimal | None:
    e,t,s = D(entry),D(target),D(stop)
    return (t-e)/(e-s) if s < e < t else None

def rr_bucket(value: Decimal, cfg: dict) -> str:
    return ("良好" if value >= D(cfg["rr_good"]) else "許容" if value >= D(cfg["rr_conditional"])
            else "最低限／要確認" if value >= D(cfg.get("rr_minimum",1.3)) else "Entry改善待ち")

def rounded(value, tick, up=False):
    return (D(value)/D(tick)).to_integral_value(rounding=ROUND_CEILING if up else ROUND_FLOOR) * D(tick)

def make_plan(entry, target, stop, *, kind="現値", support_id="", resistance_id="",
              evidence_ids=(), expires_at="", target2=None, stop2=None, alert=None,
              trigger_confirmed=False) -> EntryPlan | None:
    value = rr(entry,target,stop)
    if value is None:
        return None
    fields = [str(entry),str(target),str(stop),kind,support_id,resistance_id]
    return EntryPlan(digest(fields)[:16],kind,D(entry),D(target),D(stop),value,
        D(target2) if target2 is not None and D(target2)>=D(target) else None,
        D(stop2) if stop2 is not None and D(stop2)<D(stop) else None,
        D(alert) if alert is not None and D(stop)<D(alert)<D(entry) else None,
        support_id,resistance_id,tuple(evidence_ids),
        f"支持帯 {support_id} を割り、想定価格構造が否定された場合に再評価",expires_at,trigger_confirmed)

def plans_for(bundle: Bundle, technical: dict, cfg: dict, specified_entry=None) -> list[EntryPlan]:
    if not technical["tick_valid"]:
        return []
    tick = D(bundle.metadata["tick_size"])
    schedule=bundle.metadata.get("tick_schedule",[])
    def step(value):
        return next((D(row["tick"]) for row in schedule if row["up_to"] is None or D(value)<=D(row["up_to"])),tick)
    def round_price(value,up=False):
        # Recheck a band boundary crossed by upward rounding.
        result=rounded(value,step(value),up)
        return rounded(result,step(result),up)
    market = D(technical["latest"])
    current = round_price(specified_entry if specified_entry is not None else market,True)
    strong = [b for b in technical["bands"] if b.strength >= cfg["strong_band"]]
    supports = sorted([b for b in strong if D(b.high) < current], key=lambda b:b.high,reverse=True)
    resistances = sorted([b for b in strong if D(b.low) > current],key=lambda b:b.low)
    expires = time_value(bundle.as_of)+timedelta(hours=cfg["plan_valid_hours"])
    local_day = time_value(bundle.as_of).astimezone(JST).date().isoformat()
    next_sessions = sorted(day for day in bundle.metadata.get("calendar", []) if day > local_day)
    if next_sessions:
        expires = datetime.combine(datetime.fromisoformat(next_sessions[0]).date(),time(15,30),JST)
    earnings_at = bundle.metadata.get("earnings_at")
    if earnings_at and time_value(earnings_at)>time_value(bundle.as_of):
        expires = min(expires,time_value(earnings_at))
    def build(entry, support, kind, confirmed=False):
        # Each adopted support determines its own stop before targets or RR are inspected.
        buffer = max(step(support.low)*D(cfg["stop_buffer_ticks"]),
                     D(technical["atr"] or 0)*D(cfg["stop_buffer_atr"]))
        stop = round_price(D(support.low)-buffer)
        above = sorted([b for b in strong if b.band_id!=support.band_id and D(b.low)>entry],key=lambda b:b.low)
        below = (supports[1:] if kind in ("現値","指定価格") else
                 sorted([b for b in supports if D(b.high)<D(support.low)],key=lambda b:b.high,reverse=True))
        if not above: return None
        target = round_price(D(above[0].low)-step(D(above[0].low)-D("0.000001")))
        target2 = round_price(D(above[1].low)-step(D(above[1].low)-D("0.000001"))) if len(above)>1 else None
        stop2 = round_price(D(below[0].low)-buffer) if below else None
        refs=tuple(sorted({r for band in [support]+below[:1]+above[:2] for r in band.evidence_ids} |
                         {technical["technical_evidence_id"],bundle.metadata["tick_evidence_id"]}))
        plan=make_plan(entry,target,stop,kind=kind,support_id=support.band_id,resistance_id=above[0].band_id,
                       evidence_ids=refs,expires_at=expires.isoformat(),target2=target2,stop2=stop2,
                       alert=round_price(support.high),trigger_confirmed=confirmed)
        if plan is None: return None
        basis=tuple(getattr(support,"basis",()))
        if getattr(support,"reactions",0)>0: basis+=("過去反発・反応 "+str(support.reactions)+"回",)
        return replace(plan,support_low=support.low,support_high=support.high,support_basis=basis,
                       rr_evaluation=rr_bucket(plan.rr,cfg))

    plans=[]
    if supports and resistances:
        support=supports[0]
        daily=technical["daily"]
        bounce=len(daily)>1 and daily.iloc[-2].low<=support.high and daily.iloc[-1].close>support.high
        breaking=len(daily)>1 and any(daily.iloc[-2].close<=b.high<daily.iloc[-1].close for b in strong if b.band_id!=support.band_id)
        retest=len(daily)>1 and daily.iloc[-2].close>support.high and daily.iloc[-1].low<=support.high and daily.iloc[-1].close>=support.high
        kind="指定価格" if specified_entry is not None and current!=market else "現値"
        first=build(current,support,kind,bool(kind=="現値" and (bounce or breaking or retest)))
        if first: plans.append(first)

    # Disjoint clusters, nearest first. No RR-target search or isolated MA selection.
    selected=[]
    for support in supports:
        families=getattr(support,"families",())
        if not (len(families)>1 or "price_structure" in families or "volume_profile" in families or getattr(support,"reactions",0)>0): continue
        entry=round_price(support.high,True)
        if entry>=current: continue
        if selected and (D(support.high)>=D(selected[-1].support_low) or entry>=selected[-1].entry): continue
        candidate=build(entry,support,"第"+str(len(selected)+1)+"押し目")
        if candidate: selected.append(candidate)
        if len(selected)==2: break
    return plans+selected
