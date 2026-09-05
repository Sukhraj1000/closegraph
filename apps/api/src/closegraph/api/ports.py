"""Synchronous integration boundary; HTTP never computes financial validity.

Implement all methods on one facade. Scope and actor originate from LocalAuth,
never from request JSON. Each mutation must atomically compare expected_version,
validate evidence/check freshness and enforce independent exact-snapshot review.
Download must authorize the artifact within scope and verify immutable bytes.
"""
from dataclasses import dataclass
from typing import Literal, Protocol

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
    ConfigurationChangeRequest,
)

Role = Literal["PREPARER", "REVIEWER", "FUND_MANAGER", "INVESTOR"]


class Actor(Contract):
    actor_id: Identifier
    role: Role


class DomainNotFound(Exception):
    """Absent or inaccessible resource; HTTP always uses a generic 404."""


class DomainConflict(Exception):
    """Stale version or failed lifecycle gate; message must be safe for the caller."""


class DomainForbidden(Exception):
    """Domain-level permission/independent-review violation."""


class DomainUnavailable(Exception):
    """Required service/provider is unavailable, never a passing fallback."""


@dataclass(frozen=True)
class ArtifactDownload:
    content: bytes
    filename: str
    media_type: str = "application/octet-stream"


class PackServices(Protocol):
    def invalidate(self, scope: Scope, actor: Actor, command: ConfigurationChangeRequest) -> PackSnapshot: ...
    def record_review_event(self, scope: Scope, actor: Actor, command: ReviewEventRequest) -> dict: ...
    def review_work(self, scope: Scope, actor: Actor) -> dict: ...
    def get_pack(self, scope: Scope, actor: Actor) -> PackSnapshot: ...
    def upload(self, scope: Scope, actor: Actor, command: UploadRequest) -> PackSnapshot: ...
    def resolve(self, scope: Scope, actor: Actor, command: ResolutionRequest) -> PackSnapshot: ...
    def reject(self, scope: Scope, actor: Actor, command: RejectRequest) -> PackSnapshot: ...
    def get_history(self, scope: Scope, actor: Actor, version: int) -> PackSnapshot: ...
    def document(self, scope: Scope, actor: Actor, document_version_id: str) -> dict: ...
    def download_document(self, scope: Scope, actor: Actor, document_version_id: str) -> ArtifactDownload: ...
    def evidence(self, scope: Scope, actor: Actor, source_id: str) -> dict: ...
    def download_evidence(self, scope: Scope, actor: Actor, source_id: str) -> ArtifactDownload: ...
    def correct(self, scope: Scope, actor: Actor, command: CorrectionRequest) -> PackSnapshot: ...
    def recompute(self, scope: Scope, actor: Actor, command: VersionAction) -> PackSnapshot: ...
    def review(self, scope: Scope, actor: Actor, command: ReviewRequest) -> PackSnapshot: ...
    def publish(self, scope: Scope, actor: Actor, command: VersionAction) -> PackSnapshot: ...
    def download(self, scope: Scope, actor: Actor, artifact_id: str, *, publication_id: str | None = None) -> ArtifactDownload: ...
