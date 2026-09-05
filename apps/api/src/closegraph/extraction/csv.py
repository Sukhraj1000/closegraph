"""Bounded, explicitly laid out UTF CSV; no type inference or row dropping."""
import csv
from dataclasses import dataclass
from io import StringIO
import polars as pl
from .common import ExtractionError, ExtractionLimits, checked_source, native_result, occurrence_id


@dataclass(frozen=True)
class CSVLayout:
    columns: tuple[str, ...]
    required_fields: tuple[str, ...] = ()
    delimiter: str = ","
    encoding: str = "utf-8-sig"

    def __post_init__(self):
        if (not self.columns or any(not isinstance(c, str) or not c for c in self.columns)
                or len(set(self.columns)) != len(self.columns)
                or not set(self.required_fields) <= set(self.columns)
                or len(self.delimiter) != 1 or self.delimiter in '\r\n"\0'
                or self.encoding not in ("utf-8", "utf-8-sig", "cp1252")):
            raise ExtractionError("unsupported_layout")


def extract_csv(data: bytes, *, document_version_id: str, layout: CSVLayout,
                limits: ExtractionLimits = ExtractionLimits(), content_hash: str | None = None) -> dict:
    digest = checked_source(data, document_version_id, content_hash, limits)
    if len(layout.columns) > limits.max_columns:
        raise ExtractionError("column_limit")
    try:
        text = data.decode(layout.encoding, errors="strict")
    except UnicodeDecodeError as exc:
        raise ExtractionError("invalid_encoding") from exc
    if "\0" in text:
        raise ExtractionError("malformed_csv")
    lines = list(StringIO(text, newline=""))  # Preserve CR/LF and multiline record spelling.
    reader = csv.reader(lines, delimiter=layout.delimiter, strict=True)
    observations, dispositions, accepted = [], [], []
    try:
        header = next(reader, None)
        if header != list(layout.columns):
            raise ExtractionError("unsupported_layout")
        previous, cells = reader.line_num, len(header)
        for number, tokens in enumerate(reader, 1):
            if number > limits.max_rows:
                raise ExtractionError("row_limit")
            cells += len(tokens)
            if cells > limits.max_cells or len(tokens) > limits.max_columns:
                raise ExtractionError("cell_or_column_limit")
            if any(len(token) > limits.max_field_chars for token in tokens):
                raise ExtractionError("field_limit")
            locator = {"kind": "csv", "row": previous + 1, "end_row": reader.line_num}
            raw_record = "".join(lines[previous:reader.line_num])
            previous = reader.line_num
            oid = occurrence_id(document_version_id, digest, locator)
            source = {"document_version_id": document_version_id, "content_hash": digest, "locator": locator}
            reasons = []
            if len(tokens) != len(header):
                reasons.append("column_count")
            values = dict(zip(header, tokens)) if not reasons else {}
            reasons.extend("missing_required:" + key for key in layout.required_fields
                           if key in values and not values[key].strip())
            disposition = "REJECTED" if reasons else "ACCEPTED"
            dispositions.append({"occurrence_id": oid, "disposition": disposition,
                                 "reasons": reasons, "source": source,
                                 "raw_tokens": tokens, "raw_record": raw_record})
            observations.append({"occurrence_id": oid, "raw_values": values,
                                 "raw_tokens": tokens, "raw_record": raw_record,
                                 "source": source, "interpretation_status": "UNRESOLVED"})
            if not reasons:
                accepted.append(values)
    except csv.Error as exc:
        code = "field_limit" if "field larger" in str(exc) else "malformed_csv"
        raise ExtractionError(code) from exc
    result = native_result(data, document_version_id, digest, observations, dispositions)
    result["frame"] = pl.DataFrame(accepted, schema={key: pl.String for key in layout.columns})
    return result
