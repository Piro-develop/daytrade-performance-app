"""Explicit, bounded public downloads; no credentials, trading or hidden retries."""
from __future__ import annotations
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from io import StringIO
import hashlib
import re
import xml.etree.ElementTree as ET
import pandas as pd
import requests
from .models import InputError, Evidence, digest, plain, time_value
from .horizons import settings

ENDPOINTS={
 "stooq":"https://stooq.com/q/d/l/",
 "ecb":"https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml",
 "fed":"https://www.federalreserve.gov/feeds/press_monetary.xml"}
def download(source,params=None):
    cfg=settings()
    try:
        with requests.get(ENDPOINTS[source],params=params,timeout=cfg["network_timeout"],
                          stream=True,allow_redirects=False,headers={"User-Agent":"InvestmentDecisionUAT/1.0"}) as response:
            if response.status_code!=200: raise InputError(f"公開データ取得不可（HTTP {response.status_code}）。CSV・手動補完を使用してください。")
            chunks=[];size=0
            for block in response.iter_content(16384):
                size+=len(block)
                if size>cfg["network_max_bytes"]: raise InputError("公開データが容量上限を超えました。")
                chunks.append(block)
            raw=b"".join(chunks)
    except requests.RequestException as exc:
        raise InputError("公開サービスへ接続できません。時間をおくかCSVで補完してください。") from exc
    if not raw or b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise InputError("期待する公開データ形式ではありません。")
    return raw,datetime.now(timezone.utc).isoformat()

class StooqMarketProvider:
    def capabilities(self):
        return {"market":True,"intervals":["1d"],"network":True,"paid":False,"realtime":False}
    def fetch(self,symbol,start,end,interval="1d"):
        if interval!="1d" or not re.fullmatch(r"[0-9A-Za-z]{4}",symbol):
            raise InputError("日本株4桁コード・日足のみ対応します。")
        raw,fetched=download("stooq",{"s":symbol.lower()+".jp","i":"d","d1":start.replace("-",""),"d2":end.replace("-","")})
        try: frame=pd.read_csv(StringIO(raw.decode("utf-8-sig")))
        except Exception as exc: raise InputError("価格CSVを取得できません。") from exc
        if not {"Date","Open","High","Low","Close","Volume"}.issubset(frame.columns) or frame.empty:
            raise InputError("提供元から有効な日足を取得できません。認証回避はせずCSV補完を使用します。")
        frame=frame.rename(columns={"Date":"date","Open":"open","High":"high","Low":"low","Close":"close","Volume":"volume"})
        frame["symbol_code"]=symbol
        # Adjustment basis is deliberately absent until the user verifies the source convention.
        return {"csv":frame.to_csv(index=False).encode(),"fetched_at":fetched,
                "source":"Stooq公開日足","source_uri":ENDPOINTS["stooq"],"raw_hash":hashlib.sha256(raw).hexdigest(),
                "note":"価格調整基準と対象期間の確定時刻を確認してから採用してください。リアルタイム値ではありません。"}

class PublicContextProvider:
    def capabilities(self):
        return {"fx":True,"central_bank_news":True,"paid":False,"network":True}
    def fetch(self,source):
        raw,fetched=download(source)
        try: root=ET.fromstring(raw)
        except ET.ParseError as exc: raise InputError("公開XMLの形式を読み取れません。") from exc
        if source=="ecb":
            rows=[x for x in root.iter() if "currency" in x.attrib and "rate" in x.attrib]
            rates={x.attrib["currency"]:float(x.attrib["rate"]) for x in rows}
            if not rates or any(not (0<v<float("inf")) for v in rates.values()): raise InputError("為替値が欠損または不正です。")
            observed=next((x.attrib["time"] for x in root.iter() if "time" in x.attrib),None)
            if not observed: raise InputError("為替の観測日がありません。")
            summary={"reference_date":observed,"base":"EUR","rates":rates,
                     "USDJPY":rates["JPY"]/rates["USD"] if "JPY" in rates and "USD" in rates else None,
                     "calculation":"JPY per EUR / USD per EUR","use":"参考レート。売買の現在値ではありません"}
            # Published clock is unknown: retain date separately and use fetch time as availability cutoff.
            ev=Evidence("ecb-"+digest([observed,rates])[:16],"ECB為替参考レート",ENDPOINTS["ecb"],fetched,fetched,fetched,
                        str(summary),hashlib.sha256(raw).hexdigest(),"public",.8)
            return {"evidence":[plain(ev)],"data":summary,"fetched_at":fetched}
        records=[]
        for item in root.findall(".//item")[:30]:
            title=item.findtext("title");link=item.findtext("link");published=item.findtext("pubDate")
            if not title or not link or not published: continue
            try: stamp=parsedate_to_datetime(published).isoformat();time_value(stamp)
            except (ValueError,TypeError): continue
            if time_value(stamp)>time_value(fetched): continue
            records.append(plain(Evidence("fed-"+digest([link,stamp])[:16],"Federal Reserve",link,stamp,stamp,fetched,
                title,digest(ET.tostring(item).hex()),"public",.8)))
        if not records: raise InputError("日時付き公式ニュースが取得できませんでした。")
        return {"evidence":records,"data":{"category":"金融政策ニュース","count":len(records)},"fetched_at":fetched}
