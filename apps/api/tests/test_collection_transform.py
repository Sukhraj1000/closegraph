"""Synthetic contract tests for general, deterministic recipes (no provider calls)."""
from copy import deepcopy
from decimal import Decimal

import pytest

from closegraph.collections.transform import run_recipe


def table(name, columns, rows):
    return {"table_id": name, "source_id": "source-" + name, "title": name,
            "columns": [{"key": key, "label": key} for key in columns],
            "rows": [{"row_id": f"{name}-{index}", "values": dict(zip(columns, values, strict=True)),
                      "locators": {key: {"kind": "csv", "row": index + 2, "column": col + 1}
                                   for col, key in enumerate(columns)}}
                     for index, values in enumerate(rows)]}


def recipe(steps, checks=None, output=None):
    return {"version": 1, "steps": steps, "output": output or steps[-1]["id"], "checks": checks or []}


def values(result):
    return [row["values"] for row in result["tables"][0]["rows"]]


def test_decimal_calculation_mapping_filter_sort_and_lineage_are_reproducible():
    source = table("unfamiliar-sheet", ["id", "net", "tax"], [["002", "0.1", "0.2"], ["001", "9.99", "0.01"]])
    original = deepcopy(source)
    spec = recipe([
        {"id": "amounts", "op": "derive", "input": source["table_id"], "columns": {"gross": {"op": "add", "args": [{"column": "net"}, {"column": "tax"}]}}},
        {"id": "filtered", "op": "filter", "input": "amounts", "where": {"column": "gross", "operator": "gt", "value": "0", "type": "decimal"}},
        {"id": "ordered", "op": "sort", "input": "filtered", "by": [{"column": "id"}]},
        {"id": "named", "op": "rename", "input": "ordered", "columns": {"id": "account"}},
        {"id": "final", "op": "select", "input": "named", "columns": ["account", "gross"]},
    ], [{"type": "total", "column": "gross", "expected": "10.30"}])
    result = run_recipe([source], spec)
    assert values(result) == [{"account": "001", "gross": "10.00"}, {"account": "002", "gross": "0.3"}]
    assert result["issues"] == []
    assert result == run_recipe([source], spec)
    assert source == original
    assert len(result["tables"]) == 1
    refs = result["tables"][0]["rows"][0]["lineage"]["gross"]
    assert {ref["column_key"] for ref in refs} == {"net", "tax"}
    assert {ref["locator"]["row"] for ref in refs} == {3}


def test_explicit_locale_conversion_and_dates_do_not_guess():
    source = table("input", ["money", "date"], [["1.234,56", "31/12/2025"], ["12.34,56", "12/31/2025"]])
    result = run_recipe([source], recipe([{"id": "converted", "op": "derive", "input": "input", "columns": {
        "number": {"op": "decimal", "args": [{"column": "money"}], "decimal_separator": ",", "thousands_separator": "."},
        "date_iso": {"op": "date", "args": [{"column": "date"}], "format": "%d/%m/%Y"},
    }}]))
    assert values(result)[0]["number"] == "1234.56"
    assert values(result)[0]["date_iso"] == "2025-12-31"
    assert values(result)[1]["number"] is None
    assert values(result)[1]["date_iso"] is None
    assert len(result["issues"]) == 2
    assert all(issue["severity"] == "error" for issue in result["issues"])


def test_division_and_rounding_scale_are_explicit_and_decimal():
    source = table("input", ["value"], [["1"], ["2.345"], ["2.355"]])
    result = run_recipe([source], recipe([{"id": "out", "op": "derive", "input": "input", "columns": {
        "third": {"op": "divide", "args": [{"column": "value"}, {"literal": "3"}], "scale": 4},
        "rounded": {"op": "round", "args": [{"column": "value"}], "scale": 2},
    }}]))
    assert values(result)[0]["third"] == "0.3333"
    assert values(result)[1]["rounded"] == "2.34"
    assert values(result)[2]["rounded"] == "2.36"


@pytest.mark.parametrize("bad", [None, "NaN", "Infinity", "1,000", "garbage", "1e4"])
def test_invalid_numeric_inputs_remain_null_and_block(bad):
    source = table("input", ["value"], [[bad]])
    result = run_recipe([source], recipe([{"id": "out", "op": "derive", "input": "input", "columns": {"computed": {"op": "add", "args": [{"column": "value"}, {"literal": "1"}]}}}]))
    assert values(result)[0]["computed"] is None
    assert result["issues"][0]["severity"] == "error"
    assert result["issues"][0]["details"]["sources"][0]["locator"]["row"] == 2


def test_division_by_zero_is_a_diagnostic_not_an_exception():
    result = run_recipe([table("input", ["a"], [["1"]])], recipe([{"id": "out", "op": "derive", "input": "input", "columns": {"x": {"op": "divide", "args": [{"column": "a"}, {"literal": "0"}]}}}]))
    assert values(result)[0]["x"] is None
    assert "zero" in result["issues"][0]["message"]


def test_join_unmatched_and_ambiguous_values_are_not_silently_chosen():
    left = table("transactions", ["code", "amount"], [["A", "10"], ["B", "20"], ["Z", "30"]])
    right = table("reference", ["key", "account"], [["A", "001"], ["B", "002"], ["B", "003"]])
    step = {"id": "joined", "op": "lookup", "input": "transactions", "right": "reference", "on": [{"left": "code", "right": "key"}], "columns": {"account": "mapped_account"}}
    result = run_recipe([left, right], recipe([step]))
    assert [row["mapped_account"] for row in values(result)] == ["001", None, None]
    assert {issue["code"] for issue in result["issues"]} == {"ambiguous_join", "unmatched_join"}
    assert {ref["table_id"] for ref in result["tables"][0]["rows"][0]["lineage"]["mapped_account"]} == {"transactions", "reference"}


def test_one_to_many_join_is_only_available_when_explicit_and_keeps_unique_row_ids():
    left = table("left", ["code"], [["A"]])
    right = table("right", ["key", "name"], [["A", "first"], ["A", "second"]])
    result = run_recipe([left, right], recipe([{"id": "out", "op": "join", "input": "left", "right": "right", "on": [{"left": "code", "right": "key"}], "columns": {"name": "name"}, "cardinality": "one_to_many"}]))
    assert len(values(result)) == 2
    assert len({row["row_id"] for row in result["tables"][0]["rows"]}) == 2
    assert not result["issues"]


def test_blank_keys_do_not_join_to_each_other():
    result = run_recipe([table("l", ["key"], [[""]]), table("r", ["key", "v"], [["", "incorrect"]])], recipe([{"id": "out", "op": "lookup", "input": "l", "right": "r", "on": [{"left": "key", "right": "key"}], "columns": {"v": "v"}}]))
    assert values(result)[0]["v"] is None
    assert result["issues"][0]["code"] == "unmatched_join"


def test_aggregate_maintains_group_sources_and_reports_invalid_group():
    source = table("input", ["group", "amount"], [["A", "0.1"], ["A", "0.2"], ["B", "bad"]])
    result = run_recipe([source], recipe([{"id": "out", "op": "aggregate", "input": "input", "by": ["group"], "metrics": {"total": {"op": "sum", "column": "amount"}, "count": {"op": "count"}}}]))
    assert values(result) == [{"group": "A", "total": "0.3", "count": "2"}, {"group": "B", "total": None, "count": "1"}]
    assert len(result["tables"][0]["rows"][0]["lineage"]["total"]) == 2
    assert result["issues"][0]["code"] == "invalid_aggregate_value"


def test_classify_detects_overlapping_rules_instead_of_first_match():
    source = table("input", ["value"], [["5"], ["20"], ["-1"]])
    result = run_recipe([source], recipe([{"id": "out", "op": "classify", "input": "input", "column": "category", "rules": [
        {"when": {"column": "value", "operator": "gt", "type": "decimal", "value": "0"}, "value": "positive"},
        {"when": {"column": "value", "operator": "gt", "type": "decimal", "value": "10"}, "value": "large"},
    ], "default": "other"}]))
    assert [row["category"] for row in values(result)] == ["positive", None, "other"]
    assert result["issues"][0]["code"] == "ambiguous_classification"


@pytest.mark.parametrize("total", ["10.00", "-10.00", "0.00"])
def test_allocation_conserves_total_and_is_stable_for_equal_remainders(total):
    source = table("input", ["fund", "weight"], [["X", "1"], ["X", "1"], ["X", "1"]])
    spec = recipe([{"id": "out", "op": "allocate", "input": "input", "by": ["fund"], "weight": "weight", "total": {"literal": total}, "column": "share", "scale": 2}])
    result = run_recipe([source], spec)
    assert sum(Decimal(row["share"]) for row in values(result)) == Decimal(total)
    assert not result["issues"]
    assert result == run_recipe([source], spec)
    assert len(result["tables"][0]["rows"][0]["lineage"]["share"]) == 6


@pytest.mark.parametrize("weights,total", [(["0", "0"], "1"), (["-1", "2"], "1"), (["1", "1"], "1.001")])
def test_invalid_allocation_does_not_invent_amounts(weights, total):
    source = table("input", ["weight"], [[weight] for weight in weights])
    result = run_recipe([source], recipe([{"id": "out", "op": "allocate", "input": "input", "weight": "weight", "total": {"literal": total}, "column": "share"}]))
    assert all(row["share"] is None for row in values(result))
    assert result["issues"][0]["code"] == "invalid_allocation"


def test_melt_and_pivot_support_unseen_columns_without_losing_lineage():
    source = table("input", ["id", "new_metric", "another_metric"], [["A", "12", "13"], ["B", "1", "2"]])
    result = run_recipe([source], recipe([
        {"id": "long", "op": "reshape", "input": "input", "mode": "melt", "id_columns": ["id"], "value_columns": ["new_metric", "another_metric"]},
        {"id": "wide", "op": "reshape", "input": "long", "mode": "pivot", "id_columns": ["id"], "variable_column": "variable", "value_column": "value", "columns": {"new_metric": "first", "another_metric": "second"}},
    ]))
    assert values(result) == [{"id": "A", "first": "12", "second": "13"}, {"id": "B", "first": "1", "second": "2"}]
    assert not result["issues"]
    assert result["tables"][0]["rows"][0]["lineage"]["first"][0]["column_key"] == "new_metric"


def test_duplicate_pivot_cells_block_without_summing():
    source = table("input", ["id", "key", "value"], [["A", "X", "1"], ["A", "X", "2"], ["A", "other", "3"]])
    result = run_recipe([source], recipe([{"id": "out", "op": "reshape", "input": "input", "mode": "pivot", "id_columns": ["id"], "variable_column": "key", "value_column": "value", "columns": {"X": "X"}}]))
    assert values(result)[0]["X"] is None
    assert {issue["code"] for issue in result["issues"]} == {"ambiguous_pivot", "unmapped_pivot_value"}


def test_failed_checks_are_error_issues_and_do_not_change_input_values():
    source = table("input", ["id", "debit", "credit"], [["A", "1", "0"], ["A", "2", "0"], ["", "0", "0"]])
    result = run_recipe([source], recipe([], [
        {"type": "required", "columns": ["id"]}, {"type": "unique", "columns": ["id"]},
        {"type": "balance", "debit": "debit", "credit": "credit"},
        {"type": "total", "column": "debit", "expected": "100"},
    ], "input"))
    assert {issue["code"] for issue in result["issues"]} == {"required_value", "duplicate_key", "unbalanced_values", "total_mismatch"}
    assert all(issue["severity"] == "error" for issue in result["issues"])
    assert all(not check["passed"] for check in result["checks"])
    assert values(result) == [row["values"] for row in source["rows"]]


def test_invalid_filter_value_is_kept_visible_and_error_blocks():
    result = run_recipe([table("input", ["v"], [["bad"], ["-1"], ["2"]])], recipe([{"id": "out", "op": "filter", "input": "input", "where": {"column": "v", "operator": "gt", "value": "0", "type": "decimal"}}]))
    assert values(result) == [{"v": "bad"}, {"v": "2"}]
    assert result["steps"][0]["excluded_rows"] == 1
    assert result["issues"][0]["severity"] == "error"


@pytest.mark.parametrize("step", [
    {"id": "out", "op": "python", "input": "input", "code": "open('/tmp/not-allowed','w')"},
    {"id": "input", "op": "select", "input": "input", "columns": ["v"]},
    {"id": "out", "op": "select", "input": "input", "columns": ["unknown"]},
    {"id": "out", "op": "derive", "input": "input", "columns": {"x": "__import__('os')"}},
    {"id": "out", "op": "derive", "input": "input", "columns": {"x": {"op": "trim", "column": "v", "args": [{"column": "v"}]}}},
])
def test_invalid_or_executable_recipe_configuration_is_rejected(step):
    with pytest.raises(ValueError):
        run_recipe([table("input", ["v"], [["1"]])], recipe([step]))
