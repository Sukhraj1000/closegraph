"""Single-process, loopback-only development authentication, not production IAM.

No default credentials. Configure accounts/grants on the server. Sessions are
opaque, memory-only and invalid after restart; run exactly one API worker.
"""
import hashlib
import hmac
import secrets
import time
from collections.abc import Callable, Iterable
from contextlib import contextmanager
from dataclasses import dataclass
from threading import RLock

from closegraph.contracts import Contract, Identifier, Scope
from pydantic import Field, StrictBool, model_validator

from .ports import Actor, Role

_SCRYPT_N = 32768


def _derive(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=_SCRYPT_N,
                          r=8, p=1, dklen=32, maxmem=64 * 1024 * 1024)


def hash_password(password: str) -> str:
    if not isinstance(password, str) or not 12 <= len(password) <= 1024:
        raise ValueError("development passwords must contain 12..1024 characters")
    salt = secrets.token_bytes(16)
    return f"scrypt${_SCRYPT_N}$8$1${salt.hex()}${_derive(password, salt).hex()}"


def verify_password(password: str, encoded: str) -> bool:
    if not isinstance(password, str) or len(password) > 1024 or not isinstance(encoded, str):
        return False
    try:
        algorithm, n, r, p, salt, expected = encoded.split("$")
        if (algorithm, n, r, p) != ("scrypt", str(_SCRYPT_N), "8", "1"):
            return False
        if len(salt) != 32 or len(expected) != 64:
            return False
        salt_bytes, expected_bytes = bytes.fromhex(salt), bytes.fromhex(expected)
        if len(salt_bytes) != 16 or len(expected_bytes) != 32:
            return False
        return hmac.compare_digest(_derive(password, salt_bytes), expected_bytes)
    except (ValueError, TypeError, UnicodeError):
        return False


class DevAccount(Contract):
    username: Identifier
    password_hash: str = Field(repr=False, exclude=True)
    role: Role
    scopes: tuple[Scope, ...]
    enabled: StrictBool = True

    @classmethod
    def create(cls, username: str, password: str, role: Role, scopes: Iterable[Scope]):
        return cls(username=username, password_hash=hash_password(password), role=role, scopes=tuple(scopes))

    @model_validator(mode="after")
    def unambiguous_grants(self):
        # Routes identify a pack by ID, so two grants with the same ID are unsafe.
        if len({scope.pack_id for scope in self.scopes}) != len(self.scopes):
            raise ValueError("pack IDs must be unique within an account's grants")
        return self


@dataclass(frozen=True)
class Principal:
    actor: Actor
    scopes: tuple[Scope, ...]
    csrf_token: str

    def scope_for(self, pack_id: str) -> Scope | None:
        return next((scope for scope in self.scopes if scope.pack_id == pack_id), None)


@dataclass(frozen=True)
class _Session:
    username: str
    csrf_token: str
    expires_at: float


class LocalAuth:
    def __init__(self, *, accounts: Iterable[DevAccount] = (), ttl_seconds: int = 3600,
                 clock: Callable[[], float] = time.monotonic, max_sessions: int = 1024, collection_grants=None):
        if type(ttl_seconds) is not int or ttl_seconds <= 0:
            raise ValueError("session TTL must be a positive integer")
        if type(max_sessions) is not int or max_sessions <= 0:
            raise ValueError("max_sessions must be a positive integer")
        account_list = [DevAccount.model_validate(account) for account in accounts]
        self._accounts = {account.username: account for account in account_list}
        if len(self._accounts) != len(account_list):
            raise ValueError("duplicate development account")
        self.ttl_seconds, self._clock, self._max_sessions = ttl_seconds, clock, max_sessions
        self._sessions: dict[str, _Session] = {}
        self._disabled: set[str] = set()
        self._lock = RLock()
        self._collection_grants = {name: frozenset(tuple(pair) for pair in pairs) for name,pairs in (collection_grants or {}).items()}
        self._dummy_hash = hash_password(secrets.token_urlsafe(32))

    @staticmethod
    def _key(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def _enabled(self, account: DevAccount | None) -> bool:
        return account is not None and account.enabled and account.username not in self._disabled

    def login(self, username: str, password: str) -> tuple[str, Principal] | None:
        with self._lock:
            account = self._accounts.get(username)
            encoded = account.password_hash if account else self._dummy_hash
        valid = verify_password(password, encoded)
        with self._lock:
            if not valid or not self._enabled(account):
                return None
            now = self._clock()
            self._sessions = {key: session for key, session in self._sessions.items() if session.expires_at > now}
            if len(self._sessions) >= self._max_sessions:
                self._sessions.pop(next(iter(self._sessions)))
            token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
            self._sessions[self._key(token)] = _Session(username, csrf, now + self.ttl_seconds)
            return token, Principal(Actor(actor_id=account.username, role=account.role), account.scopes, csrf)

    def resolve(self, token: str | None) -> Principal | None:
        if not isinstance(token, str) or not token.isascii() or len(token) != 43:
            return None
        with self._lock:
            key = self._key(token)
            session = self._sessions.get(key)
            if session is None:
                return None
            account = self._accounts.get(session.username)
            if session.expires_at <= self._clock() or not self._enabled(account):
                self._sessions.pop(key, None)
                return None
            return Principal(Actor(actor_id=account.username, role=account.role), account.scopes, session.csrf_token)

    def logout(self, token: str | None) -> None:
        if isinstance(token, str) and token.isascii() and len(token) == 43:
            with self._lock:
                self._sessions.pop(self._key(token), None)

    def disable(self, username: str) -> None:
        with self._lock:
            self._disabled.add(username)
            self._sessions = {key: session for key, session in self._sessions.items() if session.username != username}

    @staticmethod
    def check_csrf(principal: Principal, token: str | None) -> bool:
        return isinstance(token, str) and token.isascii() and hmac.compare_digest(principal.csrf_token, token)

    def require(self, actor_id: str, scope: Scope, action: str) -> None:
        """Resolve mutable server-owned identity/grants again at each boundary."""
        from .ports import DomainNotFound, DomainForbidden
        allowed = {
            "PREPARER": {"inspect", "download", "correct", "recompute", "publish", "invalidate", "upload"},
            "REVIEWER": {"inspect", "download", "review", "reject", "publish"},
        }
        with self._lock:
            account = self._accounts.get(actor_id)
            if not self._enabled(account) or scope not in account.scopes:
                raise DomainNotFound()
            if action not in allowed.get(account.role,set()):
                raise DomainForbidden()

    @contextmanager
    def authorized(self, actor_id: str, scope: Scope, action: str):
        """Serialize a business commit with server-owned grant revocation.

        Acquire this authority lock before a scoped database lock. The database
        transaction must exit before this guard so disable() cannot finish while
        a previously authorized publication is still committing.
        """
        with self._lock:
            self.require(actor_id,scope,action)
            yield


    def collection_funds(self, actor_id):
        with self.collection_authorized(actor_id, action='inspect') as grants:
            return [{'tenant_id':tenant,'fund_id':fund} for tenant,fund in sorted(grants)]

    @contextmanager
    def collection_authorized(self, actor_id, *, action):
        """Explicit server-owned fund grants, separate from legacy pack grants."""
        from .ports import DomainForbidden
        with self._lock:
            account=self._accounts.get(actor_id)
            allowed={'PREPARER':{'inspect','prepare','download'},'REVIEWER':{'inspect','review','download'},'FUND_MANAGER':{'inspect','download'},'INVESTOR':{'inspect','download'}}
            if not self._enabled(account) or action not in allowed.get(account.role,set()):
                raise DomainForbidden()
            yield self._collection_grants.get(actor_id,frozenset())

    def collection_actor(self, actor_id):
        from .ports import DomainForbidden
        with self._lock:
            account=self._accounts.get(actor_id)
            if not self._enabled(account): raise DomainForbidden()
            return {'actor_id':actor_id,'role':account.role}

    def collection_participants(self, tenant_id, fund_id):
        with self._lock:
            return [{'actor_id':name,'role':a.role} for name,a in self._accounts.items()
                    if self._enabled(a) and (tenant_id,fund_id) in self._collection_grants.get(name,())]
