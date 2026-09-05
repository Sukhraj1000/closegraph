"""Explicit PDF evidence provenance, with disabled and exact captured replay modes.

This stage exposes raw parser observations and original-page citations. It does
not invent financial mappings from provider prose or treat confidence as a check.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Protocol

from closegraph.contracts import Scope
from closegraph.extractors.reducto import (
    ENDPOINT,
    MAX_PDF_BYTES,
    MAX_RESPONSE_BYTES,
    ReductoResult,
    decode_response,
)


class LivePdfProvider(Protocol):
    """Injected by a trusted coordinator; the application never loads its key."""

    def parse_pdf(self, source: bytes, *, scope: Scope,
                  document_version_id: str) -> ReductoResult: ...


@dataclass(frozen=True)
class CapturedReplay:
    source_sha256: str
    response: bytes
    receipt: dict
    receipt_sha256: str

    @classmethod
    def from_directory(cls, directory: Path) -> CapturedReplay:
        directory = Path(directory)
        files = [directory / name for name in ("receipt.json", "parse-response.json", "synthetic.pdf")]
        if any(path.is_symlink() or not path.is_file() for path in files):
            raise ValueError("Captured replay requires three regular capture files")
        if any(path.stat().st_size > limit for path, limit in zip(files, (100_000, MAX_RESPONSE_BYTES, MAX_PDF_BYTES))):
            raise ValueError("Captured replay exceeds bounded evidence size")
        receipt_raw = files[0].read_bytes()
        response = files[1].read_bytes()
        source = files[2].read_bytes()
        if len(receipt_raw) > 100_000 or len(response) > MAX_RESPONSE_BYTES or len(source) > MAX_PDF_BYTES:
            raise ValueError("Captured replay exceeds bounded evidence size")
        receipt = json.loads(receipt_raw)
        if not isinstance(receipt, dict) or (
            receipt.get("mode") != "LIVE"
            or receipt.get("transport") != "trusted-coordinator"
            or receipt.get("endpoint") != ENDPOINT
            or receipt.get("source_sha256") != sha256(source).hexdigest()
            or receipt.get("response_sha256") != sha256(response).hexdigest()
            or not receipt.get("authorization_reference")
            or not receipt.get("data_handling_note")
            or not receipt.get("executed_at")
            or not source.startswith(b"%PDF-")
        ):
            raise ValueError("Captured replay receipt or exact content hashes do not match")
        decoded = json.loads(response)
        if not isinstance(decoded, dict) or decoded.get("job_id") != receipt.get("job_id"):
            raise ValueError("Captured replay job identity mismatch")
        return cls(sha256(source).hexdigest(), response, receipt, sha256(receipt_raw).hexdigest())


class PdfEvidenceService:
    def __init__(self, *, mode="DISABLED", capture: CapturedReplay | None = None,
                 live_provider: LivePdfProvider | None = None):
        if mode not in ("DISABLED", "CAPTURED_REPLAY", "LIVE"):
            raise ValueError("PDF mode must be explicitly DISABLED, CAPTURED_REPLAY or LIVE")
        if mode == "CAPTURED_REPLAY" and capture is None:
            raise ValueError("Captured replay mode requires a verified capture")
        self.mode, self.capture, self.live_provider = mode, capture, live_provider

    def parse(self, source: bytes, *, scope: Scope, document_version_id: str):
        digest = sha256(source).hexdigest()
        def unavailable(reason):
            return ReductoResult("UNAVAILABLE", digest, diagnostics=(reason,),
                                 mode="LIVE" if self.mode == "LIVE" else "REPLAY")

        if self.mode == "DISABLED":
            return unavailable("provider_disabled")
        if not source.startswith(b"%PDF-") or len(source) > MAX_PDF_BYTES:
            return unavailable("unsupported_pdf_signature_or_size")
        if self.mode == "CAPTURED_REPLAY":
            if digest != self.capture.source_sha256:
                return unavailable("captured_replay_source_hash_mismatch")
            return decode_response(
                self.capture.response, scope=scope, document_version_id=document_version_id,
                source_sha256=digest, settings=self.capture.receipt.get("request_settings", {}), mode="REPLAY")
        if self.live_provider is None:
            return unavailable("live_transport_unavailable")
        result = self.live_provider.parse_pdf(source, scope=scope, document_version_id=document_version_id)
        if result.mode != "LIVE" or result.source_hash != digest:
            return unavailable("live_transport_provenance_mismatch")
        if result.raw_response is not None and sha256(result.raw_response).hexdigest() != result.response_hash:
            return unavailable("live_response_hash_mismatch")
        if any(item.scope != scope or item.source.document_version_id != document_version_id
               or item.source.content_hash != digest for item in result.occurrences):
            return unavailable("live_source_scope_mismatch")
        if any(item.scope != scope for item in result.observations):
            return unavailable("live_observation_scope_mismatch")
        occurrence_ids = {item.occurrence_id for item in result.occurrences}
        observed_ids = [item.occurrence_id for item in result.observations]
        if (len(occurrence_ids) != len(result.occurrences) or len(set(observed_ids)) != len(observed_ids)
                or occurrence_ids != set(observed_ids)):
            return unavailable("live_occurrence_accounting_mismatch")
        if result.available and (not result.raw_response or not result.response_id or not occurrence_ids):
            return unavailable("live_response_provenance_incomplete")
        return result

    def extract(self, receipt, source, *, scope, blobs):
        if sha256(source).hexdigest() != receipt["content_hash"]:
            raise ValueError("PDF receipt source hash mismatch")
        result = self.parse(source, scope=scope, document_version_id=receipt["document_version_id"])
        diagnostics = list(result.diagnostics)
        # Raw provider responses are durable exact bytes in the same scoped blob store.
        if result.raw_response is not None:
            stored = blobs.put(result.raw_response)
            if stored != result.response_hash:
                raise ValueError("Provider response content-address mismatch")
        provenance = {
            "provider_mode": self.mode,
            "provider_status": "DISABLED" if self.mode == "DISABLED" else result.availability,
            "parser": "reducto", "response_id": result.response_id,
            "response_content_hash": result.response_hash,
            "diagnostics": diagnostics,
        }
        if self.capture is not None and self.mode == "CAPTURED_REPLAY":
            provenance["capture"] = {
                "receipt_sha256": self.capture.receipt_sha256,
                "original_mode": "LIVE",
                "executed_at": self.capture.receipt["executed_at"],
                "endpoint": self.capture.receipt["endpoint"],
                "data_handling_note": self.capture.receipt["data_handling_note"],
            }
        root = {**receipt, **provenance, "source_version": receipt["version"], "fact_ids": [],
                "authority_status": "UNRESOLVED", "preview_rows": []}
        evidence = {"reporting-evidence": root}
        occurrences = [item.model_dump(mode="json") for item in result.occurrences]
        observations = [item.model_dump(mode="json") for item in result.observations]
        by_occurrence = {item.occurrence_id: item for item in result.observations}
        facts, versions = [], {"reporting-evidence": receipt["version"]}
        for occurrence in result.occurrences:
            source_id = "reporting-evidence:" + occurrence.occurrence_id
            fact_id = "pdf:" + occurrence.occurrence_id
            observation = by_occurrence[occurrence.occurrence_id]
            reference = occurrence.source.model_dump(mode="json")
            facts.append({
                "fact_id": fact_id, "fact_version": 1, "occurrence_id": occurrence.occurrence_id,
                "metric": "reporting_evidence", "raw_value": occurrence.raw_content,
                "value_decimal": None, "currency": None, "period": None, "entity_id": None,
                "raw_scale": None, "value_state": "AMBIGUOUS", "interpretation_status": "UNRESOLVED",
                "source": {**reference, "source_id": source_id},
                "observation_ids": [observation.observation_id],
            })
            evidence[source_id] = {
                **root, "locator": reference["locator"], "fact_ids": [fact_id],
                "preview_rows": [{"label": "Observed PDF text", "value": occurrence.raw_content}],
            }
            versions[source_id] = receipt["version"]
        if occurrences:
            diagnostics.append("PDF reporting evidence has no approved financial interpretation mapping")
        elif result.available:
            diagnostics.append("PDF reporting evidence returned no source occurrences")
        report = {**provenance, "diagnostics": diagnostics, "source_hash": result.source_hash,
                  "occurrence_count": len(occurrences), "unresolved_count": len(occurrences),
                  "financial_mapping": "UNAVAILABLE", "parser_agreement": "NOT_RUN"}
        return {"facts": facts, "evidence": evidence, "source_versions": versions,
                "source_occurrences": occurrences, "extraction_observations": observations,
                "report": report}


def provider_from_environment(environment) -> PdfEvidenceService:
    """Read only non-secret configuration; no implicit network or replay fallback."""
    mode = environment.get("CLOSEGRAPH_PDF_MODE", "DISABLED")
    if mode == "CAPTURED_REPLAY":
        directory = environment.get("CLOSEGRAPH_PDF_CAPTURE_DIR")
        if not directory:
            raise ValueError("CAPTURED_REPLAY requires CLOSEGRAPH_PDF_CAPTURE_DIR")
        return PdfEvidenceService(mode=mode, capture=CapturedReplay.from_directory(Path(directory)))
    return PdfEvidenceService(mode=mode)
