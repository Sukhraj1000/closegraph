"""Exact scalar contracts. Never construct money from a binary float."""
import re
from decimal import Decimal, InvalidOperation
from typing import Annotated

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    PlainSerializer,
    StrictStr,
    WithJsonSchema,
)


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)


Identifier = Annotated[StrictStr, Field(min_length=1, max_length=256)]
ContentHash = Annotated[StrictStr, Field(pattern=r"^[a-f0-9]{64}$")]
Version = Annotated[int, Field(strict=True, ge=1)]


def exact_decimal(value):
    if isinstance(value, Decimal):
        number = value
    elif isinstance(value, str) and re.fullmatch(r"-?(0|[1-9][0-9]*)(\.[0-9]+)?", value) and len(value) <= 1024:
        try:
            number = Decimal(value)
        except InvalidOperation as exc:
            raise ValueError("invalid decimal") from exc
    else:
        raise ValueError("decimal must be a canonical decimal string or Decimal, never a JSON number")
    if not number.is_finite() or len(number.as_tuple().digits) > 1000 or abs(number.as_tuple().exponent) > 256:
        raise ValueError("decimal is non-finite or outside supported precision")
    return number


ExactDecimal = Annotated[Decimal, BeforeValidator(exact_decimal),
    PlainSerializer(lambda value: format(value, "f"), return_type=str, when_used="json"),
    WithJsonSchema({"type":"string", "pattern":r"^-?(0|[1-9][0-9]*)(\.[0-9]+)?$"})]
Currency = Annotated[StrictStr, Field(pattern=r"^[A-Z]{3}$")]


class Scope(Contract):
    tenant_id: Identifier
    fund_id: Identifier
    pack_id: Identifier
