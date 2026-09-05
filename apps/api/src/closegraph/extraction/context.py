"""Normalise only explicit scoped meaning; imported claims confer no authority.

The mapping argument must be loaded from authorised server state by the caller,
not taken from document content. This pure tool is not an authorisation service.
Supported periods: YYYY, YYYY-Qn, YYYY-MM, ISO calendar date. No date guessing.
"""
from copy import deepcopy
from datetime import date
import re
from typing import Any, TypedDict
from .common import valid_source
from .numbers import NumericError, NumericFormat, normalise_number

SUPPORTED_CURRENCIES = frozenset("GBP USD EUR CAD AUD CHF JPY NZD HKD SGD NOK SEK DKK".split())


class NormalisedFact(TypedDict, total=False):
    occurrence_id: str
    source: dict[str, Any]
    raw_value: Any
    raw_scale: str | None
    metric: str
    entity_id: str | None
    currency: str | None
    period: str | None
    value_decimal: str | None
    interpretation_status: str
    interpretation_reasons: list[str]
    mapping_version: str
    mapping_approval_id: str


def valid_period(value: object) -> bool:
    if not isinstance(value, str):
        return False
    if re.fullmatch(r"[1-9][0-9]{3}(?:-Q[1-4])?", value):
        return True
    if re.fullmatch(r"[1-9][0-9]{3}-(?:0[1-9]|1[0-2])", value):
        return True
    if re.fullmatch(r"[1-9][0-9]{3}-[0-9]{2}-[0-9]{2}", value):
        try:
            date.fromisoformat(value)
            return True
        except ValueError:
            pass
    return False


def context_errors(fact: dict) -> list[str]:
    reasons = []
    entity = fact.get("entity_id")
    if not isinstance(entity, str) or not entity.strip() or entity != entity.strip():
        reasons.append("invalid_entity")
    if not isinstance(fact.get("currency"), str) or fact["currency"] not in SUPPORTED_CURRENCIES:
        reasons.append("invalid_currency")
    if not valid_period(fact.get("period")):
        reasons.append("invalid_period")
    return reasons


def normalise_fact(observation: dict, *, mapping: dict,
                   fmt: NumericFormat = NumericFormat()) -> NormalisedFact:
    result = deepcopy(observation)
    # Never let a source-provided value_decimal bypass parsing of raw evidence.
    result["value_decimal"] = None
    reasons = context_errors(result)
    if not valid_source(result.get("source")) or not isinstance(result.get("occurrence_id"), str) or not result["occurrence_id"]:
        reasons.append("missing_or_invalid_evidence")
    if result.get("formula") is not None or result.get("interpretation_status") not in (None, "UNRESOLVED", "RESOLVED"):
        reasons.append("source_interpretation_unresolved")
    if (mapping.get("approved") is not True or not isinstance(mapping.get("approval_id"), str)
            or not mapping["approval_id"].strip() or not isinstance(mapping.get("version"), str)
            or not mapping["version"].strip()):
        reasons.append("mapping_not_authorised")
    if any(mapping.get(k) != result.get(k) for k in ("entity_id", "period")):
        reasons.append("mapping_scope_mismatch")
    mappings = mapping.get("mapping")
    raw_metric = result.get("metric")
    metric = mappings.get(raw_metric) if isinstance(mappings, dict) and isinstance(raw_metric, str) else None
    if not isinstance(metric, str) or re.fullmatch(r"[a-z][a-z0-9_]*", metric) is None:
        reasons.append("unmapped_metric")
    try:
        numeric = normalise_number(result.get("raw_value"), scale=result.get("raw_scale"), fmt=fmt)
        if numeric["value_decimal"] is None:
            reasons.append("missing_value")
    except NumericError as exc:
        reasons.append(str(exc))
        numeric = {"value_decimal": None}
    result["interpretation_reasons"] = reasons
    result["interpretation_status"] = "UNRESOLVED" if reasons else "RESOLVED"
    if not reasons:
        result.update(value_decimal=numeric["value_decimal"], metric=metric,
                      mapping_version=mapping["version"], mapping_approval_id=mapping["approval_id"])
    return result
