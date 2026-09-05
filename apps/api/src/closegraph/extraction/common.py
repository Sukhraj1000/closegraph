"""Native observations are evidence, not financial checks or approval."""
from dataclasses import dataclass
from hashlib import sha256
import json
import re
from typing import Any, TypedDict


class ExtractionError(ValueError):
    """Fail-closed error with a stable machine-readable code."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class ExtractionLimits:
    max_bytes: int = 10_000_000
    max_rows: int = 50_000
    max_columns: int = 256
    max_cells: int = 200_000
    max_field_chars: int = 100_000
    max_zip_members: int = 512
    max_uncompressed_bytes: int = 50_000_000
    max_compression_ratio: int = 200

    def __post_init__(self):
        if any(type(value) is not int or value <= 0 for value in vars(self).values()):
            raise ValueError("limits must be positive integers")


class SourceRef(TypedDict):
    document_version_id: str
    content_hash: str
    locator: dict[str, Any]


class Observation(TypedDict, total=False):
    occurrence_id: str
    source: SourceRef
    raw_value: str | None
    raw_record: str
    raw_values: dict[str, str]
    raw_scale: str | None
    metric: str
    entity_id: str | None
    currency: str | None
    period: str | None
    interpretation_status: str
    formula: str | None
    cached_value: str | None
    cache_status: str


def checked_source(data: bytes, document_version_id: str, content_hash: str | None,
                   limits: ExtractionLimits) -> str:
    if not isinstance(data, bytes):
        raise ExtractionError("bytes_required")
    if not isinstance(document_version_id, str) or not document_version_id.strip():
        raise ExtractionError("document_version_required")
    if len(data) > limits.max_bytes:
        raise ExtractionError("byte_limit")
    digest = sha256(data).hexdigest()
    if content_hash is not None:
        if not isinstance(content_hash, str) or re.fullmatch(r"[0-9a-f]{64}", content_hash) is None:
            raise ExtractionError("invalid_content_hash")
        if content_hash != digest:
            raise ExtractionError("hash_mismatch")
    return digest


def occurrence_id(version: str, digest: str, locator: dict) -> str:
    return sha256(json.dumps([version, digest, locator], sort_keys=True,
                             separators=(",", ":")).encode()).hexdigest()


def native_result(data: bytes, version: str, digest: str, observations: list,
                  dispositions: list) -> dict:
    return {"source_bytes": data, "document_version_id": version,
            "content_hash": digest, "observations": observations,
            "dispositions": dispositions, "execution_status": "COMPLETED",
            "parser_confidence": {"status": "NOT_APPLICABLE", "value": None},
            "parser_agreement": {"status": "NOT_RUN"}, "checks": []}


def valid_source(source: object) -> bool:
    if not isinstance(source, dict):
        return False
    version, digest, loc = (source.get(k) for k in ("document_version_id", "content_hash", "locator"))
    if not isinstance(version, str) or not version.strip() or not isinstance(digest, str):
        return False
    if re.fullmatch(r"[0-9a-f]{64}", digest) is None or not isinstance(loc, dict):
        return False
    if loc.get("kind") == "csv":
        return type(loc.get("row")) is int and loc["row"] >= 2
    if loc.get("kind") == "xlsx":
        return isinstance(loc.get("sheet"), str) and bool(loc["sheet"].strip()) and valid_cell(loc.get("cell"))
    return False  # Native-only boundary; PDF evidence is not implemented.


def valid_cell(cell: object) -> bool:
    if not isinstance(cell, str) or re.fullmatch(r"[A-Z]{1,3}[1-9][0-9]{0,6}", cell) is None:
        return False
    from openpyxl.utils.cell import coordinate_from_string, column_index_from_string
    column, row = coordinate_from_string(cell)
    return column_index_from_string(column) <= 16384 and row <= 1048576
