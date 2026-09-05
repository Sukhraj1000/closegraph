"""Explicit, deterministic table recipes. See docs/engineering/collection-recipes.md.

No expression text is executed. Numbers are Decimal strings; conversion of locale
formats requires an explicit ``decimal`` expression. Data errors produce issues and
null results; invalid recipe configuration raises ValueError. Every output cell
retains its contributing source cells in row.lineage.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from decimal import Decimal, Inexact, InvalidOperation, ROUND_DOWN, ROUND_HALF_EVEN, localcontext
import hashlib
import json
import re
from typing import Any

MAX_ROWS = 200_000
MAX_STEPS = 64
MAX_COLUMNS = 1024
_DECIMAL = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)\Z")


class DataError(ValueError):
    """A recorded input value cannot satisfy an explicit operation."""


def _number(value: Any) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise DataError("A decimal value is required")
    text = str(value)
    if len(text) > 256 or not _DECIMAL.fullmatch(text):
        raise DataError("Value is not a canonical decimal; configure explicit conversion")
    try:
        result = Decimal(text)
        if not result.is_finite() or abs(result.adjusted()) > 100:
            raise DataError("Decimal is outside the supported range")
        return result
    except InvalidOperation as exc:
        raise DataError("Invalid decimal") from exc


def _value(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        raise ValueError("Values must be text, integer or null; decimal literals use strings")
    return format(value, "f") if isinstance(value, Decimal) else str(value)


def _digest(*parts: Any) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:24]


def _keys(table: dict) -> list[str]:
    return [column["key"] for column in table["columns"]]


def _columns(table: dict, columns: Any, *, allow_empty: bool = False) -> list[str]:
    if not isinstance(columns, list) or (not columns and not allow_empty):
        raise ValueError("A nonempty column list is required")
    if any(not isinstance(c, str) for c in columns) or len(set(columns)) != len(columns) or any(c not in _keys(table) for c in columns):
        raise ValueError("Unknown or duplicate column")
    return columns


def _refs(row: dict, columns: list[str]) -> list[dict]:
    unique: dict[str, dict] = {}
    for key in columns:
        for ref in row.get("lineage", {}).get(key, []):
            unique[json.dumps(ref, sort_keys=True)] = ref
    return list(unique.values())


def _initial(table: dict) -> dict:
    result = deepcopy(table)
    if not isinstance(result.get("table_id"), str) or not result["table_id"]:
        raise ValueError("Table ID is required")
    keys = _keys(result)
    if len(keys) > MAX_COLUMNS or len(set(keys)) != len(keys):
        raise ValueError("Duplicate columns or column limit exceeded")
    if len(result["rows"]) > MAX_ROWS:
        raise ValueError("Table row limit exceeded")
    ids = set()
    for row in result["rows"]:
        if not row.get("row_id") or row["row_id"] in ids:
            raise ValueError("Missing or duplicate row ID")
        ids.add(row["row_id"])
        row.setdefault("lineage", {})
        row.setdefault("locators", {})
        for key in keys:
            row["values"][key] = _value(row["values"].get(key))
            row["lineage"].setdefault(key, [{
                "table_id": result["table_id"], "row_id": row["row_id"],
                "column_key": key, "source_id": result.get("source_id"),
                "locator": row["locators"].get(key),
            }])
    return result


def _expression_columns(expr: Any, table: dict, depth: int = 0) -> list[str]:
    if depth > 16 or not isinstance(expr, dict):
        raise ValueError("Expression must be a bounded object")
    if set(expr) == {"column"}:
        return _columns(table, [expr["column"]])
    if set(expr) == {"literal"}:
        _value(expr["literal"])
        return []
    op = expr.get("op")
    arities = {"add": (2, 64), "subtract": (2, 2), "multiply": (2, 64),
               "divide": (2, 2), "round": (1, 1), "concat": (1, 64),
               "trim": (1, 1), "upper": (1, 1), "lower": (1, 1),
               "coalesce": (1, 64), "decimal": (1, 1), "date": (1, 1)}
    allowed = {"op", "args", "scale"} if op in ("round", "divide") else {"op", "args", "decimal_separator", "thousands_separator"} if op == "decimal" else {"op", "args", "format"} if op == "date" else {"op", "args"}
    if set(expr) - allowed:
        raise ValueError("Unsupported expression fields")
    args = expr.get("args")
    if op not in arities or not isinstance(args, list) or not arities[op][0] <= len(args) <= arities[op][1]:
        raise ValueError("Unknown expression operation or invalid argument count")
    if op in ("round", "divide") and (type(expr.get("scale", 2)) is not int or not 0 <= expr.get("scale", 2) <= 12):
        raise ValueError("Rounding scale must be 0 through 12")
    if op == "date" and (not isinstance(expr.get("format"), str) or not expr["format"]):
        raise ValueError("Date conversion requires an explicit strptime format")
    if op == "decimal":
        decimal = expr.get("decimal_separator", ".")
        thousands = expr.get("thousands_separator")
        if decimal not in (".", ",") or thousands not in (None, ".", ",", " ", "\u00a0", "'") or decimal == thousands:
            raise ValueError("Invalid explicit decimal separators")
    return list(dict.fromkeys(c for arg in args for c in _expression_columns(arg, table, depth + 1)))


def _evaluate(expr: dict, row: dict) -> str | None:
    if "column" in expr:
        return row["values"].get(expr["column"])
    if "literal" in expr:
        return _value(expr["literal"])
    values = [_evaluate(arg, row) for arg in expr["args"]]
    op = expr["op"]
    if op == "coalesce":
        return next((v for v in values if v is not None), None)
    if any(v is None for v in values):
        raise DataError("Operation has a missing input value")
    if op == "concat":
        return "".join(values)
    if op in ("trim", "upper", "lower"):
        return getattr(values[0], {"trim": "strip", "upper": "upper", "lower": "lower"}[op])()
    if op == "date":
        try:
            return datetime.strptime(values[0], expr["format"]).date().isoformat()
        except ValueError as exc:
            raise DataError("Date does not match the explicit format") from exc
    if op == "decimal":
        text = values[0].strip()
        decimal = expr.get("decimal_separator", ".")
        thousands = expr.get("thousands_separator")
        sign = ""
        if text.startswith(("+", "-")):
            sign, text = text[0], text[1:]
        if text.count(decimal) > 1:
            raise DataError("Multiple decimal separators")
        parts = text.split(decimal)
        whole = parts[0]
        if thousands and thousands in whole:
            groups = whole.split(thousands)
            if not re.fullmatch(r"\d{1,3}", groups[0]) or any(not re.fullmatch(r"\d{3}", g) for g in groups[1:]):
                raise DataError("Invalid thousands grouping")
            whole = "".join(groups)
        if len(parts) == 2 and thousands and thousands in parts[1]:
            raise DataError("Thousands separator appears in fraction")
        return _value(_number(sign + whole + ("." + parts[1] if len(parts) == 2 else "")))
    numbers = [_number(v) for v in values]
    with localcontext() as context:
        context.prec = 256
        context.traps[Inexact] = op not in ("divide", "round")
        try:
            if op == "add":
                result = sum(numbers, Decimal(0))
            elif op == "subtract":
                result = numbers[0] - numbers[1]
            elif op == "multiply":
                result = Decimal(1)
                for n in numbers:
                    result *= n
            elif op == "divide":
                if numbers[1] == 0:
                    raise DataError("Division by zero")
                result = (numbers[0] / numbers[1]).quantize(Decimal(1).scaleb(-expr.get("scale", 12)), rounding=ROUND_HALF_EVEN)
            elif op == "round":
                result = numbers[0].quantize(Decimal(1).scaleb(-expr.get("scale", 2)), rounding=ROUND_HALF_EVEN)
            else:
                raise ValueError("Unsupported expression")
        except (InvalidOperation, Inexact) as exc:
            raise DataError("Decimal operation exceeds supported precision") from exc
        return _value(_number(_value(result)))


def _condition_columns(condition: Any, table: dict, depth: int = 0) -> list[str]:
    if depth > 16 or not isinstance(condition, dict):
        raise ValueError("Invalid condition")
    for logical in ("all", "any"):
        if logical in condition:
            items = condition[logical]
            if set(condition) != {logical} or not isinstance(items, list) or not 1 <= len(items) <= 64:
                raise ValueError("Logical conditions require 1 through 64 conditions")
            return list(dict.fromkeys(c for item in items for c in _condition_columns(item, table, depth + 1)))
    if "not" in condition:
        if set(condition) != {"not"}:
            raise ValueError("Invalid negated condition")
        return _condition_columns(condition["not"], table, depth + 1)
    _columns(table, [condition.get("column")])
    if condition.get("operator") not in ("eq", "ne", "gt", "gte", "lt", "lte", "in", "is_null", "contains"):
        raise ValueError("Unknown comparison operator")
    if condition.get("type", "text") not in ("text", "decimal"):
        raise ValueError("Unknown comparison type")
    if condition["operator"] == "in":
        if not isinstance(condition.get("value"), list) or len(condition["value"]) > 1000:
            raise ValueError("Membership comparison needs a bounded value list")
        for value in condition["value"]:
            _value(value)
    elif condition["operator"] != "is_null":
        _value(condition.get("value"))
    return [condition["column"]]


def _matches(condition: dict, row: dict) -> bool:
    if "all" in condition:
        return all(_matches(c, row) for c in condition["all"])
    if "any" in condition:
        return any(_matches(c, row) for c in condition["any"])
    if "not" in condition:
        return not _matches(condition["not"], row)
    value = row["values"].get(condition["column"])
    op = condition["operator"]
    if op == "is_null":
        return value is None
    expected = condition.get("value")
    convert = _number if condition.get("type", "text") == "decimal" else _value
    if op == "in":
        return value is not None and convert(value) in [convert(v) for v in expected]
    if value is None or expected is None:
        return (value == expected) if op == "eq" else (value != expected) if op == "ne" else False
    left, right = convert(value), convert(expected)
    return {"eq": lambda: left == right, "ne": lambda: left != right,
            "gt": lambda: left > right, "gte": lambda: left >= right,
            "lt": lambda: left < right, "lte": lambda: left <= right,
            "contains": lambda: str(right) in str(left)}[op]()


def _add_column(table: dict, key: str, label: str | None = None) -> None:
    if not isinstance(key, str) or not key or len(key) > 200:
        raise ValueError("Output column key must be a nonempty string up to 200 characters")
    if key not in _keys(table):
        table["columns"].append({"key": key, "label": label or key})
    if len(table["columns"]) > MAX_COLUMNS:
        raise ValueError("Column limit exceeded")


def run_recipe(tables: list[dict], recipe: dict) -> dict:
    """Execute a v1 explicit recipe; source tables and recipe are never modified."""
    if not isinstance(recipe, dict) or recipe.get("version") != 1:
        raise ValueError("Recipe version must be 1")
    steps = recipe.get("steps", [])
    if not isinstance(steps, list) or len(steps) > MAX_STEPS:
        raise ValueError("Recipe exceeds the 64 step limit")
    available = {}
    for table in tables:
        initial = _initial(table)
        if initial["table_id"] in available:
            raise ValueError("Duplicate table ID")
        available[initial["table_id"]] = initial
    issues: list[dict] = []
    summaries = []

    def issue(code: str, message: str, table_id: str, row: dict | None = None,
              column: str | None = None, *, severity: str = "error", details: dict | None = None):
        item = {"id": _digest(len(issues), code, table_id, row and row["row_id"], column),
                "severity": severity, "code": code, "message": message, "table_id": table_id}
        if row:
            item["row_id"] = row["row_id"]
        if column:
            item["column_key"] = column
        if row:
            details = {**(details or {}), "sources": _refs(row, [column] if column else list(row.get("lineage", {})))}
        if details:
            item["details"] = details
        issues.append(item)

    for step in steps:
        if not isinstance(step, dict):
            raise ValueError("Every step must be an object")
        sid, op = step.get("id"), step.get("op")
        if not isinstance(sid, str) or not sid or sid in available:
            raise ValueError("Step IDs must be unique and must not shadow input tables")
        if step.get("input") not in available:
            raise ValueError("Step input is not an available table")
        source = available[step["input"]]
        result = deepcopy(source)
        result.update(table_id=sid, title=step.get("title", sid))
        result["metadata"] = {**result.get("metadata", {}), "recipe_step": sid, "operation": op}
        before, issue_start = len(source["rows"]), len(issues)
        if op == "select":
            keys = _columns(source, step.get("columns"))
            result["columns"] = [deepcopy(next(c for c in source["columns"] if c["key"] == k)) for k in keys]
            for row in result["rows"]:
                for field in ("values", "locators", "lineage", "raw_values", "formulas"):
                    if field in row:
                        row[field] = {k: row[field].get(k) for k in keys if k in row[field]}
        elif op == "rename":
            mapping = step.get("columns")
            if not isinstance(mapping, dict) or not mapping:
                raise ValueError("Rename needs a column mapping")
            _columns(source, list(mapping))
            targets = [mapping.get(k, k) for k in _keys(source)]
            if any(not isinstance(k, str) or not k for k in targets) or len(set(targets)) != len(targets):
                raise ValueError("Rename creates duplicate or empty keys")
            for column in result["columns"]:
                column["key"] = mapping.get(column["key"], column["key"])
            for row in result["rows"]:
                for field in ("values", "locators", "lineage", "raw_values", "formulas"):
                    if field in row:
                        row[field] = {mapping.get(k, k): v for k, v in row[field].items()}
        elif op == "filter":
            condition = step.get("where")
            _condition_columns(condition, source)
            kept = []
            for row in result["rows"]:
                try:
                    if _matches(condition, row):
                        kept.append(row)
                except DataError as exc:
                    issue("invalid_filter_value", str(exc), sid, row)
                    kept.append(row)  # Unresolved rows remain inspectable and block approval.
            result["rows"] = kept
        elif op == "derive":
            mapping = step.get("columns")
            if not isinstance(mapping, dict) or not mapping:
                raise ValueError("Derive needs an expression mapping")
            dependencies = {k: _expression_columns(expr, source) for k, expr in mapping.items()}
            for key in mapping:
                _add_column(result, key)
            for row, original in zip(result["rows"], source["rows"], strict=True):
                for key, expr in mapping.items():
                    row["lineage"][key] = _refs(original, dependencies[key])
                    try:
                        row["values"][key] = _evaluate(expr, original)
                    except DataError as exc:
                        row["values"][key] = None
                        issue("invalid_expression_value", str(exc), sid, row, key)
                    row["locators"].pop(key, None)
        elif op in ("join", "lookup"):
            if step.get("right") not in available:
                raise ValueError("Join right table is not available")
            right = available[step["right"]]
            on, mapping = step.get("on"), step.get("columns")
            if not isinstance(on, list) or not on or any(not isinstance(pair, dict) for pair in on) or not isinstance(mapping, dict) or not mapping:
                raise ValueError("Join needs key pairs and right-column output mapping")
            left_keys = _columns(source, [pair.get("left") for pair in on])
            right_keys = _columns(right, [pair.get("right") for pair in on])
            _columns(right, list(mapping))
            if len(set(mapping.values())) != len(mapping) or set(mapping.values()) & set(_keys(source)):
                raise ValueError("Join output columns must be distinct and not overwrite left columns")
            how, cardinality = step.get("how", "left"), step.get("cardinality", "many_to_one")
            if how not in ("left", "inner") or cardinality not in ("many_to_one", "one_to_many"):
                raise ValueError("Unsupported join mode")
            if op == "lookup" and cardinality != "many_to_one":
                raise ValueError("Lookup requires many_to_one cardinality")
            for target in mapping.values():
                _add_column(result, target)
            index: dict[tuple, list[dict]] = {}
            for row in right["rows"]:
                key = tuple(row["values"].get(k) for k in right_keys)
                if all(v is not None and v != "" for v in key):
                    index.setdefault(key, []).append(row)
            output_rows = []
            for row in result["rows"]:
                key = tuple(row["values"].get(k) for k in left_keys)
                matches = index.get(key, [])
                if not matches:
                    issue("unmatched_join", "No exact reference match", sid, row,
                          details={"right_table": right["table_id"], "join_columns": left_keys})
                if len(matches) > 1 and cardinality == "many_to_one":
                    issue("ambiguous_join", "Multiple reference rows match; no row was selected", sid, row,
                          details={"match_count": len(matches), "right_table": right["table_id"]})
                    matches = []
                if not matches and how == "inner":
                    continue
                for match in matches or [None]:
                    output = deepcopy(row)
                    if cardinality == "one_to_many":
                        output["row_id"] = _digest(sid, row["row_id"], match and match["row_id"])
                    for source_key, target in mapping.items():
                        output["values"][target] = match["values"].get(source_key) if match else None
                        output["lineage"][target] = _refs(row, left_keys) + (_refs(match, [*right_keys, source_key]) if match else [])
                    output_rows.append(output)
                    if len(output_rows) > MAX_ROWS:
                        raise ValueError("Join exceeds output row limit")
            result["rows"] = output_rows
        elif op == "aggregate":
            group_keys = _columns(source, step.get("by", []), allow_empty=True)
            metrics = step.get("metrics")
            if not isinstance(metrics, dict) or not metrics or set(metrics) & set(group_keys):
                raise ValueError("Aggregate needs distinct named metrics")
            for metric in metrics.values():
                if not isinstance(metric, dict):
                    raise ValueError("Metric must be an object")
                if metric.get("op") not in ("sum", "count", "min", "max"):
                    raise ValueError("Unsupported aggregate operation")
                if metric["op"] != "count":
                    _columns(source, [metric.get("column")])
            groups: dict[tuple, list[dict]] = {}
            for row in source["rows"]:
                groups.setdefault(tuple(row["values"].get(k) for k in group_keys), []).append(row)
            result["columns"] = [deepcopy(c) for c in source["columns"] if c["key"] in group_keys]
            for key in metrics:
                _add_column(result, key)
            result["rows"] = []
            for group, members in groups.items():
                row = {"row_id": _digest(sid, group), "values": dict(zip(group_keys, group, strict=True)), "locators": {}, "lineage": {}}
                for key in group_keys:
                    row["lineage"][key] = [ref for member in members for ref in _refs(member, [key])]
                for key, metric in metrics.items():
                    dependencies = [metric["column"]] if metric["op"] != "count" else _keys(source)
                    row["lineage"][key] = [ref for member in members for ref in _refs(member, dependencies)]
                    try:
                        values = [_number(member["values"].get(metric["column"])) for member in members] if metric["op"] != "count" else []
                        with localcontext() as context:
                            context.prec = 256
                            context.traps[Inexact] = True
                            computed = len(members) if metric["op"] == "count" else sum(values, Decimal(0)) if metric["op"] == "sum" else min(values) if metric["op"] == "min" else max(values)
                        row["values"][key] = _value(computed)
                    except (DataError, Inexact) as exc:
                        row["values"][key] = None
                        issue("invalid_aggregate_value", str(exc), sid, row, key)
                result["rows"].append(row)
        elif op == "sort":
            order = step.get("by")
            if not isinstance(order, list) or not order:
                raise ValueError("Sort needs explicit columns")
            if any(not isinstance(entry, dict) for entry in order):
                raise ValueError("Sort entries must be objects")
            _columns(source, [entry.get("column") for entry in order])
            for entry in reversed(order):
                if entry.get("type", "text") not in ("text", "decimal") or entry.get("direction", "asc") not in ("asc", "desc"):
                    raise ValueError("Unsupported sort type or direction")
                valid, unresolved = [], []
                for row in result["rows"]:
                    try:
                        value = row["values"].get(entry["column"])
                        if value is None:
                            unresolved.append(row)
                        else:
                            valid.append((_number(value) if entry.get("type") == "decimal" else value, row))
                    except DataError as exc:
                        issue("invalid_sort_value", str(exc), sid, row, entry["column"])
                        unresolved.append(row)
                result["rows"] = [row for _, row in sorted(valid, key=lambda item: item[0], reverse=entry.get("direction") == "desc")] + unresolved
        elif op == "classify":
            key, rules = step.get("column"), step.get("rules")
            _add_column(result, key)
            if not isinstance(rules, list) or not 1 <= len(rules) <= 100:
                raise ValueError("Classify requires 1 through 100 explicit rules")
            if any(not isinstance(rule, dict) for rule in rules):
                raise ValueError("Classification rules must be objects")
            dependencies = list(dict.fromkeys(c for rule in rules for c in _condition_columns(rule.get("when"), source)))
            for rule in rules:
                _value(rule.get("value"))
            default = _value(step.get("default"))
            for row in result["rows"]:
                row["lineage"][key] = _refs(row, dependencies)
                try:
                    matches = [rule for rule in rules if _matches(rule["when"], row)]
                    row["values"][key] = _value(matches[0]["value"]) if len(matches) == 1 else default if not matches else None
                    if len(matches) > 1:
                        issue("ambiguous_classification", "Multiple classification rules match", sid, row, key)
                    elif not matches and "default" not in step:
                        issue("unmatched_classification", "No classification rule matches", sid, row, key)
                except DataError as exc:
                    row["values"][key] = None
                    issue("invalid_classification_value", str(exc), sid, row, key)
                row["locators"].pop(key, None)
        elif op == "allocate":
            group_keys = _columns(source, step.get("by", []), allow_empty=True)
            weight, target, scale = step.get("weight"), step.get("column"), step.get("scale", 2)
            _columns(source, [weight])
            if type(scale) is not int or not 0 <= scale <= 12:
                raise ValueError("Allocation scale must be 0 through 12")
            dependencies = _expression_columns(step.get("total"), source)
            _add_column(result, target)
            groups = {}
            for row in result["rows"]:
                groups.setdefault(tuple(row["values"].get(k) for k in group_keys), []).append(row)
            for members in groups.values():
                refs = [ref for member in members for ref in _refs(member, [*group_keys, weight, *dependencies])]
                for row in members:
                    row["lineage"][target] = refs
                try:
                    totals = [_number(_evaluate(step["total"], row)) for row in members]
                    if any(total != totals[0] for total in totals):
                        raise DataError("Allocation total differs within a group")
                    weights = [_number(row["values"].get(weight)) for row in members]
                    if any(w < 0 for w in weights) or sum(weights) <= 0:
                        raise DataError("Allocation weights must be nonnegative with a positive sum")
                    with localcontext() as context:
                        context.prec = 256
                        quantum = Decimal(1).scaleb(-scale)
                        total = totals[0]
                        if total.quantize(quantum) != total:
                            raise DataError("Allocation total has more precision than the configured scale")
                        exact = [abs(total) * w / sum(weights) for w in weights]
                        amounts = [amount.quantize(quantum, rounding=ROUND_DOWN) for amount in exact]
                        remaining = int((abs(total) - sum(amounts)) / quantum)
                        priority = sorted(range(len(members)), key=lambda i: (-(exact[i] - amounts[i]), members[i]["row_id"]))
                        for i in priority[:remaining]:
                            amounts[i] += quantum
                        for row, amount in zip(members, amounts, strict=True):
                            row["values"][target] = _value(amount if total >= 0 else -amount)
                except (DataError, InvalidOperation) as exc:
                    for row in members:
                        row["values"][target] = None
                    issue("invalid_allocation", str(exc), sid, members[0], target)
                for row in members:
                    row["lineage"][target] = refs
                    row["locators"].pop(target, None)
        elif op == "reshape":
            mode = step.get("mode")
            if mode == "melt":
                identity = _columns(source, step.get("id_columns", []), allow_empty=True)
                values = _columns(source, step.get("value_columns"))
                variable, value_key = step.get("variable_column", "variable"), step.get("value_column", "value")
                if variable == value_key or variable in identity or value_key in identity or set(identity) & set(values):
                    raise ValueError("Melt columns must be distinct")
                result["columns"] = [deepcopy(c) for c in source["columns"] if c["key"] in identity]
                _add_column(result, variable)
                _add_column(result, value_key)
                if len(source["rows"]) * len(values) > MAX_ROWS:
                    raise ValueError("Melt exceeds output row limit")
                result["rows"] = []
                for row in source["rows"]:
                    for key in values:
                        result["rows"].append({"row_id": _digest(sid, row["row_id"], key),
                            "values": {**{k: row["values"].get(k) for k in identity}, variable: key, value_key: row["values"].get(key)},
                            "locators": {}, "lineage": {**{k: _refs(row, [k]) for k in identity}, variable: _refs(row, [key]), value_key: _refs(row, [key])}})
            elif mode == "pivot":
                identity = _columns(source, step.get("id_columns", []), allow_empty=True)
                variable, value_key, mapping = step.get("variable_column"), step.get("value_column"), step.get("columns")
                _columns(source, [variable, value_key])
                if not isinstance(mapping, dict) or not mapping or len(set(mapping.values())) != len(mapping) or set(mapping.values()) & set(identity):
                    raise ValueError("Pivot needs an explicit distinct value-to-column mapping")
                result["columns"] = [deepcopy(c) for c in source["columns"] if c["key"] in identity]
                for key in mapping.values():
                    _add_column(result, key)
                groups = {}
                seen = set()
                for member in source["rows"]:
                    group = tuple(member["values"].get(k) for k in identity)
                    if group not in groups:
                        groups[group] = {"row_id": _digest(sid, group), "values": {**dict(zip(identity, group, strict=True)), **{k: None for k in mapping.values()}}, "locators": {}, "lineage": {k: _refs(member, [k]) for k in identity}}
                    row = groups[group]
                    key = mapping.get(member["values"].get(variable))
                    if key is None:
                        issue("unmapped_pivot_value", "Pivot category has no explicit output binding", sid, member, variable)
                        continue
                    if (group, key) in seen:
                        issue("ambiguous_pivot", "More than one value maps to the same output cell", sid, row, key)
                        row["values"][key] = None
                    else:
                        row["values"][key] = member["values"].get(value_key)
                    seen.add((group, key))
                    row["lineage"].setdefault(key, []).extend(_refs(member, [variable, value_key]))
                result["rows"] = list(groups.values())
            else:
                raise ValueError("Reshape mode must be melt or pivot")
        else:
            raise ValueError(f"Unsupported recipe operation: {op}")
        available[sid] = result
        summaries.append({"id": sid, "operation": op, "input_rows": before,
                          "output_rows": len(result["rows"]), "issues": len(issues) - issue_start,
                          "excluded_rows": max(0, before - len(result["rows"]))})
    output_id = recipe.get("output")
    if output_id not in available:
        raise ValueError("Recipe output must name an available table or step")
    output = available[output_id]
    checks = recipe.get("checks", [])
    if not isinstance(checks, list) or len(checks) > 100:
        raise ValueError("Checks must be a list of at most 100 items")
    check_results = []
    for index, check in enumerate(checks):
        if not isinstance(check, dict) or check.get("table", output_id) not in available:
            raise ValueError("Invalid check table")
        table = available[check.get("table", output_id)]
        kind, start = check.get("type"), len(issues)
        if kind in ("required", "unique"):
            keys = _columns(table, check.get("columns"))
            seen = set()
            for row in table["rows"]:
                values = tuple(row["values"].get(k) for k in keys)
                if kind == "required":
                    for key, value in zip(keys, values, strict=True):
                        if value is None or value.strip() == "":
                            issue("required_value", "A required value is missing", table["table_id"], row, key)
                else:
                    if values in seen:
                        issue("duplicate_key", "Duplicate key in the declared uniqueness check", table["table_id"], row, details={"columns": keys})
                    seen.add(values)
        elif kind in ("total", "balance"):
            keys = _columns(table, [check.get("column")] if kind == "total" else [check.get("debit"), check.get("credit")])
            tolerance = _number(check.get("tolerance", "0"))
            if tolerance < 0:
                raise ValueError("Check tolerance must not be negative")
            try:
                with localcontext() as context:
                    context.prec = 256
                    context.traps[Inexact] = True
                    sums = [sum((_number(row["values"].get(key)) for row in table["rows"]), Decimal(0)) for key in keys]
                    expected = _number(check.get("expected")) if kind == "total" else sums[1]
                    if abs(sums[0] - expected) > tolerance:
                        issue("total_mismatch" if kind == "total" else "unbalanced_values", "Computed totals fail the explicit reconciliation", table["table_id"], details={"actual": str(sums[0]), "expected": str(expected), "tolerance": str(tolerance)})
            except (DataError, Inexact) as exc:
                issue("invalid_check_value", str(exc), table["table_id"])
        else:
            raise ValueError("Unsupported check type")
        check_results.append({"id": check.get("id", f"check-{index + 1}"), "type": kind,
                              "table_id": table["table_id"], "passed": len(issues) == start})
    if not output["rows"]:
        issue("empty_output", "The recipe produced no output rows", output_id, severity="warning")
    lineage = [{"table_id": output_id, "row_id": row["row_id"], "columns": row["lineage"]} for row in output["rows"]]
    return {"tables": [output], "issues": issues, "steps": summaries, "lineage": lineage, "checks": check_results}
