"""Strict bounded decimal parsing with an isolated accounting context."""
from dataclasses import dataclass
from decimal import Context, Decimal, DecimalException, ROUND_HALF_EVEN, localcontext
import re
from typing import TypedDict

# All operations use this context, never the process/thread ambient precision.
DECIMAL_CONTEXT = Context(prec=256, rounding=ROUND_HALF_EVEN)
SCALES = {"units": Decimal("1"), "thousands": Decimal("1000"), "millions": Decimal("1000000")}


class NumericError(ValueError):
    pass


@dataclass(frozen=True)
class NumericFormat:
    decimal_separator: str = "."
    thousands_separator: str | None = ","

    def __post_init__(self):
        if (self.decimal_separator not in (".", ",")
                or self.thousands_separator not in (None, ",", ".", " ")
                or self.thousands_separator == self.decimal_separator):
            raise NumericError("invalid_numeric_format")


class NormalisedNumber(TypedDict):
    raw_value: str | int | Decimal | None
    raw_scale: str
    value_decimal: str | None


def bounded_decimal(value: Decimal) -> Decimal:
    if (not value.is_finite() or len(value.as_tuple().digits) > 80
            or abs(value.as_tuple().exponent) > 80 or abs(value.adjusted()) > 80):
        raise NumericError("nonfinite_or_numeric_limit")
    return value


def parse_decimal(raw: str | int | Decimal | None, fmt: NumericFormat = NumericFormat()) -> Decimal | None:
    if raw is None:
        return None
    if isinstance(raw, bool) or isinstance(raw, float):
        raise NumericError("binary_float_or_boolean_forbidden")
    if isinstance(raw, Decimal):
        return bounded_decimal(raw)
    if isinstance(raw, int):
        return bounded_decimal(Decimal(raw))
    if not isinstance(raw, str) or len(raw) > 512:
        raise NumericError("invalid_numeric_token")
    token = raw.strip()
    if token in ("", "NA", "N/A"):
        return None
    negative = token.startswith("(") and token.endswith(")")
    if negative:
        token = token[1:-1]
        if token.startswith(("+", "-")):
            raise NumericError("ambiguous_sign")
    ds = re.escape(fmt.decimal_separator)
    ts = re.escape(fmt.thousands_separator) if fmt.thousands_separator is not None else None
    integer = rf"(?:[0-9]+|[0-9]{{1,3}}(?:{ts}[0-9]{{3}})+)" if ts is not None else r"[0-9]+"
    if re.fullmatch(rf"[+-]?{integer}(?:{ds}[0-9]+)?(?:[eE][+-]?[0-9]{{1,3}})?", token) is None:
        raise NumericError("invalid_numeric_token")
    if fmt.thousands_separator is not None:
        token = token.replace(fmt.thousands_separator, "")
    token = token.replace(fmt.decimal_separator, ".")
    try:
        value = Decimal(("-" if negative else "") + token)
        return bounded_decimal(value)
    except DecimalException as exc:
        raise NumericError("invalid_numeric_token") from exc


def normalise_number(raw: str | int | Decimal | None, *, scale: str,
                     fmt: NumericFormat = NumericFormat()) -> NormalisedNumber:
    if not isinstance(scale, str) or scale not in SCALES:
        raise NumericError("explicit_supported_scale_required")
    value = parse_decimal(raw, fmt)
    with localcontext(DECIMAL_CONTEXT):
        normal = bounded_decimal(value * SCALES[scale]) if value is not None else None
    return {"raw_value": raw, "raw_scale": scale,
            "value_decimal": format(normal, "f") if normal is not None else None}
