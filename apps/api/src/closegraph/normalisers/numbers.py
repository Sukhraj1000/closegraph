"""Specification namespace for the existing exact numeric normalizer."""
from closegraph.extraction.numbers import (
    DECIMAL_CONTEXT,
    SCALES,
    NormalisedNumber,
    NumericError,
    NumericFormat,
    bounded_decimal,
    normalise_number,
    parse_decimal,
)

__all__ = ["DECIMAL_CONTEXT", "SCALES", "NormalisedNumber", "NumericError", "NumericFormat",
           "bounded_decimal", "normalise_number", "parse_decimal"]
