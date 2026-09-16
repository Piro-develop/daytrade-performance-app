"""Small deterministic checks for public price integrity; no database or network."""
from datetime import datetime, timedelta
import json
import unittest
from unittest.mock import patch

import requests
from judgment import price_sources as prices

NOW = datetime(2026, 9, 15, 18, tzinfo=prices.JST)


def minute_rows(symbol="4461", start=None, count=10):
    start = start or NOW.replace(hour=9, minute=0)
    return [{"ric":symbol+".T", "currency_code":"JPY", "date":(start+timedelta(minutes=i)).isoformat(),
             "open":100+i, "high":102+i, "low":99+i, "close":101+i, "volume":10+i} for i in range(count)]


def raw_fetch(items):
    return lambda *_: json.dumps(items).encode()


class PriceSourceTests(unittest.TestCase):
    def test_complete_minutes_only_and_exact_ohlcv(self):
        data, url, _ = prices.minkabu_chart("4461", "5m", NOW, raw_fetch(minute_rows()))
        rows, _ = prices.normalize_chart(data,"4461","5m",NOW)
        self.assertEqual(len(rows),2)
        self.assertEqual([rows[0][k] for k in ("open","high","low","close","volume")], [100,106,99,105,60])
        self.assertEqual(rows[0]["timestamp"], "2026-09-15T09:05:00+09:00")
        self.assertIn("ric=4461.T",url)
        self.assertEqual(rows[0]["adjustment_basis"],"minkabu_chart_as_published")

    def test_no_fill_for_missing_null_or_conflicting_minutes(self):
        items=minute_rows(count=5)
        with self.assertRaises(ValueError):prices.minkabu_chart("4461","5m",NOW,raw_fetch(items[:4]))
        items[2]["volume"]=None
        with self.assertRaises(ValueError):prices.minkabu_chart("4461","5m",NOW,raw_fetch(items))
        items=minute_rows(count=5);items.append(dict(items[0],close=102))
        with self.assertRaisesRegex(ValueError,"conflicting_bars"):prices.minkabu_chart("4461","5m",NOW,raw_fetch(items))

    def test_delayed_unfinished_bar_lunch_and_auction_not_merged(self):
        items=minute_rows(start=NOW.replace(hour=9,minute=0),count=5)
        with self.assertRaises(ValueError):prices.minkabu_chart("4461","5m",NOW.replace(hour=9,minute=19),raw_fetch(items))
        data,_,_=prices.minkabu_chart("4461","5m",NOW.replace(hour=9,minute=20),raw_fetch(items))
        self.assertEqual(len(data["timestamp"]),1)
        for hour,minute in ((11,28),(15,28)):
            with self.assertRaises(ValueError):prices.minkabu_chart("4461","5m",NOW,raw_fetch(minute_rows(start=NOW.replace(hour=hour,minute=minute),count=5)))

    def test_prior_session_keeps_real_date_and_after_close_works(self):
        items=minute_rows(start=NOW.replace(hour=15,minute=20),count=5)
        data,_,_=prices.minkabu_chart("4461","5m",NOW,raw_fetch(items))
        rows,_=prices.normalize_chart(data,"4461","5m",NOW)
        self.assertEqual(rows[-1]["timestamp"],"2026-09-15T15:25:00+09:00")
        next_day=NOW+timedelta(days=1)
        prior,_=prices.normalize_chart(data,"4461","5m",next_day)
        self.assertEqual(prior,rows)

    def test_wrong_symbol_currency_or_timezone_is_rejected(self):
        for field,value in (("ric","7203.T"),("currency_code","USD"),("date","2026-09-15T09:00:00")):
            items=minute_rows(count=5);items[0][field]=value
            with self.assertRaises(ValueError):prices.minkabu_chart("4461","5m",NOW,raw_fetch(items))

    def test_daily_closed_prices_and_volume_retained(self):
        items=[dict(minute_rows()[0],date="2026-09-15"),dict(minute_rows()[1],date="2026-09-14")]
        data,_,_=prices.minkabu_chart("4461","1d",NOW,raw_fetch(items))
        rows,_=prices.normalize_chart(data,"4461","1d",NOW)
        self.assertEqual(len(rows),2)
        self.assertEqual(rows[-1]["volume"],10)
        self.assertEqual(rows[-1]["timestamp"],"2026-09-15T15:30:00+09:00")
        data,_,_=prices.minkabu_chart("4461","1d",NOW.replace(hour=15,minute=35),raw_fetch(items))
        rows,_=prices.normalize_chart(data,"4461","1d",NOW)
        self.assertEqual(len(rows),1)

    def test_yahoo_both_hosts_429_use_independent_provider(self):
        calls=[]
        def fetch(url,params):
            calls.append(url)
            if "yahoo.com" in url:
                response=requests.Response();response.status_code=429
                raise requests.HTTPError("secret-must-not-be-logged",response=response)
            return json.dumps(minute_rows()).encode()
        with self.assertLogs("uvicorn.error",level="INFO") as logs:
            data,url,_=prices.chart("4461","5m",NOW,fetch)
        self.assertEqual(data["meta"]["provider"],"minkabu")
        self.assertIn("mkdd.net",url)
        self.assertEqual(len(calls),3)
        self.assertIn("http=429",str(logs.output))
        self.assertNotIn("secret-must-not-be-logged",str(logs.output))

    def test_http_200_bad_json_or_no_closed_rows_also_falls_back(self):
        empty={"chart":{"result":[{"meta":{"symbol":"4461.T","currency":"JPY","instrumentType":"EQUITY","exchangeName":"JPX"},"timestamp":[],"indicators":{"quote":[{}]}}]}}
        def fetch(url,params):
            if "query1" in url:return b"<html>unavailable</html>"
            if "query2" in url:return json.dumps(empty).encode()
            return json.dumps(minute_rows()).encode()
        data,_,_=prices.chart("4461","5m",NOW,fetch)
        self.assertEqual(data["meta"]["provider"],"minkabu")

    def test_all_sources_fail_do_not_fabricate_prices(self):
        with self.assertRaisesRegex(ValueError,"public prices unavailable"):
            prices.chart("4461","1d",NOW,lambda *_:b"[]")

    def test_zero_trade_carry_forward_is_not_a_price_observation(self):
        data={"timestamp":[NOW.replace(hour=9,minute=0).timestamp()],
              "indicators":{"quote":[{"open":[100],"high":[100],"low":[100],"close":[100],"volume":[0]}]}}
        with self.assertRaisesRegex(ValueError,"no_completed_bars"):
            prices.normalize_chart(data,"4461","5m",NOW)

    def test_yahoo_null_and_unfinished_and_latest_session(self):
        starts=[NOW.replace(hour=9,minute=i) for i in (0,5,10)]
        data={"timestamp":[t.timestamp() for t in starts],"indicators":{"quote":[{k:[100,100,None] for k in ("open","high","low","close","volume")}]}}
        rows,omitted=prices.normalize_chart(data,"7203","5m",NOW.replace(hour=9,minute=7))
        self.assertEqual(len(rows),1)
        rows,omitted=prices.normalize_chart(data,"7203","5m",NOW)
        self.assertEqual((len(rows),omitted),(2,1))


if __name__ == "__main__":unittest.main()
