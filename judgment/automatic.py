"""Public, bounded acquisition for the normal symbol-only workflow. No AI scoring."""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
import csv
from datetime import datetime,timezone,date
from io import BytesIO,StringIO
import json,math,re,threading,unicodedata,zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
import requests
from investment_app.models import InputError,Evidence,plain,digest,JST
from investment_app.public_data import PublicContextProvider
from .price_sources import chart as _chart, normalize_chart, download
from .public_facts import PublicFactsProvider

JPX_LIST="https://www.jpx.co.jp/markets/statistics-equities/misc/tvdivq0000001vg2-att/data_j.xlsx"
JPX_TICKS="https://www.jpx.co.jp/equities/trading/domestic/07.html"
JPX_HOURS="https://www.jpx.co.jp/equities/trading/domestic/01.html"
_cache={};_lock=threading.Lock()
TICKS=[(1000,.1,1),(3000,.5,1),(5000,1,5),(10000,1,10),(30000,5,10),(50000,10,50),(100000,10,100),(300000,50,100),(500000,100,500),(1000000,100,1000),(3000000,500,1000),(5000000,1000,5000),(10000000,1000,10000),(30000000,5000,10000),(50000000,10000,50000),(None,10000,100000)]

def reference_rows(raw):
    ns={"s":"http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(BytesIO(raw)) as z:
        if sum(i.file_size for i in z.infolist())>30_000_000:raise ValueError("workbook limit")
        strings=["".join(e.itertext()) for e in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("s:si",ns)]
        rows=[]
        for row in ET.fromstring(z.read("xl/worksheets/sheet1.xml")).findall(".//s:row",ns):
            values={}
            for cell in row:
                v=cell.find("s:v",ns);v=v.text if v is not None else ""
                values[re.sub("[0-9]","",cell.get("r",""))]=strings[int(v)] if cell.get("t")=="s" and v else v
            if re.fullmatch("[0-9][0-9A-Z]{3}",values.get("B","")) and "内国株式" in values.get("D",""):
                rows.append({"code":values["B"],"name":values.get("C",""),"sector":values.get("F",""),
                             "size":values.get("J",""),"as_of":values.get("A","")})
        if not rows:raise ValueError("empty domestic equities")
        return rows

def company_reference():
    now=datetime.now(timezone.utc)
    with _lock:
        cached=_cache.get("jpx")
        if cached and (now-cached[0]).total_seconds()<21600:return cached[1]
    raw=download(JPX_LIST);result=(reference_rows(raw),digest(raw.hex()),now.isoformat())
    with _lock:_cache["jpx"]=(now,result)
    return result

def normalize_query(value):
    return re.sub(r"\s+","",unicodedata.normalize("NFKC",str(value))).casefold()

def resolve(query,rows):
    q=normalize_query(query);code=re.match(r"^([0-9][0-9a-z]{3})(?:$|[^0-9a-z])",unicodedata.normalize("NFKC",str(query)).casefold())
    matches=[r for r in rows if normalize_query(r["code"])==(code[1] if code else q) or normalize_query(r["name"])==q]
    if len(matches)==1:return matches[0]
    matches=[r for r in rows if q and q in normalize_query(r["name"])]
    if len(matches)==1:return matches[0]
    if matches:raise InputError("候補が複数あります。銘柄コードを指定してください。")
    if re.fullmatch("[0-9][0-9A-Za-z]{3}",str(query).strip()):return {"code":str(query).upper(),"name":str(query).upper()}
    raise InputError("日本株の銘柄名または4桁の銘柄コードを確認してください。")

def evidence(eid,source,url,stamp,summary,hash_value=None,observed=None,published=None):
    return plain(Evidence(eid,source,url,observed or stamp,published or stamp,stamp,summary,hash_value or digest(summary),"public",.8))

def chart(symbol,interval):
    return _chart(symbol,interval,fetch=download)

def csv_bytes(rows):
    out=StringIO();writer=csv.DictWriter(out,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    return out.getvalue().encode()

def acquire(query,now=None):
    notices=[];reference=None
    try:reference=company_reference();stocks=reference[0]
    except (requests.RequestException,ValueError,KeyError,zipfile.BadZipFile,ET.ParseError,IndexError):
        stocks=json.loads((Path(__file__).resolve().parents[1]/"stocks.json").read_text(encoding="utf-8"))["securities"]
        notices.append("業種と呼値区分の最新情報を取得できませんでした。")
    stock=resolve(query,stocks);symbol=stock["code"]
    with ThreadPoolExecutor(max_workers=3) as pool:
        jobs={key:pool.submit(fn) for key,fn in {
            "daily":lambda:chart(symbol,"1d"),
            "macro":lambda:PublicContextProvider().fetch("ecb"),
            "facts":lambda:PublicFactsProvider().fetch(symbol,now or datetime.now(timezone.utc))}.items()}
        received={}
        for key,job in jobs.items():
            try:received[key]=job.result()
            except (requests.RequestException,InputError,ValueError,KeyError,TypeError,IndexError):
                notices.append({"daily":"日足株価","macro":"為替参考値","facts":"企業公開情報"}[key]+"を自動取得できませんでした。")
    asof=now or datetime.now(timezone.utc);stamp=asof.isoformat()
    meta={"symbol":symbol,"name":stock["name"],"as_of":stamp,"evidence":[],"assessments":[],
          "macro":{"sector":stock.get("sector","")},"automatic":{"notices":notices,"assessment_provider":"unconfigured"},
          "is_demo":False}
    output={"symbol":symbol,"name":stock["name"],"as_of":stamp,"metadata":meta,"notices":notices,"csv":None}
    for key,interval in (("daily","1d"),):
        if key not in received:continue
        data,url,hash_value=received[key]
        try:rows,omitted=normalize_chart(data,symbol,interval,asof)
        except (ValueError,KeyError,TypeError):
            notices.append("日足の確定データが不足しています。");continue
        eid="public-"+key+"-"+hash_value[:16]
        meta["automatic"]["price_evidence_id"]=eid
        meta["evidence"].append(evidence(eid,data.get("meta",{}).get("source","Yahoo Finance 公開株価"),url,stamp,
            (data.get("meta",{}).get("source_note") or "Yahoo分割調整済み価格。配当調整終値をOHLCへ混在させない。")+
            " 確定日足。"+f" {len(rows)}本",hash_value,observed=rows[-1]["timestamp"],published=stamp))
        if data.get("meta",{}).get("provider")=="minkabu":
            notices.append("日足"+"は代替の公開チャートから取得しました（15分以上遅延）。")
        if data.get("meta",{}).get("incomplete_latest"):
            notices.append("最新確定日の日足が欠けているため、それ以前の確定足による暫定分析です。")
        if omitted:notices.append(f"価格が欠けた{omitted}本を除外しました。欠損値は補っていません。")
        if key=="daily":
            output["csv"]=csv_bytes(rows);meta["price_source"]=data.get("meta",{}).get("source","Yahoo Finance 公開株価")
            quote=data["meta"];qt=quote.get("regularMarketTime");qp=quote.get("regularMarketPrice")
            if isinstance(qt,(int,float)) and isinstance(qp,(int,float)) and math.isfinite(qp) and qp>0 and qt<=asof.timestamp():
                meta["current_quote"]={"price":qp,"observed_at":datetime.fromtimestamp(qt,timezone.utc).isoformat(),"source":meta["price_source"],"delayed":True}
    if reference and stock.get("as_of"):
        refdate=datetime.strptime(stock["as_of"],"%Y%m%d").replace(tzinfo=JST)
        eid="jpx-company-"+reference[1][:16]
        meta["evidence"].append(evidence(eid,"JPX 東証上場銘柄一覧",JPX_LIST,stamp,
            str({k:stock.get(k) for k in ("code","name","sector","size","as_of")})+"。公表時刻不明のため取得時点を利用可能時点とする。",reference[1],observed=refdate.isoformat(),published=reference[2]))
        # Do not use an outdated membership list or a future tick regime.
        if 0<=(asof-refdate).days<=35 and asof.astimezone(JST).date()<date(2027,3,1) and output["csv"]:
            group=1 if stock.get("size") in {"TOPIX Core30","TOPIX Large70","TOPIX Mid400"} else 2
            table=[{"up_to":r[0],"tick":r[group]} for r in TICKS]
            latest=float(list(csv.DictReader(StringIO(output["csv"].decode())))[-1]["close"])
            tick=next(r["tick"] for r in table if r["up_to"] is None or latest<=r["up_to"])
            tid="jpx-tick-"+digest([table,stock["as_of"],symbol])[:16]
            meta["evidence"].append(evidence(tid,"JPX 呼値の単位",JPX_TICKS,stamp,
                "2027年3月改定前の呼値表。適用区分の根拠："+eid+"。価格水準別に丸める。"))
            meta.update(tick_size=tick,tick_evidence_id=tid,tick_schedule=table)
    if "macro" in received:meta["evidence"].extend(received["macro"]["evidence"])
    if "facts" in received:
        facts=received["facts"]
        meta["public_facts"]=facts["facts"]
        meta["evidence"].extend(facts["evidence"])
        meta["evidence_quality"]=facts["evidence_quality"]
        notices.extend(facts["notices"])
    meta["automatic"]["notices"]=notices
    return output
