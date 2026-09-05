from typing import Literal

from pydantic import model_validator

from .evidence import SourceRef
from .types import Contract, Currency, ExactDecimal, Identifier, Scope, Version


class FactVersion(Contract):
    scope: Scope
    fact_id: Identifier
    version: Version
    metric: Identifier
    entity_id: Identifier | None
    period: Identifier | None
    value_decimal: ExactDecimal | None
    currency: Currency | None
    raw_value: str | None
    raw_scale: str | None
    value_state: Literal["PRESENT", "MISSING", "NOT_APPLICABLE", "CONFLICTING", "AMBIGUOUS"]
    interpretation_status: Literal["UNRESOLVED", "RULE_MAPPED", "CORRECTED"]
    source: SourceRef
    observation_ids: tuple[Identifier, ...]
    interpretation_rule_id: Identifier | None = None
    correction_id: Identifier | None = None
    supersedes: Identifier | None = None

    @model_validator(mode="after")
    def coherent_value(self):
        if self.value_state == "PRESENT" and self.value_decimal is None:
            raise ValueError("present value requires a decimal, including explicit zero")
        if self.value_state in {"MISSING", "NOT_APPLICABLE"} and self.value_decimal is not None:
            raise ValueError("missing/not-applicable must not acquire a numeric value")
        if self.interpretation_status == "CORRECTED" and not self.correction_id:
            raise ValueError("corrected interpretation requires correction provenance")
        if self.interpretation_status == "RULE_MAPPED" and not self.interpretation_rule_id:
            raise ValueError("mapped interpretation requires rule provenance")
        return self
