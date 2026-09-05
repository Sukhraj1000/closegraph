"""Optional independent parser observations; no mandatory second-parser dependency."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from closegraph.contracts import ExtractionObservation, Scope


@dataclass(frozen=True)
class ObservationComparison:
    primary_id: str
    secondary_id: str | None
    status: Literal["AGREE", "DISAGREE", "UNKNOWN"]
    reason: str


@dataclass(frozen=True)
class SecondPassResult:
    status: Literal["NOT_RUN", "UNAVAILABLE", "COMPLETED"]
    primary: tuple[ExtractionObservation, ...]
    secondary: tuple[ExtractionObservation, ...] = ()
    comparisons: tuple[ObservationComparison, ...] = ()
    reason: str | None = None


class SecondParser(Protocol):
    def observe(self, source: bytes, *, scope: Scope, document_version_id: str
                ) -> tuple[ExtractionObservation, ...]: ...


def compare_observations(primary: ExtractionObservation,
                         secondary: ExtractionObservation) -> ObservationComparison:
    """Compare an explicitly matched occurrence in its complete candidate context."""
    if primary.scope != secondary.scope or primary.occurrence_id != secondary.occurrence_id:
        return ObservationComparison(primary.observation_id, secondary.observation_id,
                                     "DISAGREE", "scope_or_source_occurrence_differs")
    fields = ("metric", "value_decimal", "entity_id", "period", "currency", "raw_scale")
    left = tuple(getattr(primary.candidate, name) for name in fields)
    right = tuple(getattr(secondary.candidate, name) for name in fields)
    if any(value is None for value in left + right):
        return ObservationComparison(primary.observation_id, secondary.observation_id,
                                     "UNKNOWN", "incomplete_context_cannot_establish_agreement")
    same = left == right
    return ObservationComparison(primary.observation_id, secondary.observation_id,
                                 "AGREE" if same else "DISAGREE",
                                 "complete_context_matches" if same else "value_or_context_differs")


def run_second_pass(primary: tuple[ExtractionObservation, ...], source: bytes, *,
                    scope: Scope, document_version_id: str, requested: bool = False,
                    parser: SecondParser | None = None) -> SecondPassResult:
    """Keep original observations; absence and service failure are never agreement."""
    primary = tuple(primary)
    if any(item.scope != scope for item in primary):
        raise ValueError("Primary observations must belong to the requested scope")
    if not requested:
        return SecondPassResult("NOT_RUN", primary, reason="Optional second parser was not requested")
    if parser is None:
        return SecondPassResult("UNAVAILABLE", primary, reason="No optional parser is configured")
    try:
        secondary = tuple(parser.observe(source, scope=scope,
                                         document_version_id=document_version_id))
        if any(not isinstance(item, ExtractionObservation) or item.scope != scope for item in secondary):
            raise ValueError("Second parser returned invalid or out-of-scope observations")
    except Exception as exc:  # noqa: BLE001 - optional external parser failures are explicit UNAVAILABLE
        return SecondPassResult("UNAVAILABLE", primary,
                                reason="Second parser unavailable: " + type(exc).__name__)
    pairs = []
    for first in primary:
        matches = [item for item in secondary if item.occurrence_id == first.occurrence_id]
        if len(matches) != 1:
            pairs.append(ObservationComparison(first.observation_id, None, "UNKNOWN",
                                               "missing_or_ambiguous_second_observation"))
        else:
            pairs.append(compare_observations(first, matches[0]))
    if not secondary:
        return SecondPassResult("UNAVAILABLE", primary, reason="Second parser returned no observations")
    return SecondPassResult("COMPLETED", primary, secondary, tuple(pairs))
