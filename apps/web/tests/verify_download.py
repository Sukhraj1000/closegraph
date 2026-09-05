"""Verify browser-downloaded bytes independently with Python's standard library."""
import hashlib
import json
from decimal import Decimal
from pathlib import Path
import sys
import xml.etree.ElementTree as ET
import zipfile

workbook_path, manifest_path, fixture_dir, reviewer = sys.argv[1:]
fixture = Path(fixture_dir)
expected = json.loads((fixture / "expected.json").read_text())
manifest = json.loads(Path(manifest_path).read_text())
artifact = Path(workbook_path).read_bytes()
assert manifest["artifact_sha256"] == hashlib.sha256(artifact).hexdigest(), "Manifest does not bind downloaded workbook"
assert manifest["review"]["actor"] == reviewer, "Independent reviewer identity mismatch"
assert manifest["snapshot_version"] == manifest["review"]["snapshot_version"], "Approval is bound to another snapshot"
assert all(check["status"] == "PASS" or (check["status"] == "NOT_APPLICABLE" and check.get("applicable") is False and str(check.get("justification", "")).strip()) for check in manifest["checks"] if check["required"]), "Required check failed"
source_rows = manifest["sources"]
assert len({source["source_id"] for source in source_rows}) == len(source_rows), "Manifest source anchor IDs are not unique"
sources = {source["source_id"]: source for source in source_rows}
for role, filename in [("capital", "capital.csv"), ("fee-rule", "fee-rule.csv"), ("original", "original.xlsx")]:
    matches = [source for source in source_rows if source.get("source_role") == role and source.get("filename") == filename]
    assert matches, "Manifest omits uploaded source " + filename
    expected_hash = hashlib.sha256((fixture / filename).read_bytes()).hexdigest()
    assert all(source["content_hash"] == expected_hash for source in matches), "Manifest source does not match uploaded bytes"
for fact in manifest["facts"]:
    reference = fact.get("source")
    if reference:
        assert reference["source_id"] in sources, "Fact references missing source anchor: " + fact["fact_id"]
        anchor = sources[reference["source_id"]]
        for key in ["document_version_id", "content_hash", "locator"]:
            assert reference[key] == anchor[key], "Fact source " + key + " differs from manifest anchor: " + fact["fact_id"]
    correction_source = fact.get("correction_source_id")
    if correction_source:
        assert correction_source in sources, "Correction references missing source anchor: " + fact["fact_id"]
        anchor = sources[correction_source]
        assert fact["fact_id"] in anchor.get("fact_ids", []), "Correction evidence does not support this fact"
        assert anchor.get("locator") and anchor.get("document_version_id"), "Correction lacks exact source location/version"
        assert anchor["content_hash"] == hashlib.sha256((fixture / "fee-rule.csv").read_bytes()).hexdigest(), "Correction source is not the uploaded approved rule"
ns = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
with zipfile.ZipFile(workbook_path) as archive:
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    targets = {item.attrib["Id"]: item.attrib["Target"] for item in relationships}
    for fact_id, sheet_name, address in expected["bindings"]:
        sheet = next(sheet for sheet in workbook.find("s:sheets", ns) if sheet.attrib["name"] == sheet_name)
        target = targets[sheet.attrib["{" + ns["r"] + "}id"]]
        target = target.lstrip("/") if target.startswith("/") else "xl/" + target
        root = ET.fromstring(archive.read(target))
        cell = root.find(".//s:c[@r='" + address + "']", ns)
        assert cell is not None, "Missing output cell " + address
        value = cell.findtext("s:v", namespaces=ns)
        if cell.attrib.get("t") == "inlineStr":
            value = "".join(cell.find("s:is", ns).itertext())
        assert value is not None, "Output cell has no materialised value"
        assert cell.find("s:f", ns) is None, "Output contains unevaluated formula"
        assert Decimal(value) == Decimal(expected["expected"][fact_id]), "Incorrect output amount at " + address
print("Downloaded workbook mapped values, exact-source hashes, reviewer, exact fact/correction source anchors and manifest integrity verified.")
