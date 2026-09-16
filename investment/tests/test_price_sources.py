"""Small deterministic checks for public price integrity; no database or network."""
from datetime import datetime, timedelta
import json
import unittest
from unittest.mock import patch

import requests
from judgment import price_sources as prices

NOW = datetime(2026, 9, 15, 18, tzinfo=prices.JST)


def daily_rows(symbol="4461", count=10):
    return [{"ric":symbol+".T", "currency_code":"JPY", "date":(NOW-timedelta(days=i)).date().isoformat(),
             "open":100+i, "high":102+i, "low":99+i, "close":101+i, "volume":10+i} for i in range(count)]


def raw_fetch(items):
    return lambda *_: json.dumps(items).encode()


class PriceSourceTests(unittest.TestCase):


    def test_daily_closed_prices_and_volume_retained(self):
        items=[dict(daily_rows()[0],date="2026-09-15"),dict(daily_rows()[1],date="2026-09-14")]
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
            return json.dumps(daily_rows()).encode()
        with self.assertLogs("uvicorn.error",level="INFO") as logs:
            data,url,_=prices.chart("4461","1d",NOW,fetch)
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
            return json.dumps(daily_rows()).encode()
        data,_,_=prices.chart("4461","1d",NOW,fetch)
        self.assertEqual(data["meta"]["provider"],"minkabu")

    def test_latest_closed_day_missing_uses_fallback_without_discarding_older_data(self):
        stamps=[int((NOW-timedelta(days=i)).replace(hour=9).timestamp()) for i in (1,0)]
        data={"meta":{"symbol":"4461.T","currency":"JPY","instrumentType":"EQUITY","exchangeName":"JPX"},
              "timestamp":stamps,"indicators":{"quote":[{k:[100,None] for k in ("open","high","low","close","volume")}]}}
        def fetch(url,params):
            return json.dumps({"chart":{"result":[data]}} if "yahoo.com" in url else daily_rows()).encode()
        result,_,_=prices.chart("4461","1d",NOW,fetch)
        self.assertEqual(result["meta"]["provider"],"minkabu")
        rows,_=prices.normalize_chart(result,"4461","1d",NOW)
        self.assertTrue(rows[-1]["timestamp"].startswith("2026-09-15"))
        def fallback_down(url,params):
            if "yahoo.com" not in url:raise requests.ConnectionError()
            return fetch(url,params)
        result,_,_=prices.chart("4461","1d",NOW,fallback_down)
        self.assertTrue(result["meta"]["incomplete_latest"])
        rows,_=prices.normalize_chart(result,"4461","1d",NOW)
        self.assertTrue(rows[-1]["timestamp"].startswith("2026-09-14"))

    def test_all_sources_fail_do_not_fabricate_prices(self):
        with self.assertRaisesRegex(ValueError,"public prices unavailable"):
            prices.chart("4461","1d",NOW,lambda *_:b"[]")


if __name__ == "__main__":unittest.main()
