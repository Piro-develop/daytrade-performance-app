"""Bounded public facts. Issuer PDFs are facts; generated summaries are never inputs."""
from datetime import datetime, timedelta
from hashlib import sha256
from html import unescape
from io import BytesIO
import json, re, unicodedata
from urllib.parse import urlsplit
import requests
from .price_sources import download, normalize_chart, JST

HOST = 'https://finance.yahoo.co.jp/quote/'
PDF_HOST = 'finance-frontend-pc-dist.west.edge.storage-yahoo.jp'


def flight_objects(html):
    def walk(value):
        if isinstance(value, dict):
            yield value
            for child in value.values(): yield from walk(child)
        elif isinstance(value, list):
            for child in value: yield from walk(child)
    for body in re.findall(r'self\.__next_f\.push\((.*?)\)</script>', html, re.S):
        try: chunk = json.loads(body)[1]
        except (ValueError, IndexError, TypeError): continue
        if not isinstance(chunk, str): continue
        for line in chunk.splitlines():
            try: value = json.loads(line.split(':', 1)[1])
            except (ValueError, IndexError): continue
            yield from walk(value)


def text_only(html):
    return unescape(re.sub('<[^>]+>', ' ', html))


def disclosures(html, asof):
    rows = []
    for url, body in re.findall(r'href="([^"]+\.pdf)"[^>]*>(.*?)</a>', html, re.S):
        title = re.search(r'<h3[^>]*>(.*?)</h3>', body, re.S)
        stamp = re.search(r'dateTime="([^"]+)"', body)
        if not title or not stamp or urlsplit(url).hostname != PDF_HOST: continue
        when = datetime.fromisoformat(stamp[1])
        if when > asof: continue
        rows.append({'title': text_only(title[1]), 'published_at': when.isoformat(), 'url': url})
    return sorted(rows, key=lambda r:r['published_at'], reverse=True)


def pdf_text(raw, symbol):
    from pypdf import PdfReader
    from pypdf.errors import PyPdfError
    try:
        reader = PdfReader(BytesIO(raw))
    except PyPdfError as exc:
        raise ValueError('unreadable_document') from exc
    if len(reader.pages)>60: raise ValueError('document_page_limit')
    pages = [unicodedata.normalize('NFKC', p.extract_text() or '') for p in reader.pages]
    text = '\n'.join(pages)
    if len(text)>200000 or not re.search(r'(?:コード番号|証券コード|コード)\D{0,8}'+re.escape(symbol), pages[0]):
        raise ValueError('issuer_not_confirmed')
    return pages, text


def numbers(row):
    parts = row.replace(',', '').split()
    if any(not re.fullmatch(r'[△▲+-]?\d+(?:\.\d+)?|[-－―]', x) for x in parts): return []
    return [None if x in ('-', '－', '―') else float(x.replace('△','-').replace('▲','-')) for x in parts]


def financial_table(pages):
    # Only the standard J-GAAP consolidated first-page table, with explicit units.
    text = pages[0]
    if not all(x in text for x in ('日本基準', '連結', '百万円', '売上高', '営業利益', '経常利益')): return {}
    rows=[];eps={}
    for line in text.splitlines():
        m=re.match(r'\s*(\d{4}年\d{1,2}月期(?:第[123]四半期|中間期)?)\s+(.+)$',line)
        if not m: continue
        nums=numbers(m[2])
        if len(nums)==8 and all(x is not None for x in nums[::2]):
            rows.append(dict(period=m[1],sales=nums[0],sales_yoy=nums[1],operating=nums[2],operating_yoy=nums[3],ordinary=nums[4],ordinary_yoy=nums[5],net=nums[6],net_yoy=nums[7]))
        if len(nums)==2 and nums[0] is not None: eps[m[1]]=nums[0]
    if len(rows)!=2 or int(rows[0]['period'][:4])!=int(rows[1]['period'][:4])+1: return {}
    if rows[0]['period'][4:]!=rows[1]['period'][4:]: return {}
    for row in rows:
        row['eps']=eps.get(row['period'])
        row['operating_margin']=100*row['operating']/row['sales'] if row['sales']>0 else None
    forecast=None
    for line in text.splitlines():
        m=re.match(r'\s*通期\s+(.+)$',line)
        if m:
            vals=numbers(m[1])
            if len(vals)==9 and all(x is not None for x in vals[::2]):
                forecast=dict(period=rows[0]['period'].split('期')[0]+'期',sales=vals[0],sales_yoy=vals[1],operating=vals[2],operating_yoy=vals[3],ordinary=vals[4],ordinary_yoy=vals[5],net=vals[6],net_yoy=vals[7],eps=vals[8])
    return dict(current=rows[0],previous=rows[1],forecast=forecast,unit='百万円（EPSは円）',scope='連結・日本基準')


def revision_table(text, forecast):
    if not forecast or forecast['period'] not in re.sub(r'\s+','',text): return {}
    old=[];new=[]
    for line in text.splitlines():
        compact=re.sub(r'\s+','',line)
        for label, dest in (('前回発表予想',old),('今回修正予想',new)):
            if compact.startswith(label):
                m=re.search(r'[)）]\s*(.+)$',line)
                vals=numbers(m[1]) if m else []
                if len(vals)==5 and all(x is not None for x in vals): dest.append(vals)
    expected=[forecast[k] for k in ('sales','operating','ordinary','net','eps')]
    pairs=[(a,b) for a,b in zip(old,new) if b==expected]
    return dict(previous=pairs[0][0],current=pairs[0][1],period=forecast['period']) if len(pairs)==1 else {}


class PublicFactsProvider:
    def fetch(self, symbol, asof):
        facts={};evidence=[];quality={};notices=[]
        stamp=asof.isoformat()
        def add(kind, source, url, raw, summary, observed=None, published=None, original=False, days=1):
            digest=sha256(raw).hexdigest();eid='facts-'+kind+'-'+digest[:16]
            observed=observed or stamp
            evidence.append(dict(evidence_id=eid,source_name=source,source_uri=url,observed_at=observed,published_at=published or stamp,fetched_at=stamp,summary=summary,content_hash=digest,source_type='public',confidence=.8))
            quality[eid]=dict(valid_until=((asof if original else datetime.fromisoformat(observed))+timedelta(days=days)).isoformat(),source_quality='original_verified' if original else 'secondary_verified',independent_evidence_ids=[],unresolved_conflict=False)
            return eid
        quote='';listing=[]
        for page in ('', '/disclosure'):
            url=HOST+symbol+'.T'+page
            try:
                raw=download(url);html=raw.decode('utf-8')
                if page: listing=disclosures(html,asof)
                else: quote=html
            except (requests.RequestException, ValueError, UnicodeError): notices.append('公開企業情報の一部を取得できませんでした。')
        for obj in flight_objects(quote):
            schedule=obj.get('pressReleaseSchedule')
            if isinstance(schedule,dict) and not schedule.get('isError'):
                message=schedule.get('pressReleaseScheduleMessage','')
                if message:
                    eid=add('event','Yahoo!ファイナンス 決算予定',HOST+symbol+'.T',message.encode(),message)
                    facts['earnings']={'description':message,'evidence_ids':[eid]}
                    exact=re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日',message)
                    # Estimated dates are not a confirmed event even when formatted as a date.
                    if exact and schedule.get('planDivision')!='ifisCalculation' and not re.search('頃|上旬|中旬|下旬|予測',message):
                        event=datetime(*map(int,exact.groups()),tzinfo=JST)
                        if event.date()>=asof.astimezone(JST).date(): facts['earnings']['scheduled_at']=event.isoformat()
            detail=obj.get('detailData')
            if isinstance(detail,dict) and not detail.get('isApiError'):
                values={}
                for key in ('per','pbr','eps','bps','roe','equityRatio','tradingValue'):
                    item=detail.get('indicators',{}).get(key,{})
                    if item.get('isLock'): continue
                    try: val=float(item['value'].replace(',',''))
                    except (ValueError,KeyError,TypeError): continue
                    when=item.get('updateDateMeta')
                    if when and 'T' in when and datetime.fromisoformat(when)>asof: continue
                    values[key]={'value':val,'period_or_observed_at':when,'label':item.get('name','')+item.get('subText',''),'unit':item.get('suffix','')}
                if values:
                    eid=add('indicators','Yahoo!ファイナンス 公開指標',HOST+symbol+'.T',json.dumps(values).encode(),json.dumps(values,ensure_ascii=False))
                    quality[eid]['constrained']=True # Missing period dates must remain explicit.
                    facts['valuation']={'values':values,'evidence_ids':[eid]}
        # Visible credit balances only; ignore premium placeholders and generated summaries.
        visible=text_only(quote).split('信用取引情報',1)[-1].split('現物信用売買内訳',1)[0]
        credit={}
        for label,key in (('信用買残','buy'),('信用売残','sell')):
            m=re.search(label+r'\s*用語\s*([\d,]+)\s*株\s*\(\s*(\d{2})/(\d{2})\s*\).*?前週比\s*用語\s*([+\-]?\d[\d,]*)\s*株',visible,re.S)
            if m:
                day=datetime(asof.year,int(m[2]),int(m[3]),tzinfo=JST)
                if day>asof: day=day.replace(year=day.year-1)
                credit[key]=int(m[1].replace(',',''));credit[key+'_change']=int(m[4].replace(',',''));credit[key+'_observed_at']=day.isoformat()
        if credit and len({credit.get('buy_observed_at'),credit.get('sell_observed_at')})==1:
            eid=add('credit','Yahoo!ファイナンス 公表信用残',HOST+symbol+'.T',json.dumps(credit).encode(),json.dumps(credit,ensure_ascii=False),observed=credit['buy_observed_at'],days=10)
            facts['credit']={**credit,'evidence_ids':[eid]}
        if listing:
            eid=add('disclosures','TDnet原文リンク付き開示一覧',HOST+symbol+'.T/disclosure',json.dumps(listing).encode(),json.dumps(listing,ensure_ascii=False))
            facts['disclosures']={'items':listing,'evidence_ids':[eid],'complete_review':False}
        financial=next((r for r in listing if '決算短信' in r['title'] and '訂正' not in r['title']),None)
        if financial:
            try:
                raw=download(financial['url']);pages,text=pdf_text(raw,symbol);table=financial_table(pages)
                if table:
                    eid=add('financial','会社公表 決算短信（TDnet原文）',financial['url'],raw,json.dumps(table,ensure_ascii=False)+'\n'+text[:18000],observed=financial['published_at'],published=financial['published_at'],original=True)
                    facts['financial']={**table,'evidence_ids':[eid],'published_at':financial['published_at'],'period':table['current']['period'],'latest_confirmed':(asof-datetime.fromisoformat(financial['published_at'])).days<=120}
                    # Explicit scope only: no unsupported "no bad news" statement.
                    facts['financial']['going_concern_no_issue']=bool(re.search(r'継続企業の前提に関する注記[)）\s]*該当事項はありません',text))
                    revision=next((r for r in listing if '業績予想' in r['title'] and '修正' in r['title'] and r['published_at']>=financial['published_at']),None)
                    if revision:
                        rr=download(revision['url']);_,rt=pdf_text(rr,symbol);rev=revision_table(rt,table['forecast'])
                        if rev:
                            rid=add('revision','会社公表 業績予想修正（TDnet原文）',revision['url'],rr,json.dumps(rev,ensure_ascii=False)+'\n'+rt[:12000],observed=revision['published_at'],published=revision['published_at'],original=True)
                            facts['revision']={**rev,'evidence_ids':[rid]}
                        else:
                            facts['financial']['latest_confirmed']=False
                            quality[eid]['unresolved_conflict']=True
                            notices.append('業績修正と採用計画の数値を照合できないため財務評価を保留しています。')
            except (requests.RequestException, ValueError, KeyError, TypeError, ImportError): notices.append('公式決算の数値表を確実に確認できなかったため、該当カードを未評価にしています。')
        # A market-wide comparison proxy, not a peer valuation or another trading target.
        url='https://query1.finance.yahoo.com/v8/finance/chart/1306.T'
        try:
            params={'interval':'1d','range':'1y'};raw=download(url,params)
            data=json.loads(raw)['chart']['result'][0];m=data['meta']
            if not (m.get('symbol')=='1306.T' and m.get('currency')=='JPY' and m.get('instrumentType')=='ETF' and m.get('exchangeName')=='JPX'): raise ValueError('benchmark_identity')
            rows,_=normalize_chart(data,'1306','1d',asof)
            uri=requests.Request('GET',url,params=params).prepare().url
            eid=add('benchmark','Yahoo Finance TOPIX連動ETF 1306',uri,raw,'市場全体に対する相対強度用。TOPIX連動ETFを価格リターン比較の代理に使用。指数そのもの・同業比較ではない。分配金・追随誤差を含む制約。商品定義：https://nextfunds.jp/lineup/1306/',observed=rows[-1]['timestamp'],days=3)
            facts['benchmark']={'symbol':'1306','bars':rows,'evidence_ids':[eid],'purpose':'TOPIX連動ETFに対する4週・13週価格リターン差'}
        except (requests.RequestException,ValueError,KeyError,TypeError,IndexError): notices.append('市場比較用の確定日足を取得できず、相対強度は未評価です。')
        return dict(facts=facts,evidence=evidence,evidence_quality=quality,notices=notices)
