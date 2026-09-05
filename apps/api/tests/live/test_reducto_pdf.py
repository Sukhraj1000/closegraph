"""Actual synthetic PDF evidence from a credential-isolated trusted transport.

The coordinator performs /upload and /parse with the secret outside worker
sandboxes, then transfers exact source/response bytes and its execution receipt.
A missing receipt is a SKIP and does not complete live-provider acceptance.
"""
import json
import os
from hashlib import sha256
from pathlib import Path

import pytest

from closegraph.contracts import Scope
from closegraph.extractors.reducto import ENDPOINT, decode_response


def synthetic_pdf() -> bytes:
    """One-page, deterministic, explicitly synthetic test document."""
    stream = b"BT /F1 14 Tf 50 740 Td (SYNTHETIC CLOSEGRAPH REPORT) Tj 0 -30 Td (Fund SYNTHETIC-001) Tj 0 -30 Td (NAV GBP 1000.00) Tj 0 -30 Td (Reporting period 2026-Q2) Tj ET"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    raw, offsets = bytearray(b"%PDF-1.4\n"), [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(raw))
        raw.extend(str(index).encode() + b" 0 obj\n" + obj + b"\nendobj\n")
    xref = len(raw)
    raw.extend(b"xref\n0 6\n0000000000 65535 f \n")
    for offset in offsets[1:]:
        raw.extend(f"{offset:010d} 00000 n \n".encode())
    raw.extend(b"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n" + str(xref).encode() + b"\n%%EOF\n")
    return bytes(raw)


def test_authorized_live_synthetic_pdf_is_source_linked():
    receipt_path = os.environ.get("CLOSEGRAPH_REDUCTO_LIVE_RECEIPT")
    if not receipt_path:
        pytest.skip("No actual trusted Reducto transport receipt; live acceptance remains incomplete")
    receipt = json.loads(Path(receipt_path).read_text())
    assert receipt["mode"] == "LIVE"
    assert receipt["transport"] == "trusted-coordinator"
    assert receipt["endpoint"] == ENDPOINT
    assert receipt["authorization_reference"]
    assert receipt["data_handling_note"]
    assert receipt["executed_at"]
    source = Path(receipt["source_path"]).read_bytes()
    raw_response = Path(receipt["parse_response_path"]).read_bytes()
    assert source == synthetic_pdf(), "Live test permits only this deterministic synthetic PDF"
    assert receipt["source_sha256"] == sha256(source).hexdigest()
    assert receipt["response_sha256"] == sha256(raw_response).hexdigest()
    assert receipt["request_settings"] == {"persist_results": False, "force_url_result": False}
    result = decode_response(raw_response, scope=Scope(tenant_id="synthetic-tenant",
        fund_id="synthetic-fund", pack_id="synthetic-pack"), document_version_id="live-synthetic-v1",
        source_sha256=receipt["source_sha256"], settings=receipt["request_settings"], mode="LIVE")
    assert result.available, result.diagnostics
    assert result.response_id == receipt["job_id"]
    values = " ".join(item.raw_content for item in result.occurrences)
    assert "SYNTHETIC" in values.upper()
    assert "1000" in values.replace(",", "")
    assert any(item.source.locator.original_page == 1 for item in result.occurrences)
    assert all(item.source.content_hash == sha256(source).hexdigest() for item in result.occurrences)
    assert all(item.mode == "LIVE" and item.response_content_hash == sha256(raw_response).hexdigest()
               for item in result.observations)
