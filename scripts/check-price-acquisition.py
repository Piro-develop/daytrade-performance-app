"""Read-only live acquisition check, no Firebase, personal data or saved analyses.

Run in the deployed environment to distinguish its egress from local/CI egress.
--fallback deliberately makes Yahoo unavailable; only actual independent data
can pass. Prints public source, bar counts and observation times, never secrets.
"""
import argparse
from datetime import datetime,timezone
import json
import logging
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from judgment.price_sources import chart,download,normalize_chart


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--fallback",action="store_true")
    args=parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    now=datetime.now(timezone.utc)
    def fetch(url,params):
        if args.fallback and "finance.yahoo.com" in url:
            raise ValueError("test_yahoo_unavailable")
        return download(url,params)
    failed=False
    for symbol in ("4461","7203"):
        for interval in ("1d",):
            try:
                data,url,_=chart(symbol,interval,now,fetch)
                rows,omitted=normalize_chart(data,symbol,interval,now)
                print(json.dumps({"symbol":symbol,"interval":interval,"status":"ok", "source":data["meta"]["source"],
                    "uri":url,"bars":len(rows),"observed_at":rows[-1]["timestamp"],
                    "fetched_at":datetime.now(timezone.utc).isoformat(),"last_volume":rows[-1]["volume"],
                    "omitted":omitted},ensure_ascii=True),flush=True)
            except Exception as exc:
                failed=True;print(json.dumps({"symbol":symbol,"interval":interval,"status":"failed","error":type(exc).__name__}),flush=True)
    return int(failed)


if __name__=="__main__":raise SystemExit(main())
