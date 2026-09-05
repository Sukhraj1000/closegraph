"""Conservative XLSX adapter. Never evaluate formulas, macros or links.

openpyxl supplies workbook/string/style semantics; numeric source tokens come
from XML rather than its float conversion. Formula caches are never current.
"""
from dataclasses import dataclass
from io import BytesIO
from pathlib import PurePosixPath
import posixpath
import re
from xml.etree import ElementTree as ET
from zipfile import ZipFile, BadZipFile
from openpyxl import load_workbook
from openpyxl.utils.cell import coordinate_from_string, column_index_from_string
from openpyxl.styles.numbers import is_date_format
from .common import (ExtractionError, ExtractionLimits, checked_source,
                     native_result, occurrence_id, valid_cell)

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"


@dataclass(frozen=True)
class ExcelLayout:
    sheet: str
    cells: tuple[str, ...]

    def __post_init__(self):
        if (not isinstance(self.sheet, str) or not self.sheet.strip() or not self.cells
                or len(set(self.cells)) != len(self.cells) or not all(map(valid_cell, self.cells))):
            raise ExtractionError("unsupported_layout")


def _xml(payload: bytes):
    # Explicitly limit supported XML encoding; reject entities before parsing.
    if b"\0" in payload or b"<!DOCTYPE" in payload.upper() or b"<!ENTITY" in payload.upper():
        raise ExtractionError("unsafe_xml")
    try:
        return ET.fromstring(payload.decode("utf-8-sig"))
    except (UnicodeError, ET.ParseError) as exc:
        raise ExtractionError("invalid_xlsx") from exc


def _archive(data: bytes, limits: ExtractionLimits) -> dict:
    with ZipFile(BytesIO(data)) as archive:
        infos = archive.infolist()
        if len(infos) > limits.max_zip_members:
            raise ExtractionError("zip_member_limit")
        if len({i.filename for i in infos}) != len(infos):
            raise ExtractionError("duplicate_zip_member")
        if sum(i.file_size for i in infos) > limits.max_uncompressed_bytes:
            raise ExtractionError("uncompressed_limit")
        trees = {}
        for info in infos:
            name = info.filename
            if (name.startswith("/") or "\\" in name or ":" in name or "\0" in name
                    or ".." in PurePosixPath(name).parts or posixpath.normpath(name) != name.rstrip("/")):
                raise ExtractionError("unsafe_zip_member")
            lower = name.lower()
            if "vba" in lower or "macrosheet" in lower or "activex" in lower or "/embeddings/" in lower:
                raise ExtractionError("unsupported_macros")
            if "externallinks/" in lower or lower.endswith("connections.xml") or "/querytables/" in lower:
                raise ExtractionError("unsupported_external_links")
            if info.flag_bits & 1:
                raise ExtractionError("encrypted_xlsx")
            if info.file_size > max(info.compress_size, 1) * limits.max_compression_ratio:
                raise ExtractionError("compression_ratio_limit")
            if name.endswith((".xml", ".rels")):
                payload = archive.read(info)
                if len(payload) > limits.max_uncompressed_bytes:
                    raise ExtractionError("uncompressed_limit")
                if b"macroEnabled" in payload or b"vbaProject" in payload:
                    raise ExtractionError("unsupported_macros")
                tree = trees[name] = _xml(payload)
                if any(node.attrib.get("TargetMode", "").lower() == "external" for node in tree.iter()):
                    raise ExtractionError("unsupported_external_links")
        cells = rows = 0
        for name, tree in trees.items():
            if not name.startswith("xl/worksheets/") or not name.endswith(".xml"):
                continue
            rows += len(tree.findall(".//" + NS + "row"))
            seen = set()
            for cell in tree.findall(".//" + NS + "c"):
                address = cell.get("r")
                if not valid_cell(address) or address in seen:
                    raise ExtractionError("invalid_xlsx")
                seen.add(address)
                column, row = coordinate_from_string(address)
                if row > limits.max_rows or column_index_from_string(column) > limits.max_columns:
                    raise ExtractionError("worksheet_dimension_limit")
                cells += 1
            if rows > limits.max_rows or cells > limits.max_cells:
                raise ExtractionError("worksheet_cell_or_row_limit")
            dimension = tree.find(NS + "dimension")
            if dimension is not None:
                for address in dimension.get("ref", "").split(":"):
                    if not valid_cell(address):
                        raise ExtractionError("invalid_xlsx")
                    column, row = coordinate_from_string(address)
                    if row > limits.max_rows or column_index_from_string(column) > limits.max_columns:
                        raise ExtractionError("worksheet_dimension_limit")
        return trees


def extract_excel(data: bytes, *, document_version_id: str, layout: ExcelLayout,
                  limits: ExtractionLimits = ExtractionLimits(), content_hash: str | None = None) -> dict:
    digest = checked_source(data, document_version_id, content_hash, limits)
    if len(layout.cells) > limits.max_cells:
        raise ExtractionError("cell_limit")
    for address in layout.cells:
        column, row = coordinate_from_string(address)
        if row > limits.max_rows or column_index_from_string(column) > limits.max_columns:
            raise ExtractionError("worksheet_dimension_limit")
    try:
        trees = _archive(data, limits)
        book = trees["xl/workbook.xml"]
        rels = {r.attrib["Id"]: r.attrib["Target"] for r in trees["xl/_rels/workbook.xml.rels"]}
        sheets = book.findall(NS + "sheets/" + NS + "sheet")
        chosen = [s for s in sheets if s.get("name") == layout.sheet]
        if len(chosen) != 1:
            raise ExtractionError("unsupported_layout")
        target = rels[chosen[0].attrib[REL + "id"]]
        if ".." in PurePosixPath(target).parts or "\\" in target:
            raise ExtractionError("unsafe_zip_member")
        path = target.lstrip("/") if target.startswith("/") else "xl/" + target
        tree = trees[path]
        xml_cells = {c.attrib["r"]: c for c in tree.findall(".//" + NS + "c")}
        # Sparse in-memory workbook avoids read-only dimension iteration on repeated access.
        workbook = load_workbook(BytesIO(data), data_only=False, read_only=False, keep_links=False)
        try:
            sheet = workbook[layout.sheet]
            observations, dispositions = [], []
            for address in layout.cells:
                cell, node = sheet[address], xml_cells.get(address)
                raw_xml = node.findtext(NS + "v") if node is not None else None
                formula_node = node.find(NS + "f") if node is not None else None
                kind = node.get("t", "n") if node is not None else None
                formula = None
                cached = None
                cache_status = "NOT_APPLICABLE"
                if formula_node is not None:
                    formula = "=" + (formula_node.text or "")
                    raw = formula
                    cached = raw_xml or None
                    cache_status = "UNVERIFIED" if cached is not None else "MISSING"
                    status = "FORMULA_UNRESOLVED"
                elif node is None or cell.value is None:
                    raw, status = None, "MISSING"
                elif kind == "n":
                    raw = raw_xml
                    status = "UNSUPPORTED_TYPE" if is_date_format(cell.number_format) else "UNRESOLVED"
                elif kind in ("s", "inlineStr", "str") and isinstance(cell.value, str):
                    raw, status = cell.value, "UNRESOLVED"
                else:
                    raw, status = raw_xml, "UNSUPPORTED_TYPE"
                if any(value is not None and len(value) > limits.max_field_chars for value in (raw, cached)):
                    raise ExtractionError("field_limit")
                locator = {"kind": "xlsx", "sheet": layout.sheet, "cell": address}
                oid = occurrence_id(document_version_id, digest, locator)
                source = {"document_version_id": document_version_id, "content_hash": digest, "locator": locator}
                observations.append({"occurrence_id": oid, "source": source, "raw_value": raw,
                                     "raw_xml_value": raw_xml, "cell_type": kind,
                                     "number_format": cell.number_format, "formula": formula,
                                     "cached_value": cached, "cache_status": cache_status,
                                     "interpretation_status": status})
                dispositions.append({"occurrence_id": oid, "source": source,
                                     "disposition": "ACCEPTED" if status == "UNRESOLVED" else "UNRESOLVED",
                                     "reasons": [] if status == "UNRESOLVED" else [status]})
        finally:
            workbook.close()
    except ExtractionError:
        raise
    except (BadZipFile, KeyError, ValueError, TypeError, IndexError, OSError, OverflowError, RuntimeError) as exc:
        raise ExtractionError("invalid_xlsx") from exc
    return native_result(data, document_version_id, digest, observations, dispositions)
