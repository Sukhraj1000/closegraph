"""Synthetic offline contract tests: no provider calls, source disclosure or secrets."""
import base64
from hashlib import sha256
import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace
from urllib.error import URLError
from unittest.mock import Mock

import pytest
from closegraph.collections import provider
from closegraph.contracts import Scope

PDF = b"%PDF-1.7\nFictional offline provider contract fixture\n%%EOF"
DIGEST = sha256(PDF).hexdigest()
SCOPE = Scope(tenant_id="test", fund_id="fictional", pack_id="collection-offline")
RAW = json.dumps({"job_id":"offline-response", "result":{"type":"full", "chunks":[{"blocks":[{"type":"Text", "content":"Fictional extraction", "bbox":{"left":0.1,"top":0.1,"width":0.3,"height":0.2,"page":1,"original_page":1}}]}]}}).encode()
UPLOAD = json.dumps({"file_id":"reducto://offline-fixture"}).encode()
SETTINGS = {"persist_results":False,"force_url_result":False}

def envelope(**changes):
    return {"mode":"LIVE","source_sha256":DIGEST,"endpoint":"https://platform.reducto.ai","request_settings":SETTINGS,
            "raw_response_base64":base64.b64encode(RAW).decode(),"upload_response_base64":base64.b64encode(UPLOAD).decode(),**changes}

def fake_transport(monkeypatch, module, responses):
    requests=[]
    class Opener:
        def open(self,request,timeout):
            requests.append((request,timeout))
            response=responses.pop(0)
            if isinstance(response,Exception):raise response
            return io.BytesIO(response)
    build=Mock(return_value=Opener());monkeypatch.setattr(module,"build_opener",build)
    return requests,build

def parse():
    return provider.GatewayProvider("http://127.0.0.1:24183/parse","offline-gateway-token").parse_pdf(PDF,scope=SCOPE,document_version_id="original-v1")

def test_missing_configuration_is_unavailable_without_a_fallback():
    assert provider.collection_pdf_provider({}) is None
    with pytest.raises(ValueError):provider.collection_pdf_provider({"CLOSEGRAPH_PDF_GATEWAY_URL":"http://127.0.0.1:24183/parse"})

@pytest.mark.parametrize("endpoint",["https://platform.reducto.ai/parse","http://localhost:24183/parse","http://127.0.0.1:24183/other","http://127.0.0.1:24184/parse","https://untrusted.invalid/parse"])
def test_only_exact_loopback_gateway_is_configurable(endpoint):
    with pytest.raises(ValueError):provider.GatewayProvider(endpoint,"offline-token")

def test_provider_sends_scope_and_exact_hash_and_preserves_actual_responses(monkeypatch):
    requests,build=fake_transport(monkeypatch,provider,[json.dumps(envelope()).encode()])
    result=parse();assert result.available and result.mode=="LIVE"
    assert result.raw_response==RAW and result.upload_response==UPLOAD
    assert result.source_hash==DIGEST and result.response_hash==sha256(RAW).hexdigest()
    request,timeout=requests[0];payload=json.loads(request.data)
    assert request.full_url=="http://127.0.0.1:24183/parse" and timeout==250
    assert request.get_header("Authorization")=="Bearer offline-gateway-token"
    assert payload["scope"]==SCOPE.model_dump(mode="json") and payload["document_version_id"]=="original-v1"
    assert payload["source_sha256"]==DIGEST and base64.b64decode(payload["source_base64"])==PDF
    assert build.call_args.args[0].proxies=={}
    assert isinstance(build.call_args.args[1],provider._NoRedirect)

@pytest.mark.parametrize("changes",[
    {"source_sha256":"0"*64},{"mode":"REPLAY"},{"endpoint":"https://untrusted.invalid"},
    {"request_settings":{"persist_results":True,"force_url_result":False}},
    {"raw_response_base64":"!not-base64!"},
    {"upload_response_base64":base64.b64encode(b'{"file_id":"https://untrusted.invalid/file"}').decode()},
    {"upload_response_base64":base64.b64encode(b'{}').decode()},
    {"raw_response_base64":base64.b64encode(b'{"job_id":"other","result":{"type":"url","url":"https://untrusted.invalid"}}').decode()},
])
def test_response_mismatch_or_untrusted_reference_never_becomes_available(monkeypatch,changes):
    requests,_=fake_transport(monkeypatch,provider,[json.dumps(envelope(**changes)).encode()])
    result=parse();assert not result.available and result.mode=="LIVE"
    assert len(requests)==1

@pytest.mark.parametrize("failure",[URLError("offline transport"),TimeoutError("offline timeout"),ValueError("rejected redirect")])
def test_failed_gateway_transport_is_an_unavailable_observation(monkeypatch,failure):
    fake_transport(monkeypatch,provider,[failure]);result=parse()
    assert not result.available and result.occurrences==()
    assert "offline transport" not in str(result.diagnostics)

def test_non_pdf_and_oversized_source_never_calls_gateway(monkeypatch):
    build=Mock();monkeypatch.setattr(provider,"build_opener",build);monkeypatch.setattr(provider,"MAX_BYTES",8)
    client=provider.GatewayProvider("http://127.0.0.1:24183/parse","offline-token")
    for content in (b"not-pdf",PDF):assert not client.parse_pdf(content,scope=SCOPE,document_version_id="v1").available
    build.assert_not_called()

@pytest.fixture
def gateway():
    # Script imports are performed only by this worker-side test process.
    path=Path(__file__).resolve().parents[4]/"scripts"/"reducto_gateway.py"
    spec=importlib.util.spec_from_file_location("closegraph_offline_gateway_test",path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module

@pytest.fixture
def config():
    return {"api_key":"fictional-offline-provider-key","token":"x"*40,"authorized_source_hashes":[DIGEST],"authorization_reference":"synthetic offline test only","data_handling_note":"No network calls in this test"}

def payload(**changes):
    return {"source_base64":base64.b64encode(PDF).decode(),"source_sha256":DIGEST,**changes}

def test_private_config_requires_credentials_and_exact_authorization(gateway,config,tmp_path):
    path=tmp_path/"gateway.json";path.write_text(json.dumps(config));path.chmod(0o600)
    assert gateway.read_config(path)==config
    for key in ("api_key","token","authorized_source_hashes","authorization_reference","data_handling_note"):
        path.write_text(json.dumps({k:v for k,v in config.items() if k!=key}))
        with pytest.raises(ValueError):gateway.read_config(path)
    path.write_text(json.dumps(config));path.chmod(0o644)
    with pytest.raises(ValueError):gateway.read_config(path)
    path.chmod(0o600);link=tmp_path/"symlink.json";link.symlink_to(path)
    with pytest.raises(ValueError):gateway.read_config(link)

@pytest.mark.parametrize("change",[{"source_sha256":"0"*64},{"source_base64":"!bad!"}])
def test_gateway_rejects_hash_mismatch_before_transport(gateway,config,monkeypatch,change):
    build=Mock();monkeypatch.setattr(gateway,"build_opener",build)
    with pytest.raises(ValueError):gateway.process(payload(**change),config)
    build.assert_not_called()

def test_gateway_source_allowlist_cannot_be_overridden_by_worker_payload(gateway,config,monkeypatch):
    build=Mock();monkeypatch.setattr(gateway,"build_opener",build)
    with pytest.raises(ValueError):gateway.process(payload(authorized_source_hashes=[DIGEST],api_key="attacker",endpoint="https://untrusted.invalid"),{**config,"authorized_source_hashes":["0"*64]})
    build.assert_not_called()

def test_gateway_only_calls_fixed_endpoints_and_fixed_retention_settings(gateway,config,monkeypatch):
    requests,build=fake_transport(monkeypatch,gateway,[UPLOAD,RAW])
    result=gateway.process(payload(endpoint="https://untrusted.invalid",request_settings={"persist_results":True}),config)
    assert [request.full_url for request,_ in requests]==["https://platform.reducto.ai/upload","https://platform.reducto.ai/parse"]
    assert all(timeout==120 for _,timeout in requests)
    assert all(request.get_header("Authorization")=="Bearer fictional-offline-provider-key" for request,_ in requests)
    assert json.loads(requests[1][0].data)=={"input":"reducto://offline-fixture","settings":SETTINGS}
    assert result["source_sha256"]==DIGEST and result["endpoint"]=="https://platform.reducto.ai" and result["mode"]=="LIVE"
    assert base64.b64decode(result["raw_response_base64"])==RAW
    assert build.call_args.args[0].proxies=={}
    assert isinstance(build.call_args.args[1],gateway.NoRedirect)

@pytest.mark.parametrize("response",[b'{"file_id":"https://untrusted.invalid"}',b'{"file_id":1}',b'{}'])
def test_gateway_invalid_upload_reference_stops_before_parse(gateway,config,monkeypatch,response):
    requests,_=fake_transport(monkeypatch,gateway,[response])
    with pytest.raises((ValueError,KeyError)):gateway.process(payload(),config)
    assert len(requests)==1

def test_gateway_failed_and_oversized_provider_responses_stop_processing(gateway,config,monkeypatch):
    requests,_=fake_transport(monkeypatch,gateway,[URLError("offline")])
    with pytest.raises(URLError):gateway.process(payload(),config)
    assert len(requests)==1
    monkeypatch.setattr(gateway,"MAX_RESPONSE",4)
    requests,_=fake_transport(monkeypatch,gateway,[b"oversized"])
    with pytest.raises(ValueError,match="response_limit"):gateway.process(payload(),config)
    assert len(requests)==1

def test_gateway_redirects_are_refused(gateway):
    with pytest.raises(ValueError,match="redirect_refused"):gateway.NoRedirect().redirect_request(None,None,302,"redirect",{},"https://untrusted.invalid")

def test_http_gateway_requires_capability_before_processing(gateway,config,tmp_path,monkeypatch):
    path=tmp_path/"gateway.json";path.write_text(json.dumps(config));path.chmod(0o600);captured={}
    class Server:
        def __init__(self,address,handler):captured.update(address=address,handler=handler)
        def serve_forever(self):pass
    monkeypatch.setattr(gateway,"ThreadingHTTPServer",Server)
    process=Mock();monkeypatch.setattr(gateway,"process",process);gateway.serve(path)
    assert captured["address"]==("127.0.0.1",24183)
    for route,authorization in (("/parse","Bearer wrong-token"),("/other","Bearer "+config["token"])):
        handler=object.__new__(captured["handler"]);handler.path=route;handler.headers={"Authorization":authorization};handler.connection=SimpleNamespace(settimeout=lambda value:None);handler.send_error=Mock()
        handler.do_POST();handler.send_error.assert_called_once_with(403)
    process.assert_not_called()
