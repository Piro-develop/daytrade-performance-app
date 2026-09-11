"""Read-only deployment checks; authenticated analysis must be checked separately."""
import argparse
from urllib.parse import urlsplit
import requests

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("url",help="Verified HTTPS backend origin")
    args=parser.parse_args()
    parts=urlsplit(args.url)
    if parts.scheme!="https" or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment or parts.path not in ("","/"):
        parser.error("Specify an HTTPS origin without credentials.")
    base=args.url.rstrip("/")
    with requests.Session() as session:
        health=session.get(base+"/healthz",timeout=30,allow_redirects=False)
        health.raise_for_status()
        if health.json()!={"service":"trading-journal","ready":True}: raise RuntimeError("Unexpected service")
        protected=session.get(base+"/api/judgment/history",timeout=30,allow_redirects=False)
        if protected.status_code!=401: raise RuntimeError("Unauthenticated access was not rejected")
        origin="https://piro-develop.github.io"
        preflight=session.options(base+"/api/judgment/analyze",headers={
            "Origin":origin,"Access-Control-Request-Method":"POST",
            "Access-Control-Request-Headers":"authorization,content-type"},timeout=30,allow_redirects=False)
        if preflight.status_code!=200 or preflight.headers.get("access-control-allow-origin")!=origin:
            raise RuntimeError("Pages origin is not allowed")
    print("HTTPS, health, unauthenticated rejection and Pages CORS: passed")
    print("Before publishing main, verify Google login, analysis and saved history after server restart.")
if __name__=="__main__": main()
