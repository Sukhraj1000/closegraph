#!/usr/bin/env python3
"""Trusted stdlib PDF transport. Install a reviewed copy outside the checkout.

Private config JSON: api_key, token, authorized_source_hashes, authorization_reference,
data_handling_note. No source from the worker can change this processing allowlist.
"""
import argparse
import base64
from datetime import datetime,timezone
from hashlib import sha256
import hmac
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
from pathlib import Path
import threading
from urllib.error import HTTPError
from urllib.request import Request,build_opener,ProxyHandler,HTTPRedirectHandler
import uuid

MAX_SOURCE=32*1024*1024
MAX_RESPONSE=12_000_000
ENDPOINT='https://platform.reducto.ai'
SETTINGS={'persist_results':False,'force_url_result':False}

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):raise ValueError('provider_redirect_refused')

def read_config(path):
    path=Path(path)
    if path.is_symlink() or path.stat().st_mode&0o077:raise ValueError('Gateway configuration must be private and not a symlink')
    config=json.loads(path.read_text())
    if not all(config.get(key) for key in ('api_key','token','authorized_source_hashes','authorization_reference','data_handling_note')):
        raise ValueError('Provider credentials, exact source scope and handling record required')
    if len(config['token'])<32:raise ValueError('Use a random gateway token')
    if not isinstance(config['authorized_source_hashes'],list) or any(not isinstance(x,str) or len(x)!=64 or any(c not in '0123456789abcdef' for c in x) for x in config['authorized_source_hashes']):raise ValueError('Exact source SHA256 allowlist required')
    return config

def process(payload,config):
    source=base64.b64decode(payload['source_base64'],validate=True)
    digest=sha256(source).hexdigest()
    if digest!=payload['source_sha256'] or digest not in config['authorized_source_hashes']:raise ValueError('source_not_authorized')
    if not source.startswith(b'%PDF-') or not 0<len(source)<=MAX_SOURCE:raise ValueError('pdf_signature_or_limit')
    opener=build_opener(ProxyHandler({}),NoRedirect())
    def call(path,body,content_type):
        if path not in ('/upload','/parse'):raise ValueError('invalid_endpoint')
        request=Request(ENDPOINT+path,data=body,method='POST',headers={
            'Authorization':'Bearer '+config['api_key'],'Content-Type':content_type})
        with opener.open(request,timeout=120) as response:raw=response.read(MAX_RESPONSE+1)
        if len(raw)>MAX_RESPONSE:raise ValueError('provider_response_limit')
        return raw
    boundary='closegraph-'+uuid.uuid4().hex
    body=('--'+boundary+'\r\nContent-Disposition: form-data; name="file"; filename="authorized.pdf"\r\nContent-Type: application/pdf\r\n\r\n').encode()+source+('\r\n--'+boundary+'--\r\n').encode()
    upload=call('/upload',body,'multipart/form-data; boundary='+boundary)
    file_id=json.loads(upload)['file_id']
    if not isinstance(file_id,str) or not file_id.startswith('reducto://') or len(file_id)>2048:raise ValueError('invalid_file_reference')
    raw=call('/parse',json.dumps({'input':file_id,'settings':SETTINGS}).encode(),'application/json')
    return {'mode':'LIVE','source_sha256':digest,'raw_response_base64':base64.b64encode(raw).decode(),
            'upload_response_base64':base64.b64encode(upload).decode(),'request_settings':SETTINGS,
            'executed_at':datetime.now(timezone.utc).isoformat(),'endpoint':ENDPOINT}

def serve(config_path):
    # Reload private scope for each request; independent access slots bound paid requests.
    read_config(config_path);semaphore=threading.BoundedSemaphore(2)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            self.connection.settimeout(20)
            try:
                config=read_config(config_path)
                if self.path!='/parse' or not hmac.compare_digest(self.headers.get('Authorization',''),'Bearer '+config['token']):
                    self.send_error(403);return
                if self.headers.get('Transfer-Encoding'):self.send_error(400);return
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=45*1024*1024:self.send_error(413);return
                if not semaphore.acquire(blocking=False):self.send_error(429);return
                try:
                    data=self.rfile.read(length)
                    if len(data)!=length:raise ValueError('incomplete_request')
                    result=process(json.loads(data),config)
                finally:semaphore.release()
                body=json.dumps(result,separators=(',',':')).encode()
                self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
            except Exception:
                self.send_error(502,'PDF provider unavailable or source not authorized')
    server=ThreadingHTTPServer(('127.0.0.1',24183),Handler);server.daemon_threads=True;server.serve_forever()

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--config',required=True);args=parser.parse_args();serve(args.config)
