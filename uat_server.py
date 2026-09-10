"""Single-origin, single-owner UAT gateway; production identity is a separate adapter."""
from __future__ import annotations
import argparse
import asyncio
import html
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time
from urllib.parse import urlsplit
import requests
import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response, FileResponse
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocketDisconnect
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

ROOT = Path(__file__).resolve().parent
COOKIE = "journal_uat"
MAX_BODY = 12_000_000
PUBLIC_FILES = {
    "index.html", "app.js", "styles.css", "credit-styles.css", "investment.css",
    "investment.mjs", "stocks.json", "stock-readings.json", "stock-search-aliases.json",
    "manifest.webmanifest", "credit-calculation.mjs", "position-allocation.mjs",
    "spot-calculation.mjs", "tax-calculation.mjs", "trade-editing.mjs",
    "trade-deletion.mjs", "summary-ui.mjs", "profit-display.mjs",
}
HOP = {"connection", "keep-alive", "transfer-encoding", "upgrade", "proxy-authenticate",
       "proxy-authorization", "te", "trailer", "content-length", "content-encoding"}

def public_path(path):
    """Explicit allow-list: source, DBs, secrets and .git can never be served."""
    relative = path.lstrip("/") or "index.html"
    target = (ROOT / relative).resolve()
    if not target.is_relative_to(ROOT):
        return None
    if relative in PUBLIC_FILES:
        return target if target.is_file() else None
    for folder, suffix in (("assets/icons", ".png"), ("fonts", ".woff2")):
        if relative.startswith(folder+"/") and target.is_relative_to(ROOT/folder) and target.suffix == suffix:
            return target if target.is_file() else None
    return None

def create_app(upstream, access_code, session_key):
    def authorized(conn):
        return secrets.compare_digest(conn.cookies.get(COOKIE, ""), session_key)
    def same_origin(conn):
        origin = conn.headers.get("origin")
        return bool(origin and urlsplit(origin).netloc == conn.headers.get("host"))

    async def gate(request: Request):
        if request.method == "POST":
            # Login code is not sent to another service.
            if not same_origin(request):
                return Response("Origin rejected", status_code=403)
            form = await request.form()
            supplied = str(form.get("access", ""))
            if not secrets.compare_digest(supplied, access_code):
                await asyncio.sleep(.3)
                return HTMLResponse(login_html("アクセスコードを確認してください。"), status_code=403)
            result = RedirectResponse("/", status_code=303)
            result.set_cookie(COOKIE, session_key, httponly=True, samesite="strict",
                              secure=request.url.scheme == "https", max_age=43200)
            result.headers["Cache-Control"] = "no-store"
            return result
        return HTMLResponse(login_html(""), headers={"Cache-Control":"no-store", "Referrer-Policy":"same-origin"})

    async def status(request):
        if not authorized(request):
            return JSONResponse({"ready":False}, status_code=401)
        try:
            def health():
                with requests.Session() as session:
                    session.trust_env = False
                    return session.get(upstream+"/decision/_stcore/health", timeout=3).status_code == 200
            ready = await asyncio.to_thread(health)
        except requests.RequestException:
            ready = False
        return JSONResponse({"service":"trading-journal-uat", "ready":ready},
                            headers={"Cache-Control":"no-store"})

    async def proxy(request):
        if not authorized(request):
            return RedirectResponse("/uat/login", status_code=303)
        if request.method not in {"GET","HEAD","OPTIONS"} and not same_origin(request):
            return Response("Origin rejected", status_code=403)
        body = bytearray()
        async for part in request.stream():
            body.extend(part)
            if len(body) > MAX_BODY:
                return Response("ファイルは合計12MB以内です。", status_code=413)
        url = upstream + request.url.path
        if request.url.query:
            url += "?" + request.url.query
        headers = {k:v for k,v in request.headers.items() if k.lower() not in HOP}
        headers["accept-encoding"] = "identity"
        headers.pop("authorization", None)
        # Strip only the gateway secret; preserve Streamlit's XSRF cookie.
        headers["cookie"] = "; ".join(k+"="+v for k,v in request.cookies.items() if k != COOKIE)
        def fetch():
            with requests.Session() as session:
                session.trust_env = False
                with session.request(request.method, url, data=bytes(body), headers=headers,
                                     timeout=(5,60), allow_redirects=False) as result:
                    values=[(k.lower().encode(),v.encode("latin-1")) for k,v in result.raw.headers.items()
                            if k.lower() not in HOP]
                    return result.status_code, result.content, values
        try:
            code, content, values = await asyncio.to_thread(fetch)
            response = Response(content, status_code=code)
            response.raw_headers = values
            response.headers["Referrer-Policy"] = "same-origin"
            response.headers["Cache-Control"] = "no-store"
            return response
        except requests.RequestException:
            return HTMLResponse("<h1>判定サーバーに接続できません</h1><p>起動ターミナルのエラーを確認してください。</p>", status_code=503)

    async def websocket(ws):
        if not authorized(ws) or not same_origin(ws):
            await ws.close(code=1008)
            return
        path = ws.url.path + ("?"+ws.url.query if ws.url.query else "")
        cookie = "; ".join(k+"="+v for k,v in ws.cookies.items() if k != COOKIE)
        protocols = ws.scope.get("subprotocols", [])
        # Upstream uses localhost; same-origin validation already performed at this boundary.
        try:
            async with connect(upstream.replace("http://","ws://")+path,
                               origin=upstream, additional_headers={"Cookie":cookie},
                               subprotocols=protocols or None, proxy=None,
                               max_size=MAX_BODY, open_timeout=10) as remote:
                await ws.accept(subprotocol=remote.subprotocol)
                async def client_to_server():
                    while True:
                        message = await ws.receive()
                        if message["type"] == "websocket.disconnect":
                            return
                        await remote.send(message.get("bytes") if message.get("bytes") is not None else message["text"])
                async def server_to_client():
                    async for message in remote:
                        if isinstance(message,bytes):
                            await ws.send_bytes(message)
                        else:
                            await ws.send_text(message)
                tasks = [asyncio.create_task(client_to_server()), asyncio.create_task(server_to_client())]
                try:
                    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                    for task in done:
                        task.result()
                finally:
                    for task in tasks:
                        task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
        except (ConnectionClosed, WebSocketDisconnect, OSError):
            pass
        finally:
            try:
                await ws.close()
            except (RuntimeError, WebSocketDisconnect):
                pass

    async def static(request):
        if not authorized(request):
            return RedirectResponse("/uat/login", status_code=303)
        target = public_path(request.path_params.get("path",""))
        if target is None:
            return Response("Not found", status_code=404)
        return FileResponse(target, headers={"X-Content-Type-Options":"nosniff", "Referrer-Policy":"same-origin"})

    app = Starlette(routes=[
        Route("/uat/login", gate, methods=["GET","POST"]),
        Route("/integration/status", status),
        WebSocketRoute("/decision/{path:path}", websocket),
        Route("/decision", lambda request: RedirectResponse("/decision/")),
        Route("/decision/{path:path}", proxy, methods=["GET","HEAD","POST","PUT","PATCH","DELETE","OPTIONS"]),
        Route("/{path:path}", static),
    ])
    return app

def login_html(error):
    return """<!doctype html><html lang="ja"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>投資運用記録・統合UAT</title>
<style>body{background:#07100d;color:#e7f2eb;font:16px system-ui;margin:0;padding:24px}
main{max-width:440px;margin:10vh auto;padding:24px;border:1px solid #385544;border-radius:16px}
input,button{box-sizing:border-box;width:100%;min-height:48px;margin-top:12px;padding:12px;font-size:16px}
button{background:#7cdbac;border:0;border-radius:8px}p{line-height:1.8}small{color:#b4c6bb}</style>
<main><h1>投資運用記録</h1><p>統合UATを開きます。起動ターミナル、または「UAT起動案内」に表示されたアクセスコードを入力してください。</p>
<form method="post" action="/uat/login"><label>アクセスコード<input name="access" type="password" required autocomplete="current-password" maxlength="128"></label>
<button>統合UATを開く</button></form><p role="alert">""" + html.escape(error) + """</p>
<small>売買管理は従来のGoogleログインで利用します。判定UATの履歴は、このサーバーの利用者用に保存します。</small></main></html>"""

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--port",type=int,default=8765)
    parser.add_argument("--lan",action="store_true")
    parser.add_argument("--data-dir",type=Path)
    args=parser.parse_args()
    runtime=ROOT/".runtime"; runtime.mkdir(exist_ok=True)
    directory_config=runtime/"data-directory.txt"
    saved_directory=directory_config.read_text(encoding="utf-8").strip() if directory_config.exists() else ""
    directory=(args.data_dir or Path(os.environ.get("JOURNAL_DATA_DIR") or saved_directory or
              str(Path(os.environ.get("LOCALAPPDATA",Path.home()/".local/share"))/"DaytradePerformanceUAT"))).resolve()
    directory.mkdir(parents=True,exist_ok=True)
    directory_config.write_text(str(directory),encoding="utf-8")
    # Reserve the public port before starting a worker.
    public_socket=socket.socket()
    public_socket.bind(("0.0.0.0" if args.lan else "127.0.0.1",args.port))
    public_socket.listen(128)
    with socket.socket() as free:
        free.bind(("127.0.0.1",0)); backend_port=free.getsockname()[1]
    upstream=f"http://127.0.0.1:{backend_port}"
    env=os.environ.copy()
    env["INVESTMENT_APP_DATA_DIR"]=str(directory)
    env["PYTHONUTF8"]="1"
    code=secrets.token_urlsafe(24)
    session=secrets.token_urlsafe(32)
    log=(runtime/"decision-server.log").open("w",encoding="utf-8")
    worker=subprocess.Popen([sys.executable,"-m","streamlit","run",str(ROOT/"investment/app.py"),
        "--server.address","127.0.0.1","--server.port",str(backend_port),"--server.baseUrlPath","decision",
        "--server.headless","true","--browser.gatherUsageStats","false","--server.maxUploadSize","10",
        "--theme.base","dark","--theme.primaryColor","#7cdbac","--theme.backgroundColor","#07100d",
        "--theme.secondaryBackgroundColor","#10231a"],
        cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name=="nt" else 0)
    try:
        deadline=time.monotonic()+45
        with requests.Session() as check:
            check.trust_env=False
            while time.monotonic()<deadline:
                if worker.poll() is not None:
                    raise RuntimeError("判定サーバーが終了しました。.runtime/decision-server.log を確認してください。")
                try:
                    if check.get(upstream+"/decision/_stcore/health",timeout=1).status_code==200:
                        break
                except requests.RequestException:
                    pass
                time.sleep(.25)
            else:
                raise RuntimeError("判定サーバーの起動がタイムアウトしました。")
        urls=[f"http://127.0.0.1:{args.port}/"]
        if args.lan:
            ips=sorted({i[4][0] for i in socket.getaddrinfo(socket.gethostname(),None,socket.AF_INET)
                        if not i[4][0].startswith(("127.","169.254."))})
            urls += [f"http://{ip}:{args.port}/" for ip in ips]
        links="".join(f'<li><a href="{html.escape(url)}">{html.escape(url)}</a></li>' for url in urls)
        (runtime/"uat-access.html").write_text('<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>UAT起動案内</title><h1>統合UAT</h1><ul>'+links+'</ul><p>アクセスコード：<code>'+code+'</code></p><p>PCと同じWi-Fiのスマホでは、127.0.0.1以外のURLを開いてください。起動中のPCが必要です。売買管理は従来のGoogleログインを使用します。コードは共有しないでください。停止・再起動すると旧コードは無効です。</p>',encoding="utf-8")
        (runtime/"server.json").write_text(json.dumps({"pid":os.getpid(),"worker_pid":worker.pid,"urls":urls,"data_dir":str(directory)},ensure_ascii=False,indent=2),encoding="utf-8")
        print("統合UAT: "+", ".join(urls),flush=True)
        print("アクセスコード: "+code,flush=True)
        print("UAT起動案内: "+str(runtime/"uat-access.html"),flush=True)
        print("停止: Ctrl+C",flush=True)
        config=uvicorn.Config(create_app(upstream,code,session),access_log=False,log_level="warning",
                              proxy_headers=False,ws_max_size=MAX_BODY)
        uvicorn.Server(config).run(sockets=[public_socket])
    finally:
        worker.terminate()
        try: worker.wait(timeout=10)
        except subprocess.TimeoutExpired: worker.kill();worker.wait()
        log.close();public_socket.close()

if __name__=="__main__":
    main()
