"""Loopback FastAPI adapter. Supply a PackServices facade to enable pack routes.

This app deliberately does not bootstrap a DB, seed accounts or implement domain
rules. Use one worker, bind to loopback, and disable proxy-header trust in the ASGI
server. Prefer a same-origin frontend proxy; explicit loopback origins can be
allowed but this app does not enable wildcard CORS.
"""
import ipaddress
import re
from typing import Annotated
from urllib.parse import quote, urlsplit

from closegraph.contracts import (
    Contract,
    CorrectionRequest,
    Identifier,
    PackSnapshot,
    ReviewRequest,
    Scope,
    VersionAction,
    UploadRequest,
    RejectRequest,
    ResolutionRequest,
    ReviewEventRequest,
)
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from pydantic import Field, SecretStr
from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import JSONResponse

from .auth import LocalAuth, Principal
from .ports import (
    DomainConflict,
    DomainForbidden,
    DomainNotFound,
    DomainUnavailable,
    PackServices,
)

COOKIE_NAME = "closegraph_session"
_UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}


def _loopback(host: str) -> bool:
    if host == "localhost":
        return True
    if "%" in host:
        return False
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _authority(value: str) -> tuple[str, int | None]:
    if not value or any(c.isspace() for c in value) or any(c in value for c in "/\\?#@"):
        raise ValueError("invalid local authority")
    parsed = urlsplit("//" + value)
    if not parsed.hostname or not _loopback(parsed.hostname) or value.endswith(":"):
        raise ValueError("not a loopback authority")
    port = parsed.port  # validates numeric syntax and range
    if port == 0:
        raise ValueError("invalid port")
    return parsed.hostname, port


def _origin(value: str) -> tuple[str, str, int]:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or parsed.path or parsed.query or parsed.fragment:
        raise ValueError("invalid local origin")
    host, port = _authority(parsed.netloc)
    return parsed.scheme, host, port or (443 if parsed.scheme == "https" else 80)


class LocalBoundaryMiddleware:
    """Check peer + Host (DNS rebinding) + Origin before reading request data."""

    def __init__(self, app, *, allowed_origins, max_request_bytes):
        self.app = app
        self.origins = frozenset(_origin(value) for value in allowed_origins)
        self.max_request_bytes = max_request_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            if scope["type"] == "websocket":
                await send({"type":"websocket.close", "code":1008})
            else:
                await self.app(scope, receive, send)
            return

        async def secure_send(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["cache-control"] = "no-store"
                headers["x-content-type-options"] = "nosniff"
                headers["referrer-policy"] = "no-referrer"
                headers["x-frame-options"] = "DENY"
            await send(message)

        async def reject(status, detail):
            await JSONResponse({"detail":detail}, status_code=status)(scope, receive, secure_send)

        headers = Headers(scope=scope)
        try:
            peer = scope.get("client")
            # A socket peer must be a literal loopback IP, never a hostname.
            if not peer or not ipaddress.ip_address(peer[0]).is_loopback:
                raise ValueError("remote peer")
            if len(headers.getlist("host")) != 1 or len(headers.getlist("origin")) > 1:
                raise ValueError("ambiguous request authority")
            _authority(headers["host"])
            if any(name == "forwarded" or name.startswith("x-forwarded-") for name in headers):
                raise ValueError("proxy headers are not supported")
            origin = headers.get("origin")
            if origin is not None:
                actual = _origin(origin)
                same_origin = _origin(scope.get("scheme", "http") + "://" + headers["host"])
                if actual != same_origin and actual not in self.origins:
                    raise ValueError("untrusted origin")
            elif scope["method"] in _UNSAFE:
                raise ValueError("origin required")
            if headers.get("sec-fetch-site") == "cross-site":
                raise ValueError("cross-site request")
        except (ValueError, KeyError, TypeError):
            await reject(403, "local request boundary denied")
            return

        if scope["method"] in _UNSAFE:
            chunks, size = [], 0
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                chunk = message.get("body", b"")
                size += len(chunk)
                if size > self.max_request_bytes:
                    await reject(413, "request body exceeds limit")
                    return
                chunks.append(chunk)
                if not message.get("more_body", False):
                    break
            sent = False

            async def replay():
                nonlocal sent
                if not sent:
                    sent = True
                    return {"type":"http.request", "body":b"".join(chunks), "more_body":False}
                return await receive()

            await self.app(scope, replay, secure_send)
        else:
            await self.app(scope, receive, secure_send)


class LoginRequest(Contract):
    username: Identifier
    password: Annotated[SecretStr, Field(min_length=1, max_length=1024)]


def create_app(*, auth: LocalAuth | None = None, services: PackServices | None = None,
               bind_host: str = "127.0.0.1", allowed_origins: tuple[str, ...] = (),
               cookie_secure: bool = False, max_request_bytes: int = 65536) -> FastAPI:
    if not _loopback(bind_host):
        raise ValueError("development API must bind to loopback")
    for origin in allowed_origins:
        _origin(origin)
    if type(max_request_bytes) is not int or max_request_bytes < 1:
        raise ValueError("max_request_bytes must be positive")
    auth = auth if auth is not None else LocalAuth()
    app = FastAPI(title="CloseGraph local API", version="0.1.0", docs_url=None, redoc_url=None,
                  openapi_url="/api/openapi.json")
    app.state.auth, app.state.services = auth, services
    app.add_middleware(LocalBoundaryMiddleware, allowed_origins=allowed_origins,
                       max_request_bytes=max_request_bytes)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, exc):
        # FastAPI's default errors include submitted input, including passwords.
        return JSONResponse({"detail":[{"loc":error["loc"], "type":error["type"],
                                       "msg":"Invalid request field"} for error in exc.errors()]}, status_code=422)

    @app.exception_handler(DomainNotFound)
    async def not_found(request, exc):
        return JSONResponse({"detail":"not found"}, status_code=404)

    @app.exception_handler(DomainConflict)
    async def conflict(request, exc):
        return JSONResponse({"detail":str(exc) or "domain conflict"}, status_code=409)

    @app.exception_handler(DomainForbidden)
    async def forbidden(request, exc):
        return JSONResponse({"detail":"forbidden"}, status_code=403)

    @app.exception_handler(DomainUnavailable)
    async def unavailable(request, exc):
        return JSONResponse({"detail":"domain services unavailable"}, status_code=503)

    def principal(request: Request) -> Principal:
        resolved = auth.resolve(request.cookies.get(COOKIE_NAME))
        if resolved is None:
            raise HTTPException(401, "authentication required")
        return resolved

    def mutation(request: Request, user: Annotated[Principal, Depends(principal)]) -> Principal:
        if not auth.check_csrf(user, request.headers.get("x-csrf-token")):
            raise HTTPException(403, "invalid CSRF token")
        return user

    def scoped(pack_id: str, user: Principal) -> Scope:
        scope = user.scope_for(pack_id)
        if scope is None:
            raise DomainNotFound()
        return scope

    def facade() -> PackServices:
        if services is None:
            raise DomainUnavailable()
        return services

    def snapshot(scope: Scope, result: PackSnapshot) -> PackSnapshot:
        result = PackSnapshot.model_validate(result)
        if result.pack_id != scope.pack_id or result.fund_id != scope.fund_id:
            raise DomainUnavailable()
        return result

    def session_payload(user: Principal):
        return {"actor":user.actor.model_dump(mode="json"),
                "scopes":[scope.model_dump(mode="json") for scope in user.scopes],
                "csrf_token":user.csrf_token,
                "collection_funds":auth.collection_funds(user.actor.actor_id)}

    @app.get("/api/health")
    def health():
        return {"status":"ok", "service":"closegraph-api",
                "domain_services":"configured" if services is not None else "unconfigured"}

    @app.post("/api/session/login")
    def login(command: LoginRequest, request: Request, response: Response):
        authenticated = auth.login(command.username, command.password.get_secret_value())
        if authenticated is None:
            raise HTTPException(401, "invalid credentials")
        auth.logout(request.cookies.get(COOKIE_NAME))
        token, user = authenticated
        response.set_cookie(COOKIE_NAME, token, max_age=auth.ttl_seconds, httponly=True,
                            secure=cookie_secure, samesite="strict", path="/api")
        return session_payload(user)

    @app.get("/api/session")
    def session(user: Annotated[Principal, Depends(principal)]):
        return session_payload(user)

    @app.post("/api/session/logout", status_code=204)
    def logout(request: Request, user: Annotated[Principal, Depends(mutation)]):
        auth.logout(request.cookies.get(COOKIE_NAME))
        response = Response(status_code=204)
        response.delete_cookie(COOKIE_NAME, path="/api", httponly=True,
                               secure=cookie_secure, samesite="strict")
        return response

    @app.get("/api/packs", response_model=list[PackSnapshot])
    def packs(user: Annotated[Principal, Depends(principal)]):
        service = facade()
        result = []
        for scope in user.scopes:
            try:
                result.append(snapshot(scope, service.get_pack(scope, user.actor)))
            except DomainNotFound:
                continue
        return result

    @app.get("/api/packs/{pack_id}", response_model=PackSnapshot)
    def pack(pack_id: str, user: Annotated[Principal, Depends(principal)]):
        scope = scoped(pack_id, user)
        return snapshot(scope, facade().get_pack(scope, user.actor))

    @app.post("/api/packs/{pack_id}/review-events", status_code=201)
    def review_event(pack_id: str, command: ReviewEventRequest, user: Annotated[Principal, Depends(mutation)]):
        return facade().record_review_event(scoped(pack_id,user), user.actor, command)

    @app.get("/api/packs/{pack_id}/review-work")
    def review_work(pack_id: str, user: Annotated[Principal, Depends(principal)]):
        return facade().review_work(scoped(pack_id,user), user.actor)

    @app.post("/api/packs/{pack_id}/corrections", response_model=PackSnapshot)
    def correct(pack_id: str, command: CorrectionRequest, user: Annotated[Principal, Depends(mutation)]):
        scope = scoped(pack_id, user)
        if user.actor.role != "PREPARER":
            raise DomainForbidden()
        return snapshot(scope, facade().correct(scope, user.actor, command))

    @app.post("/api/packs/{pack_id}/recompute", response_model=PackSnapshot)
    def recompute(pack_id: str, command: VersionAction, user: Annotated[Principal, Depends(mutation)]):
        scope = scoped(pack_id, user)
        if user.actor.role != "PREPARER":
            raise DomainForbidden()
        return snapshot(scope, facade().recompute(scope, user.actor, command))

    @app.post("/api/packs/{pack_id}/review", response_model=PackSnapshot)
    def review(pack_id: str, command: ReviewRequest, user: Annotated[Principal, Depends(mutation)]):
        scope = scoped(pack_id, user)
        if user.actor.role != "REVIEWER":
            raise DomainForbidden()
        return snapshot(scope, facade().review(scope, user.actor, command))

    @app.post("/api/packs/{pack_id}/publish", response_model=PackSnapshot)
    def publish(pack_id: str, command: VersionAction, user: Annotated[Principal, Depends(mutation)]):
        scope = scoped(pack_id, user)
        return snapshot(scope, facade().publish(scope, user.actor, command))

    @app.post("/api/packs/{pack_id}/uploads", response_model=PackSnapshot)
    def upload(pack_id: str, command: UploadRequest, user: Annotated[Principal, Depends(mutation)]):
        scope = scoped(pack_id, user)
        if user.actor.role != "PREPARER":
            raise DomainForbidden()
        return snapshot(scope, facade().upload(scope, user.actor, command))

    @app.post("/api/packs/{pack_id}/review/resolve", response_model=PackSnapshot)
    def resolve_review(pack_id: str, command: ResolutionRequest, user: Annotated[Principal, Depends(mutation)]):
        scope = scoped(pack_id, user)
        if user.actor.role != "REVIEWER":
            raise DomainForbidden()
        return snapshot(scope, facade().resolve(scope, user.actor, command))

    @app.post("/api/packs/{pack_id}/review/reject", response_model=PackSnapshot)
    def reject_review(pack_id: str, command: RejectRequest, user: Annotated[Principal, Depends(mutation)]):
        scope = scoped(pack_id, user)
        if user.actor.role != "REVIEWER":
            raise DomainForbidden()
        return snapshot(scope, facade().reject(scope, user.actor, command))

    @app.get("/api/packs/{pack_id}/history/{version}", response_model=PackSnapshot)
    def history(pack_id: str, version: int, user: Annotated[Principal, Depends(principal)]):
        scope = scoped(pack_id, user)
        return snapshot(scope, facade().get_history(scope, user.actor, version))

    @app.get("/api/packs/{pack_id}/documents/{document_version_id}")
    def document(pack_id: str, document_version_id: str, user: Annotated[Principal, Depends(principal)]):
        scope = scoped(pack_id,user)
        return facade().document(scope,user.actor,document_version_id)

    @app.get("/api/packs/{pack_id}/documents/{document_version_id}/download")
    def download_document(pack_id: str, document_version_id: str, user: Annotated[Principal, Depends(principal)]):
        scope = scoped(pack_id,user)
        artifact = facade().download_document(scope,user.actor,document_version_id)
        return Response(artifact.content, media_type=artifact.media_type,
                        headers={"Content-Disposition":"attachment; filename*=UTF-8''" + quote(artifact.filename, safe="")})

    @app.get("/api/packs/{pack_id}/evidence/{source_id}")
    def evidence(pack_id: str, source_id: str, user: Annotated[Principal, Depends(principal)]):
        scope = scoped(pack_id, user)
        return facade().evidence(scope, user.actor, source_id)

    @app.get("/api/packs/{pack_id}/evidence/{source_id}/download")
    def download_evidence(pack_id: str, source_id: str, user: Annotated[Principal, Depends(principal)]):
        scope = scoped(pack_id, user)
        artifact = facade().download_evidence(scope, user.actor, source_id)
        if not isinstance(artifact.content, bytes) or not re.fullmatch(r"[\w.+-]+/[\w.+-]+", artifact.media_type):
            raise DomainUnavailable()
        return Response(artifact.content, media_type=artifact.media_type,
                        headers={"Content-Disposition":"attachment; filename*=UTF-8''" + quote(artifact.filename, safe="")})

    @app.get("/api/packs/{pack_id}/artifacts/{artifact_id}/download")
    def download(pack_id: str, artifact_id: str, user: Annotated[Principal, Depends(principal)],
                 publication_id: str | None = None):
        scope = scoped(pack_id, user)
        artifact = (facade().download(scope, user.actor, artifact_id, publication_id=publication_id)
                    if publication_id is not None else facade().download(scope, user.actor, artifact_id))
        if not isinstance(artifact.content, bytes) or not re.fullmatch(r"[\w.+-]+/[\w.+-]+", artifact.media_type):
            raise DomainUnavailable()
        return Response(artifact.content, media_type=artifact.media_type,
                        headers={"Content-Disposition":"attachment; filename*=UTF-8''" + quote(artifact.filename, safe="")})

    from closegraph.collections.routes import collection_router
    app.include_router(collection_router(auth, getattr(services,'collections',None)))
    return app
