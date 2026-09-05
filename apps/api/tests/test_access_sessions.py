import json

import pytest
from closegraph.api.app import create_app
from closegraph.api.auth import DevAccount, LocalAuth, hash_password, verify_password
from closegraph.contracts import Scope
from test_routes_client import ASGIClient

S = Scope(tenant_id="tenant",fund_id="fund",pack_id="pack")


def auth():
    return LocalAuth(accounts=[DevAccount.create("preparer", "test-only-password", "PREPARER", [S]),
                               DevAccount.create("reviewer", "another-test-password", "REVIEWER", [S])])


def login(client, username="preparer", password="test-only-password"):
    status,headers,body = client.request("POST", "/api/session/login", {"username":username,"password":password})
    assert status == 200, body
    return json.loads(body)["csrf_token"],headers


def test_password_hash_and_local_only_config():
    a,b=hash_password("not-a-real-secret"),hash_password("not-a-real-secret")
    assert a != b and "not-a-real-secret" not in a
    assert verify_password("not-a-real-secret",a) and not verify_password("wrong",a)
    assert not verify_password("anything","bad-hash")
    with pytest.raises(ValueError): create_app(bind_host="0.0.0.0")


def test_cookie_auth_csrf_origin_and_logout():
    client=ASGIClient(create_app(auth=auth()))
    assert client.request("GET","/api/packs")[0] == 401
    assert client.request("POST","/api/session/login",{"username":"preparer","password":"wrong"})[0] == 401
    csrf, headers=login(client)
    cookie=headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie and "path=/api" in cookie
    assert client.request("GET","/api/session")[0] == 200
    assert client.request("POST","/api/session/logout")[0] == 403
    assert client.request("POST","/api/session/logout",headers={"x-csrf-token":csrf,"origin":"https://evil.test"})[0] == 403
    assert client.request("POST","/api/session/logout",headers={"x-csrf-token":csrf})[0] == 204
    assert client.request("GET","/api/session")[0] == 401


def test_remote_host_and_remote_peer_refused():
    client=ASGIClient(create_app(auth=auth()))
    assert client.request("GET","/api/health",host="evil.test")[0] == 403
    assert client.request("GET","/api/health",client="198.51.100.2")[0] == 403
    assert client.request("POST","/api/session/login",{"username":"preparer","password":"test-only-password"},headers={"origin":"https://evil.test"})[0] == 403


def test_account_revocation_and_session_expiry():
    store=auth(); client=ASGIClient(create_app(auth=store)); login(client)
    store.disable("preparer")
    assert client.request("GET","/api/session")[0] == 401
    clock=[100.0]
    store=LocalAuth(accounts=[DevAccount.create("p","test-only-password","PREPARER",[S])],clock=lambda:clock[0],ttl_seconds=10)
    client=ASGIClient(create_app(auth=store)); login(client,"p")
    clock[0]=111
    assert client.request("GET","/api/session")[0] == 401


def test_login_schema_and_errors_do_not_echo_passwords():
    c = ASGIClient(create_app(auth=auth()))
    for body in [
        {"username":"preparer", "password":"test-only-password", "role":"REVIEWER"},
        {"username":"preparer", "password":{"secret":"do-not-echo"}},
    ]:
        status, _, response = c.request("POST", "/api/session/login", body)
        assert status == 422
        assert b"test-only-password" not in response and b"do-not-echo" not in response


def test_unknown_host_null_origin_forwarded_and_body_limit():
    c = ASGIClient(create_app(auth=auth()))
    for headers in [{"origin":"null"}, {"origin":""}, {"origin":"http://localhost.evil.test"},
                    {"origin":"http://localhost/"}, {"x-forwarded-for":"127.0.0.1"}]:
        assert c.request("POST", "/api/session/login", {}, headers)[0] == 403
    for host in ["localhost.evil.test", "localhost@evil.test", "localhost:bad", "localhost/path"]:
        assert c.request("GET", "/api/health", host=host)[0] == 403
    assert c.request("POST", "/api/session/login", {"password":"x"*70000})[0] == 413


def test_csrf_is_session_bound_and_logout_revokes_copied_cookie():
    store = auth(); app = create_app(auth=store)
    a, b = ASGIClient(app), ASGIClient(app)
    csrf_a, _ = login(a); csrf_b, _ = login(b)
    assert csrf_a != csrf_b
    assert a.request("POST", "/api/session/logout", headers={"x-csrf-token":csrf_b})[0] == 403
    copied = dict(a.cookies)
    assert a.request("POST", "/api/session/logout", headers={"x-csrf-token":csrf_a})[0] == 204
    a.cookies = copied
    assert a.request("GET", "/api/session")[0] == 401


def test_explicit_loopback_frontend_origin_and_no_scope_collisions():
    app = create_app(auth=auth(), allowed_origins=("http://localhost:5173",))
    c = ASGIClient(app)
    assert c.request("POST", "/api/session/login", {"username":"preparer", "password":"test-only-password"},
                     {"origin":"http://localhost:5173"}, host="localhost:8000")[0] == 200
    with pytest.raises(ValueError): create_app(allowed_origins=("https://remote.example",))
    with pytest.raises(ValueError):
        LocalAuth(accounts=[DevAccount.create("p", "test-only-password", "PREPARER",
            [S, S.model_copy(update={"tenant_id":"other"})])])
