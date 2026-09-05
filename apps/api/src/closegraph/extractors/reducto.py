"""Bounded configured-only Reducto adapter producing canonical evidence.

Sources: https://docs.reducto.ai/quickstart
https://docs.reducto.ai/parse/response-format
https://docs.reducto.ai/security/policies
https://docs.reducto.ai/security/eu-data-residency
Provider confidence is an uncalibrated observation, never a trusted financial check.
"""
from __future__ import annotations

import json
import math
import re
import uuid
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from typing import Any, Literal
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from closegraph.contracts import (
    Confidence,
    ExtractionObservation,
    ObservationCandidate,
    PdfLocator,
    Scope,
    SourceOccurrence,
    SourceRef,
)

ENDPOINT = "https://platform.reducto.ai"
ADAPTER_VERSION = "adapter-v1-provider-unreported"
MAX_PDF_BYTES = 10_000_000
MAX_RESPONSE_BYTES = 12_000_000
MAX_BLOCKS = 20_000
MAX_CONTENT_CHARS = 200_000


@dataclass(frozen=True)
class ReductoConfig:
    enabled: bool = False
    api_key: str | None = field(default=None, repr=False)
    authorized_source_hashes: frozenset[str] = frozenset()
    authorization_reference: str | None = None
    data_handling_note: str | None = None
    region_note: str = "Standard provider endpoint; processing region not independently established"
    timeout_seconds: float = 120.0

    def unavailable_reason(self, digest: str) -> str | None:
        if not self.enabled:
            return "provider_disabled"
        if not self.api_key or not self.api_key.strip():
            return "provider_credentials_unavailable"
        if digest not in self.authorized_source_hashes:
            return "source_not_authorized_for_external_processing"
        if not self.authorization_reference or not self.data_handling_note:
            return "external_data_scope_or_handling_record_missing"
        if not math.isfinite(self.timeout_seconds) or not 0 < self.timeout_seconds <= 600:
            return "invalid_provider_timeout"
        return None


@dataclass(frozen=True)
class ReductoResult:
    availability: Literal["AVAILABLE", "UNAVAILABLE"]
    source_hash: str
    occurrences: tuple[SourceOccurrence, ...] = ()
    observations: tuple[ExtractionObservation, ...] = ()
    diagnostics: tuple[str, ...] = ()
    raw_response: bytes | None = field(default=None, repr=False)
    response_hash: str | None = None
    response_id: str | None = None
    upload_response: bytes | None = field(default=None, repr=False)
    request_settings: dict[str, Any] = field(default_factory=dict)
    mode: Literal["LIVE", "REPLAY", "SYNTHETIC"] = "REPLAY"

    @property
    def available(self) -> bool:
        return self.availability == "AVAILABLE"


class ProviderFailure(RuntimeError):
    pass


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ProviderFailure("provider_redirect_refused")


class ReductoTransport:
    """Only the two fixed official endpoints; no arbitrary URLs or redirect following."""
    def __init__(self):
        self.opener = build_opener(ProxyHandler({}), _NoRedirect())

    def _request(self, path: str, body: bytes, content_type: str,
                 api_key: str, timeout: float) -> bytes:
        if path not in ("/upload", "/parse"):
            raise ProviderFailure("unsupported_provider_endpoint")
        request = Request(ENDPOINT + path, data=body, method="POST",
                          headers={"Authorization": "Bearer " + api_key,
                                   "Content-Type": content_type})
        try:
            with self.opener.open(request, timeout=timeout) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
        except HTTPError as exc:
            # Do not include provider bodies, presigned links, keys or request headers in errors.
            raise ProviderFailure("provider_http_" + str(exc.code)) from None
        except (URLError, TimeoutError, OSError):
            raise ProviderFailure("provider_transport_unavailable") from None
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ProviderFailure("provider_response_limit")
        return raw

    def upload(self, source: bytes, api_key: str, timeout: float) -> bytes:
        boundary = "closegraph-" + uuid.uuid4().hex
        body = (("--" + boundary + '\r\nContent-Disposition: form-data; name="file"; '
                 'filename="synthetic-or-authorized.pdf"\r\nContent-Type: application/pdf\r\n\r\n').encode()
                + source + ("\r\n--" + boundary + "--\r\n").encode())
        return self._request("/upload", body, "multipart/form-data; boundary=" + boundary,
                             api_key, timeout)

    def parse(self, file_id: str, settings: dict, api_key: str, timeout: float) -> bytes:
        body = json.dumps({"input": file_id, "settings": settings}).encode()
        return self._request("/parse", body, "application/json", api_key, timeout)


def _unavailable(source_hash: str, reason: str, *, raw: bytes | None = None,
                 upload: bytes | None = None, settings: dict | None = None,
                 mode: Literal["LIVE", "REPLAY", "SYNTHETIC"] = "REPLAY") -> ReductoResult:
    return ReductoResult("UNAVAILABLE", source_hash, diagnostics=(reason,),
                        raw_response=raw, response_hash=sha256(raw).hexdigest() if raw else None,
                        upload_response=upload, request_settings=settings or {}, mode=mode)


def _confidence(block: dict, response_hash: str) -> Confidence:
    granular = block.get("granular_confidence")
    value = granular.get("parse_confidence") if isinstance(granular, dict) else None
    if value is None:
        return Confidence(status="UNAVAILABLE",
                          reason="No numeric parse confidence returned; categorical value preserved verbatim")
    try:
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            raise TypeError("invalid type")
        numeric = Decimal(str(value))
        if not numeric.is_finite() or not 0 <= numeric <= 1:
            raise ValueError("invalid score")
    except (ValueError, TypeError, InvalidOperation):
        return Confidence(status="UNAVAILABLE", reason="Malformed numeric provider confidence retained in raw response")
    return Confidence(status="AVAILABLE", value=str(numeric), kind="reducto.parse_confidence",
                      provenance=response_hash, calibrated=False)


def decode_response(raw_response: bytes, *, scope: Scope, document_version_id: str,
                    source_sha256: str, settings: dict | None = None,
                    mode: Literal["LIVE", "REPLAY", "SYNTHETIC"] = "REPLAY") -> ReductoResult:
    """Decode actual or explicitly labelled fixture bytes without network access.

    Blocks preserve untrusted raw text. No financial metric/context/value is inferred
    from prose. A supported subsequent mapping/normalizer must establish those fields.
    """
    settings = dict(settings or {})
    if mode not in ("LIVE", "REPLAY", "SYNTHETIC"):
        raise ValueError("Explicit live/replay/synthetic provenance required")
    if not isinstance(raw_response, bytes):
        raise TypeError("Provider response must be exact bytes")
    if not re.fullmatch(r"[0-9a-f]{64}", source_sha256):
        raise ValueError("Source SHA-256 required")
    if len(raw_response) > MAX_RESPONSE_BYTES:
        return _unavailable(source_sha256, "provider_response_limit", mode=mode)
    digest = sha256(raw_response).hexdigest()
    try:
        response = json.loads(raw_response)
        if not isinstance(response, dict):
            raise TypeError("object expected")
        response_id = response["job_id"]
        if not isinstance(response_id, str) or not response_id.strip():
            raise ValueError("job_id expected")
        result = response["result"]
        if result.get("type") != "full":
            return _unavailable(source_sha256, "external_result_url_unsupported_no_automatic_fetch",
                                raw=raw_response, settings=settings, mode=mode)
        chunks = result["chunks"]
        if not isinstance(chunks, list) or any(not isinstance(chunk, dict) or
            not isinstance(chunk.get("blocks"), list) for chunk in chunks):
            raise ValueError("invalid chunks")
        blocks = [block for chunk in chunks for block in chunk["blocks"]]
        if not blocks or len(blocks) > MAX_BLOCKS:
            raise ValueError("missing blocks or block limit")
    except (ValueError, KeyError, TypeError, AttributeError):
        return _unavailable(source_sha256, "malformed_provider_response", raw=raw_response,
                            settings=settings, mode=mode)
    occurrences, observations, diagnostics = [], [], []
    for index, block in enumerate(blocks):
        try:
            if not isinstance(block, dict):
                raise TypeError("invalid block")
            raw_content = block["content"]
            if not isinstance(raw_content, str) or len(raw_content) > MAX_CONTENT_CHARS:
                raise ValueError("invalid content")
            box = block["bbox"]
            coordinates = [box[name] for name in ("left", "top", "width", "height")]
            if any(isinstance(n, bool) or not isinstance(n, (int, float)) for n in coordinates):
                raise ValueError("invalid coordinates")
            left, top, width, height = coordinates
            locator = PdfLocator(original_page=box["original_page"], processed_page=box["page"],
                                 coordinate_system="normalised-0-1",
                                 bbox=(left, top, left + width, top + height))
            source = SourceRef(document_version_id=document_version_id,
                               content_hash=source_sha256, locator=locator)
            occurrence_id = sha256(json.dumps([document_version_id, source_sha256,
                locator.model_dump(mode="json"), index], sort_keys=True).encode()).hexdigest()
            occurrence = SourceOccurrence(scope=scope, occurrence_id=occurrence_id, source=source,
                                          raw_content=raw_content, disposition="UNRESOLVED")
            observation_id = sha256((occurrence_id + digest + str(index)).encode()).hexdigest()
            observation = ExtractionObservation(
                scope=scope, observation_id=observation_id, occurrence_id=occurrence_id,
                parser="reducto", parser_version=ADAPTER_VERSION,
                settings={"request": settings, "provider_block_type": block.get("type"),
                          "provider_confidence": block.get("confidence"),
                          "provider_granular_confidence": block.get("granular_confidence"),
                          "provider_model_version": response.get("model_version"),
                          "block_index": index},
                response_id=response_id, response_content_hash=digest, mode=mode,
                confidence=_confidence(block, digest),
                candidate=ObservationCandidate(raw_value=raw_content))
            occurrences.append(occurrence)
            observations.append(observation)
        except (ValueError, KeyError, TypeError, AttributeError, OverflowError):
            diagnostics.append("block_" + str(index) + "_malformed_citation_or_content")
    return ReductoResult("UNAVAILABLE" if diagnostics else "AVAILABLE", source_sha256,
        tuple(occurrences), tuple(observations), tuple(diagnostics), raw_response, digest,
        response_id, request_settings=settings, mode=mode)


class ReductoAdapter:
    def __init__(self, config: ReductoConfig, transport: ReductoTransport | None = None):
        self.config, self.transport = config, transport or ReductoTransport()

    def parse_pdf(self, source: bytes, *, scope: Scope,
                  document_version_id: str) -> ReductoResult:
        if not isinstance(source, bytes):
            raise TypeError("Source bytes required")
        digest = sha256(source).hexdigest()
        reason = self.config.unavailable_reason(digest)
        if reason:
            return _unavailable(digest, reason)
        if not source.startswith(b"%PDF-") or len(source) > MAX_PDF_BYTES:
            return _unavailable(digest, "unsupported_pdf_signature_or_size")
        settings = {"persist_results": False, "force_url_result": False}
        upload = None
        try:
            upload = self.transport.upload(source, self.config.api_key, self.config.timeout_seconds)
            uploaded = json.loads(upload)
            file_id = uploaded["file_id"]
            if not isinstance(file_id, str) or not file_id.startswith("reducto://") or len(file_id) > 2048:
                raise ProviderFailure("malformed_upload_reference")
            raw = self.transport.parse(file_id, settings, self.config.api_key, self.config.timeout_seconds)
        except ProviderFailure as exc:
            return _unavailable(digest, str(exc), upload=upload, settings=settings, mode="LIVE")
        except (ValueError, TypeError, KeyError):
            return _unavailable(digest, "malformed_upload_response", upload=upload,
                                settings=settings, mode="LIVE")
        decoded = decode_response(raw, scope=scope, document_version_id=document_version_id,
                                  source_sha256=digest, settings=settings, mode="LIVE")
        return ReductoResult(**{**vars(decoded), "upload_response": upload})
