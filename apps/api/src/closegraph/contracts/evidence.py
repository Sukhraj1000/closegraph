from math import isfinite
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, StrictBool, model_validator

from .types import ContentHash, Contract, ExactDecimal, Identifier, Scope, Version


class CsvLocator(Contract):
    kind: Literal["csv"] = "csv"
    row: Annotated[int, Field(strict=True, ge=1)]
    column: Identifier
    byte_offset: Annotated[int, Field(strict=True, ge=0)] | None = None


class XlsxLocator(Contract):
    kind: Literal["xlsx"] = "xlsx"
    sheet: Identifier
    cell: Annotated[str, Field(pattern=r"^[A-Z]{1,3}[1-9][0-9]{0,6}$")]
    formula: str | None = None
    cached_value: str | None = None
    cache_status: Literal["NOT_APPLICABLE", "UNKNOWN", "STALE", "CURRENT"] = "UNKNOWN"


class PdfLocator(Contract):
    kind: Literal["pdf"] = "pdf"
    original_page: Annotated[int, Field(strict=True, ge=1)]
    processed_page: Annotated[int, Field(strict=True, ge=1)] | None = None
    coordinate_system: Literal["normalised-0-1", "points-top-left", "points-bottom-left"]
    bbox: tuple[float, float, float, float]

    @model_validator(mode="after")
    def valid_box(self):
        x1,y1,x2,y2 = self.bbox
        if not all(isfinite(v) and v >= 0 for v in self.bbox) or x1 >= x2 or y1 >= y2:
            raise ValueError("bounding box must have finite ordered coordinates")
        if self.coordinate_system == "normalised-0-1" and max(self.bbox) > 1:
            raise ValueError("normalised coordinates must be within 0..1")
        return self


Locator = Annotated[CsvLocator | XlsxLocator | PdfLocator, Field(discriminator="kind")]


class SourceRef(Contract):
    document_version_id: Identifier
    content_hash: ContentHash
    locator: Locator
    context_evidence_ids: tuple[Identifier, ...] = ()


class DocumentVersion(Contract):
    scope: Scope
    document_version_id: Identifier
    source_id: Identifier
    version: Version
    storage_key: ContentHash
    content_hash: ContentHash
    byte_size: Annotated[int, Field(strict=True, ge=0)]
    filename: Identifier
    media_type: Identifier
    idempotency_key: Identifier
    receipt_actor_id: Identifier
    received_at: AwareDatetime
    observed_at: AwareDatetime
    authority_status: Literal["UNRESOLVED", "AUTHORITATIVE", "SUPERSEDED"] = "UNRESOLVED"
    coverage_status: Literal["UNKNOWN", "COMPLETE", "INCOMPLETE"] = "UNKNOWN"

    @model_validator(mode="after")
    def hash_matches(self):
        if self.storage_key != self.content_hash:
            raise ValueError("content-addressed storage key must match content hash")
        return self


class SourceOccurrence(Contract):
    scope: Scope
    occurrence_id: Identifier
    source: SourceRef
    raw_content: str
    disposition: Literal["ACCEPTED", "REJECTED", "EXCLUDED", "UNRESOLVED"]
    reason: str | None = None

    @model_validator(mode="after")
    def rejected_reason(self):
        if self.disposition in {"REJECTED", "EXCLUDED"} and not (self.reason and self.reason.strip()):
            raise ValueError("rejected/excluded records require a reason")
        return self


class Confidence(Contract):
    status: Literal["AVAILABLE", "NOT_APPLICABLE", "UNAVAILABLE", "NOT_RUN"]
    value: ExactDecimal | None = None
    kind: Identifier | None = None
    provenance: str | None = None
    reason: str | None = None
    calibrated: StrictBool = False

    @model_validator(mode="after")
    def honest_availability(self):
        if self.status == "AVAILABLE":
            if self.value is None or not self.kind or not self.provenance:
                raise ValueError("available confidence requires actual value, kind and provenance")
        elif self.value is not None or self.calibrated or not (self.reason and self.reason.strip()):
            raise ValueError("absent confidence has no value/calibration and requires a reason")
        return self


class ObservationCandidate(Contract):
    metric: Identifier | None = None
    value_decimal: ExactDecimal | None = None
    entity_id: Identifier | None = None
    period: Identifier | None = None
    currency: Annotated[str, Field(pattern=r"^[A-Z]{3}$")] | None = None
    raw_value: str | None = None
    raw_scale: str | None = None


class ExtractionObservation(Contract):
    scope: Scope
    observation_id: Identifier
    occurrence_id: Identifier
    parser: Identifier
    parser_version: Identifier
    settings: dict
    response_id: Identifier
    response_content_hash: ContentHash | None = None
    mode: Literal["NATIVE", "LIVE", "REPLAY", "SYNTHETIC"]
    confidence: Confidence
    candidate: ObservationCandidate
