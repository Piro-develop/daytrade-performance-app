"""Production tracker and authenticated judgment API. No UAT login or iframe."""
from __future__ import annotations
import argparse
import asyncio
from datetime import datetime,timezone
import json
import logging
import os
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/"investment/src"))
import uvicorn
from starlette.applications import Starlette
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import FileResponse,JSONResponse,Response
from starlette.routing import Route
from judgment.auth import FirebaseIdentity,AuthenticationError
from judgment.service import JudgmentService
from judgment.firestore_store import FirestoreHistory
from investment_app.models import InputError,plain
from investment_app.uat_service import recommendation
from web_assets import public_path
from investment_app.presentation import selected_result

def present(result):
    h=result['metadata'].get('horizon','swing')
    return dict(result,presentation={k:selected_result({h:result},h,k) for k in result['decisions']})

def create_app(directory=None,identity=None,origins=(),store_factory=None):
    identity=identity or FirebaseIdentity(ROOT)
    async def api(request):
        headers={"Cache-Control":"no-store","X-Content-Type-Options":"nosniff"}
        try:
            bearer=request.headers.get("authorization","")
            if not bearer.startswith("Bearer "): raise AuthenticationError("Googleログインが必要です。")
            uid=await asyncio.to_thread(identity.verify,bearer[7:])
        except AuthenticationError as exc:
            return JSONResponse({"error":str(exc)},status_code=401,headers=headers)
        # Local storage is available only through explicit offline test injection, never the production CLI.
        service=JudgmentService(directory) if directory is not None else JudgmentService(store=(store_factory(uid,bearer[7:]) if store_factory else FirestoreHistory(identity.project,uid,bearer[7:])))
        try:
            payload={}
            if request.method=="POST":
                body=bytearray()
                async for chunk in request.stream():
                    body.extend(chunk)
                    if len(body)>30_000_000:
                        return JSONResponse({"error":"入力ファイルの合計が大きすぎます。"},status_code=413,headers=headers)
                payload=json.loads(body)
                if not isinstance(payload,dict): raise InputError("入力形式を確認してください。")
            action=request.path_params["action"]
            method=request.method
            def execute():
                if method=="GET" and action=="catalog": return service.catalog()
                if method=="GET" and action.startswith("images/"): return service.history(uid).get_image(action[7:])
                if method=="GET" and action=="history": return service.list_runs(uid)
                if method=="GET" and action.startswith("runs/"): return present(service.get(uid,action[5:]))
                if method=="GET" and action=="approval":
                    return service.approval_state(uid,request.query_params.get("run_id",""),request.query_params.get("scenario",""))
                if method=="POST" and action=="automatic":
                    out=service.automatic(uid,payload)
                    out["results"]={h:present(r) for h,r in out["results"].items()}
                    out["recommended"]=recommendation(out["results"]) if out["results"] else []
                    return out
                if method=="POST" and action=="analyze":
                    results=service.analyze(uid,payload)
                    return {"results":{h:present(r) for h,r in results.items()},"recommended":recommendation(results)}
                if method=="POST" and action=="image": return service.image(uid,payload)
                if method=="POST" and action=="public": return service.public(payload)
                if method=="POST" and action=="ai": return service.ai(payload)
                if method=="POST" and action=="approval": return service.approve(uid,payload)
                raise KeyError("endpoint")
            result=await asyncio.to_thread(execute)
            return JSONResponse(plain(result),headers=headers)
        except KeyError:
            return JSONResponse({"error":"対象の分析または機能がありません。"},status_code=404,headers=headers)
        except (InputError,ValueError,TypeError) as exc:
            return JSONResponse({"error":str(exc)},status_code=400,headers=headers)
        except Exception:
            logging.exception("Judgment request failed")
            return JSONResponse({"error":"処理を完了できませんでした。入力またはサーバーログを確認してください。"},
                                status_code=500,headers=headers)
    async def health(request):
        return JSONResponse({"service":"trading-journal","ready":True,"features":["automatic-judgment-v1","independent-price-fallback-v1"]})
    async def static(request):
        path=public_path(request.path_params.get("path",""))
        if not path: return Response("Not found",status_code=404)
        media="text/javascript" if path.suffix in {".js",".mjs"} else None
        return FileResponse(path,media_type=media,headers={"Cache-Control":"no-cache","X-Content-Type-Options":"nosniff"})
    app=Starlette(routes=[Route("/healthz",health),Route("/api/judgment/{action:path}",api,methods=["GET","POST"]),
                           Route("/{path:path}",static)])
    app.add_middleware(CORSMiddleware,allow_origins=list(origins),allow_methods=["GET","POST"],
                       allow_headers=["Authorization","Content-Type"],max_age=600)
    return app

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--host",default="127.0.0.1")
    parser.add_argument("--port",type=int,default=int(os.getenv("PORT","8766")))
    parser.add_argument("--allow-origin",action="append",default=[])
    args=parser.parse_args()
    origins=args.allow_origin or ["https://piro-develop.github.io"]
    uvicorn.run(create_app(origins=origins),host=args.host,port=args.port,access_log=False)

if __name__=="__main__": main()
