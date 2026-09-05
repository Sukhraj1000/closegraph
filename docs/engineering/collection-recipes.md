# Collection recipes and verified exports

Collection recipes are explicit, versioned configuration. They do not execute Python, SQL,
expression strings or LLM output. Source tables are retained; transformations return a new
selected output and recorded issues. Input acceptance and independent output review are
separate application decisions.

## Recipe shape

```json
{
  "version": 1,
  "steps": [
    {
      "id": "calculated",
      "op": "derive",
      "input": "the-selected-table-id",
      "columns": {
        "total": {"op": "add", "args": [{"column": "c2"}, {"column": "c3"}]}
      }
    }
  ],
  "output": "calculated",
  "checks": [
    {"type": "required", "columns": ["c1", "total"]},
    {"type": "unique", "columns": ["c1"]}
  ]
}
```

`input`, `right`, `output` and check `table` reference a source table ID or an earlier step
ID. Step IDs cannot shadow source tables. An empty steps list can select a source table as
output. Column references use stable keys, not inferred labels or filenames. A recipe can
include the application's `export` configuration; the transform engine does not act on it.

Numbers remain decimal strings. Canonical decimal syntax is an optional sign, digits and
an optional decimal point. Scientific notation, currency symbols and locale punctuation
require upstream correction or explicit conversion; they are never guessed. Null differs
from empty text. Expressions in the same derive step read the input snapshot; use another
step to depend on a newly derived column.

## Operations

Each operation includes `id`, `op` and `input` in addition to these fields.

| Operation | Additional fields | Behavior |
| --- | --- | --- |
| `select` | `columns: [key, ...]` | Select/reorder columns. |
| `rename` | `columns: {oldKey: newKey}` | Rename keys without collisions; source labels and lineage remain. |
| `filter` | `where: condition` | Keep matching rows. Invalid comparison values remain visible and create blocking issues. |
| `derive` | `columns: {outputKey: expression}` | Calculate new or explicitly replace existing fields. |
| `sort` | `by: [{column, direction?: "asc" or "desc", type?: "text" or "decimal"}]` | Stable ordering; null/invalid values appear last. Defaults are ascending text. |
| `join` / `lookup` | `right`, `on: [{left, right}]`, `columns: {rightKey: outputKey}`, `how?: "left" or "inner"`, `cardinality?: "many_to_one" or "one_to_many"` | Exact key matching. Defaults left/many-to-one. Lookup supports many-to-one only. Output columns must not overwrite left columns. |
| `aggregate` | `by: [key, ...]`, `metrics: {outputKey: {op: "sum", "count", "min" or "max", column?: key}}` | Decimal numeric aggregates, row count without a column. Empty `by` produces one group when rows exist. |
| `classify` | `column: outputKey`, `rules: [{when: condition, value: literal}]`, `default?: literal` | Exactly one matching rule supplies its explicit value. Multiple matches block; missing match blocks unless an explicit default exists. |
| `allocate` | `by?: [key, ...]`, `weight: key`, `total: expression`, `column: outputKey`, `scale?: 2` | Groupwise proportional allocation conserving the declared total. |
| `reshape` (`melt`) | `mode: "melt"`, `id_columns: [key, ...]`, `value_columns: [key, ...]`, `variable_column?: "variable"`, `value_column?: "value"` | One row per selected source value; category values are stable source column keys. |
| `reshape` (`pivot`) | `mode: "pivot"`, `id_columns: [key, ...]`, `variable_column: key`, `value_column: key`, `columns: {categoryValue: outputKey}` | Explicit category-to-column binding; duplicate output cells block rather than implicitly sum. |

Blank/null join keys never match each other. Unmatched and ambiguous joins create error
issues even in an inner join that excludes those rows. Many-to-one ambiguity produces no
selected reference value. Explicit one-to-many joins retain every match with stable distinct
row IDs. This prevents reference matching from silently inventing accounting treatment.

Allocation requires nonnegative weights with a positive group sum and the same total for
every member of a group. The total must fit the chosen 0–12 decimal-place scale. It applies
the largest-remainder method to the absolute total, breaking equal remainders by source row
ID, then restores its sign. This preserves the total for positive, zero and negative amounts.
A total or weight error leaves the whole group unresolved.

### Expressions

An expression is `{"column":"c2"}`, `{"literal":"12.50"}`, or
`{"op":"add","args":[expression,expression]}`. Literal values are text, integer or null;
use strings for decimal literals. No executable source is accepted.

| Operation | Arguments and options |
| --- | --- |
| `add`, `multiply` | 2–64 numeric expressions |
| `subtract` | Exactly two numeric expressions |
| `divide` | Exactly two numeric expressions; optional `scale` defaults to 12 |
| `round` | One numeric expression; optional `scale` defaults to 2 |
| `concat` | 1–64 text expressions |
| `trim`, `upper`, `lower` | One text expression |
| `coalesce` | First non-null of 1–64 expressions (empty text is a value) |
| `decimal` | One text expression; `decimal_separator` is `.` (default) or `,`; optional `thousands_separator` is `.`, `,`, space, nonbreaking space or apostrophe |
| `date` | One text expression and explicit Python `strptime` `format`; outputs ISO date |

Division and rounding use Decimal half-even rounding at the declared scale (0–12). Other
arithmetic uses bounded Decimal precision, never binary floating-point. Arithmetic input
magnitude is limited to adjusted exponents -100 through 100. Invalid formats, division by
zero and missing inputs are error issues, not generated zero values. Thousands separators
must form valid groups of three; dates must match the declared format exactly.

Example locale conversion:

```json
{"op":"decimal","args":[{"column":"c4"}],"decimal_separator":",","thousands_separator":"."}
```

### Conditions

```json
{"column":"amount","operator":"gte","value":"0","type":"decimal"}
```

Operators: `eq`, `ne`, `gt`, `gte`, `lt`, `lte`, `in`, `is_null`, `contains`. `in` uses a list
of values; `is_null` needs no value. Default type is exact text. Numeric comparison requires
`type: "decimal"`. Text equality is case-sensitive and whitespace-sensitive; explicitly
normalise using derive when that is the desired rule. Logical conditions are
`{"all":[condition,...]}`, `{"any":[condition,...]}` or `{"not":condition}`.

### Checks

Checks default to the selected output; optional `table` identifies an earlier step/source.
Each can include a stable `id` for display. Every failed or uncomputable check emits an error
issue as well as `passed: false` in the check results; independent review cannot override it.

```json
[
  {"type":"required","columns":["account","amount"]},
  {"type":"unique","columns":["account","date"]},
  {"type":"total","column":"amount","expected":"120.00","tolerance":"0.01"},
  {"type":"balance","debit":"debit","credit":"credit","tolerance":"0"}
]
```

Required rejects null and blank/whitespace text. Unique checks exact tuples, including null
values; combine it with required for mandatory keys. Totals and balance use Decimal with a
nonnegative absolute tolerance. Empty output gets a warning; checks are not a proof of
financial correctness and only test the explicitly declared conditions.

## Output schemas and templates

`export_table(table, "csv" or "xlsx", template_bytes=None, bindings=None)` returns content,
media type, filename and readback verification with a source manifest and hashes. The API
requires acceptance, successful checks and exact output-version independent approval.

Optional bindings:

```json
{
  "sheet":"Loader",
  "start_row":4,
  "header_row":3,
  "columns":{"account":"A","amount":"C"},
  "types":{"amount":"decimal"},
  "labels":{"account":"Account","amount":"Net amount"}
}
```

For a new workbook, defaults are sheet `Export`, headers at row 1, data at row 2, all columns
in table order. `columns` binds arbitrary source keys to Excel column letters and determines
CSV order too. `labels` selects headers. `types` defaults to text, with explicit `decimal`,
`integer` and ISO `date` options. Sheet and row bindings do not affect CSV.

Text is the default so leading-zero identifiers and long decimals survive intact. Explicit
XLSX numbers must fit Excel's 15 significant digits and pass exact Decimal readback. Values
are never silently rounded to fit Excel. For CSV, dangerous spreadsheet prefixes (including
whitespace before `=`, `+`, `-`, `@`) are escaped with an apostrophe and every escaped cell is
listed. This includes negative numeric values: clients that require a numeric loader should
use the typed XLSX export or explicitly handle the recorded CSV escaping. XLSX text is
written as literal strings, even when it resembles a formula. Null and empty strings both
export to empty cells; this format limitation is stated in verification.

Templates require an explicit sheet, start row and column mapping. Variable row counts are
written into available blank cells without shifting rows or silently replacing content.
Headers may reuse an equal existing header. A binding that intersects nonblank data or a
merged region is rejected. Unmapped sheet order, values, basic styles, merged ranges,
row/column layout, freeze panes and defined names are checked after readback. This is semantic
preservation, not identical ZIP bytes.

Supported templates are plain XLSX with values and styles. Macros, drawings, charts, pivots,
formulas, external links, hyperlinks, comments, structured tables, conditional formatting,
data validation and protected sheets are explicitly unsupported. They produce a clear error;
we do not discard these features and then call the output verified. Formula recalculation is
not implemented. Bind dates only to already date-formatted cells in templates, otherwise
use text or a new workbook.

Every generated file is reopened and all mapped values are compared before it is returned.
The manifest connects output row/column keys to all contributing original source locators.
A derived value does not acquire an invented PDF cell box; its source list retains the
precision supplied by the parser.

## Bounds and failure behavior

Recipes support up to 64 steps, 1,024 columns and 200,000 output rows. Expressions/conditions
have bounded depth and argument counts. Joins and melts stop before exceeding row limits.
Exports allow two million mapped cells. Templates have compressed/expanded ZIP limits and
an explicit supported package-part allowlist. Configuration errors raise `ValueError`;
input-data errors preserve unresolved values/rows and generate blocking issues. The engine
never modifies the supplied table objects or chooses a reference/accounting rule by filename.
