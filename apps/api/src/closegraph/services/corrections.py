from decimal import Decimal, InvalidOperation
from copy import deepcopy
from .errors import DomainError


def decimal_text(value):
    if not isinstance(value, str) or not value or value.strip() != value:
        raise DomainError("Decimal must be a finite decimal string")
    try:
        number = Decimal(value)
    except InvalidOperation as e:
        raise DomainError("Invalid decimal") from e
    if not number.is_finite() or len(number.as_tuple().digits) > 28 or abs(number.as_tuple().exponent) > 12:
        raise DomainError("Unsupported decimal precision or magnitude")
    return format(number, "f")


def corrected_facts(facts, *, fact_id, value_decimal, reason, source_id, evidence):
    if not reason or not reason.strip():
        raise DomainError("An evidence-backed reason is required")
    value = decimal_text(value_decimal)
    old = next((f for f in facts if f["fact_id"] == fact_id), None)
    if old is None or old.get("derived"):
        raise DomainError("Unsupported correction target")
    source = evidence.get(source_id)
    if not source or fact_id not in source.get("fact_ids", ()) or not source.get("locator"):
        raise DomainError("Correction evidence does not support this fact")
    if any(source.get(k) != old.get(k) for k in ("entity_id", "currency", "period")):
        raise DomainError("Correction evidence context mismatch")
    result = deepcopy(facts)
    fact = next(f for f in result if f["fact_id"] == fact_id)
    fact["value_decimal"] = value
    fact["supersedes"] = old.get("fact_version", 1)
    fact["fact_version"] = old.get("fact_version", 1) + 1
    fact["correction_source_id"] = source_id
    fact["interpretation_status"] = "CORRECTED"
    fact["correction_id"] = fact_id + ":correction:v" + str(fact["fact_version"])
    # Raw tokens/source/observations remain immutable, not rewritten as extraction.
    return result, old["value_decimal"]
