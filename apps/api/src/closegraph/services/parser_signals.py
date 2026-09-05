"""Independent confidence and agreement signals for a declared candidate pair."""
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation

from closegraph.contracts import Confidence, ExtractionObservation, ObservationCandidate

CONTEXT = ("entity_id", "metric", "period", "currency", "raw_scale")
ABSENT_SIGNALS = frozenset({"NOT_RUN", "UNAVAILABLE", "NOT_APPLICABLE"})


def compare_observations(primary, secondary, *, availability="NOT_RUN"):
    """Compare fully normalized contextual candidates, preserving absence states."""
    if secondary is None:
        return availability if availability in ABSENT_SIGNALS else "UNKNOWN"
    if (isinstance(primary, ExtractionObservation) and isinstance(secondary, ExtractionObservation)
            and primary.scope != secondary.scope):
        return "DISAGREE"
    if isinstance(primary, ExtractionObservation):
        primary = primary.candidate
    if isinstance(secondary, ExtractionObservation):
        secondary = secondary.candidate
    if isinstance(primary, ObservationCandidate):
        primary = primary.model_dump()
    if isinstance(secondary, ObservationCandidate):
        secondary = secondary.model_dump()
    if not isinstance(primary, Mapping) or not isinstance(secondary, Mapping):
        return "UNKNOWN"
    if any(not isinstance(item.get(key), str) or not item[key].strip()
           for item in (primary, secondary) for key in CONTEXT):
        return "UNKNOWN"
    values = (primary.get("value_decimal"), secondary.get("value_decimal"))
    # Financial candidates must already use exact decimal semantics.
    if any(isinstance(value, (bool, float)) or not isinstance(value, (str, int, Decimal))
           for value in values):
        return "UNKNOWN"
    try:
        first, second = (Decimal(value) for value in values)
        if not first.is_finite() or not second.is_finite():
            return "UNKNOWN"
    except (InvalidOperation, TypeError, ValueError):
        return "UNKNOWN"
    same = first == second and all(primary[key] == secondary[key] for key in CONTEXT)
    return "AGREE" if same else "DISAGREE"


def confidence_signal(confidence, *, native=False):
    """Retain reported scores and provenance without interpreting them as correctness."""
    if confidence is None:
        return {"status": "NOT_APPLICABLE" if native else "UNAVAILABLE", "value": None,
                "reason": "Native deterministic extraction" if native else "No confidence was returned"}
    if isinstance(confidence, Confidence):
        confidence = confidence.model_dump(mode="json")
    if not isinstance(confidence, Mapping):
        return {"status": "UNAVAILABLE", "value": None, "reason": "Malformed confidence observation"}
    result = dict(confidence)
    status = result.get("status")
    if status in ABSENT_SIGNALS:
        result["value"] = None
        result.setdefault("reason", "Provider confidence is " + status.lower())
        return result
    if status != "AVAILABLE" or not result.get("kind") or not result.get("provenance"):
        return {"status": "UNAVAILABLE", "value": None, "reason": "Confidence value/type/provenance is incomplete"}
    try:
        raw = result.get("value")
        if isinstance(raw, bool) or not isinstance(raw, (str, int, float, Decimal)):
            raise TypeError("Invalid score type")
        value = Decimal(str(raw))
        if not value.is_finite():
            raise ValueError("Nonfinite score")
    except (InvalidOperation, TypeError, ValueError):
        return {"status": "UNAVAILABLE", "value": None, "reason": "Malformed provider confidence value"}
    # Keep the original numeric spelling/type. No threshold or probability conversion.
    return result
