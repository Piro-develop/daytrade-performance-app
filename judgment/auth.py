"""Validate existing Firebase identities without admin keys or changing Firebase settings."""
import base64
import hashlib
import json
from pathlib import Path
import re
import threading
import time
import requests

class AuthenticationError(ValueError):
    pass

class FirebaseIdentity:
    def __init__(self, root: Path):
        source=(root/"app.js").read_text(encoding="utf-8")
        self.api_key=re.search(r'apiKey:\s*"([^"]+)"',source).group(1)
        self.project=re.search(r'projectId:\s*"([^"]+)"',source).group(1)
        self.cache={}
        self.lock=threading.Lock()

    def verify(self, token: str) -> str:
        if not token or len(token)>8192:
            raise AuthenticationError("Googleログインを確認してください。")
        now=time.time()
        key=hashlib.sha256(token.encode()).hexdigest()
        with self.lock:
            known=self.cache.get(key)
            if known and known[1]>now:
                return known[0]
        try:
            parts=token.split(".")
            if len(parts)!=3: raise ValueError()
            claims=json.loads(base64.urlsafe_b64decode(parts[1]+"="*(-len(parts[1])%4)))
            expiry=float(claims["exp"])
            if (claims.get("aud")!=self.project or claims.get("iss")!="https://securetoken.google.com/"+self.project
                or not claims.get("sub") or expiry<=now or float(claims["iat"])>now+60):
                raise ValueError()
            # Claims above are NOT trusted until Google's endpoint validates the ID token.
            response=requests.post("https://identitytoolkit.googleapis.com/v1/accounts:lookup",
                params={"key":self.api_key},json={"idToken":token},timeout=10,allow_redirects=False)
            if response.status_code!=200: raise ValueError()
            users=response.json().get("users",[])
            if len(users)!=1 or users[0].get("disabled") or users[0].get("localId")!=claims["sub"]:
                raise ValueError()
            uid=users[0]["localId"]
        except (ValueError,KeyError,TypeError,requests.RequestException) as exc:
            raise AuthenticationError("ログイン情報を確認できません。再ログインしてお試しください。") from exc
        with self.lock:
            self.cache={k:v for k,v in self.cache.items() if v[1]>now}
            if len(self.cache)>1000: self.cache.clear()
            self.cache[key]=(uid,min(expiry,now+60))
        return uid
