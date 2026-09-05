"""Data-level Pandera validation: never drop or coerce rejected financial rows."""
import pandera.polars as pa
import polars as pl
from closegraph.extraction.context import SUPPORTED_CURRENCIES

SCHEMA = pa.DataFrameSchema({
    'entity_id':pa.Column(str, pa.Check.str_matches(r'^\S(?:.*\S)?$')),
    'period':pa.Column(str, pa.Check.str_matches(r'^[1-9][0-9]{3}(?:-Q[1-4]|-(?:0[1-9]|1[0-2]))?$')),
    'currency':pa.Column(str, pa.Check.isin(sorted(SUPPORTED_CURRENCIES))),
    'metric':pa.Column(str, pa.Check.str_matches(r'^[a-z][a-z0-9_]*$')),
    'value':pa.Column(str, pa.Check.str_matches(r'^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$')),
    'scale':pa.Column(str, pa.Check.isin(['units','thousands','millions'])),
}, strict=True, coerce=False)


def validate_rows(frame: pl.DataFrame) -> dict:
    try:
        SCHEMA.validate(frame, lazy=True)
        if not frame.height:
            raise ValueError('No source records')
    except (pa.errors.SchemaError, pa.errors.SchemaErrors, ValueError) as error:
        return dict(id='data_schema',required=True,status='FAIL',diagnostics=[str(error)[:4000]])
    return dict(id='data_schema',required=True,status='PASS',diagnostics=[],row_count=frame.height)
