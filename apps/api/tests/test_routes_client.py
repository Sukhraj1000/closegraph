"""Real ASGI request helper: no socket, TestClient or mocked HTTP server."""
import asyncio
import json
from http.cookies import SimpleCookie
from urllib.parse import urlsplit


class ASGIClient:
    def __init__(self, app):
        self.app, self.cookies = app, {}

    def request(self, method, path, body=None, headers=None, host="localhost", client="127.0.0.1"):
        async def invoke():
            sent = False
            data = b"" if body is None else json.dumps(body).encode()
            hs = {"host":host, "content-type":"application/json", "origin":"http://localhost"}
            hs.update(headers or {})
            hs["cookie"] = "; ".join(f"{k}={v}" for k,v in self.cookies.items())
            scope = {"type": "http", "asgi": {"version":"3.0"}, "http_version": "1.1", "method": method,
                         "scheme": "http", "path": urlsplit(path).path, "raw_path": urlsplit(path).path.encode(),
                         "query_string": urlsplit(path).query.encode(), "root_path": "",
                         "headers": [(k.lower().encode(),v.encode()) for k,v in hs.items()],
                         "client": (client,1234),"server": (host,80)}
            messages = []
            async def receive():
                nonlocal sent
                if not sent:
                    sent=True
                    return {"type":"http.request","body":data,"more_body":False}
                await asyncio.Event().wait()
            async def send(message): messages.append(message)
            await self.app(scope,receive,send)
            start = next(m for m in messages if m["type"]=="http.response.start")
            for k,v in start["headers"]:
                if k == b"set-cookie":
                    cookie=SimpleCookie(); cookie.load(v.decode())
                    self.cookies.update({k:m.value for k,m in cookie.items()})
            payload = b"".join(m.get("body",b"") for m in messages if m["type"]=="http.response.body")
            return start["status"], {k.decode(): v.decode() for k,v in start["headers"]}, payload
        return asyncio.run(invoke())
