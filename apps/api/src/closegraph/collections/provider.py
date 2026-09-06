"""Bounded loopback capability; provider credentials never enter the worker."""
import base64
from dataclasses import replace
from hashlib import sha256
import json
from urllib.request import Request, build_opener, ProxyHandler
from closegraph.extractors.reducto import decode_response, _NoRedirect, ReductoResult

MAX_BYTES=32*1024*1024

class GatewayProvider:
    def __init__(self,endpoint,token):
        if endpoint!='http://127.0.0.1:24183/parse' or not token:
            raise ValueError('Configure the fixed loopback PDF gateway and token')
        self.endpoint,self.token=endpoint,token

    def parse_pdf(self,source,*,scope,document_version_id):
        digest=sha256(source).hexdigest()
        if not source.startswith(b'%PDF-') or len(source)>MAX_BYTES:
            return ReductoResult('UNAVAILABLE',digest,diagnostics=('unsupported_pdf_signature_or_size',),mode='LIVE')
        payload={'source_base64':base64.b64encode(source).decode(),'source_sha256':digest,
                 'scope':scope.model_dump(mode='json'),'document_version_id':document_version_id}
        request=Request(self.endpoint,data=json.dumps(payload).encode(),method='POST',headers={
            'Content-Type':'application/json','Authorization':'Bearer '+self.token})
        try:
            with build_opener(ProxyHandler({}),_NoRedirect()).open(request,timeout=250) as response:
                body=response.read(34_000_001)
            if len(body)>34_000_000:raise ValueError('Gateway response limit')
            result=json.loads(body)
            if result['source_sha256']!=digest or result['mode']!='LIVE':raise ValueError('Gateway source mismatch')
            if result['endpoint']!='https://platform.reducto.ai' or result['request_settings']!={'persist_results':False,'force_url_result':False}:raise ValueError('Gateway handling mismatch')
            upload=base64.b64decode(result['upload_response_base64'],validate=True)
            file_id=json.loads(upload)['file_id']
            if not isinstance(file_id,str) or not file_id.startswith('reducto://') or len(file_id)>2048:raise ValueError('Invalid upload response')
            raw=base64.b64decode(result['raw_response_base64'],validate=True)
            decoded=decode_response(raw,scope=scope,document_version_id=document_version_id,
                source_sha256=digest,settings=result['request_settings'],mode='LIVE')
            return replace(decoded,upload_response=upload)
        except Exception:
            return ReductoResult('UNAVAILABLE',digest,diagnostics=('live_pdf_gateway_unavailable_or_source_not_authorized',),mode='LIVE')

class CapturedProvider:
    """Explicit development replay of immutable, hash-bound provider receipts."""
    def __init__(self,directory):
        from pathlib import Path
        self.directory=Path(directory)
    def parse_pdf(self,source,*,scope,document_version_id):
        digest=sha256(source).hexdigest()
        try:
            path=self.directory/(digest+'.json')
            if path.is_symlink() or path.stat().st_size>34_000_000:raise ValueError('Invalid receipt')
            receipt=json.loads(path.read_text())
            if receipt['source_sha256']!=digest:raise ValueError('Source mismatch')
            raw=base64.b64decode(receipt['raw_response_base64'],validate=True)
            if sha256(raw).hexdigest()!=receipt['response_sha256']:raise ValueError('Response mismatch')
            return decode_response(raw,scope=scope,document_version_id=document_version_id,source_sha256=digest,settings=receipt.get('settings',{}),mode='REPLAY')
        except Exception:
            return ReductoResult('UNAVAILABLE',digest,diagnostics=('captured_response_unavailable_or_mismatched',),mode='REPLAY')

class CachedGatewayProvider:
    def __init__(self,directory,gateway):
        self.capture=CapturedProvider(directory);self.gateway=gateway
    def parse_pdf(self,source,*,scope,document_version_id):
        digest=sha256(source).hexdigest()
        if (self.capture.directory/(digest+'.json')).exists():
            return self.capture.parse_pdf(source,scope=scope,document_version_id=document_version_id)
        return self.gateway.parse_pdf(source,scope=scope,document_version_id=document_version_id)

def collection_pdf_provider(environment):
    mode=environment.get('CLOSEGRAPH_PDF_MODE')
    if mode=='DISABLED':return None
    if mode=='CAPTURED_REPLAY':
        directory=environment.get('CLOSEGRAPH_PDF_CAPTURE_DIR')
        if not directory:raise ValueError('Configure a PDF capture directory for replay')
        return CapturedProvider(directory)
    endpoint=environment.get('CLOSEGRAPH_PDF_GATEWAY_URL')
    if not endpoint:return None
    gateway=GatewayProvider(endpoint,environment.get('CLOSEGRAPH_PDF_GATEWAY_TOKEN'))
    directory=environment.get('CLOSEGRAPH_PDF_CAPTURE_DIR')
    return CachedGatewayProvider(directory,gateway) if directory else gateway
