"""Pure evidence requirements, deterministic checks, follow-up tasks and inbox events.

Public contracts:
  evaluate_requirements(state, load_table, now) -> list[Evaluation]
  sync_tasks(state, evaluations, now) -> state (mutates tasks/notifications only)
  tick_deadlines(state, now) -> state (no reevaluation/status rewrites)
  sync_processing_error(state, error, now) -> task | None
  create_manual_flag(state, flag, actor_id, now) -> task
  apply_task_action(state, task_id, action, actor_id, now, *, note='', document_ids=None)

Root services own scoped authorization, immutable snapshots, version checks and
transactions. These helpers never send messages, access a database or call a model.
Requirements are state.requirements (list), with state.requirements_version.
Document references are logical documents; current_revision_id selects source.id.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal, Inexact, InvalidOperation, ROUND_HALF_EVEN, localcontext
from hashlib import sha256
import json
import re
from typing import Any, Callable

PARTIES = {"account_manager", "accountant", "fund_manager", "investor"}
KINDS = {"evidence", "required_fields", "unique", "total", "bank_balance", "fee"}
OUTCOMES = {"PASS", "MISSING_EVIDENCE", "NEEDS_REVIEW", "FAIL", "ERROR"}
_DECIMAL = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?\Z")


class PendingEvidence(ValueError):
    def __init__(self, status: str, message: str):
        self.status = status
        super().__init__(message)


def _time(value: datetime | str) -> datetime:
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("Use an explicit timezone-aware timestamp")
    return value.astimezone(timezone.utc)


def _stamp(value: datetime | str) -> str:
    return _time(value).isoformat()


def _hash(value: Any) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _decimal(value: Any) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        raise ValueError("A decimal string is required; missing amounts are not zero")
    text = str(value)
    if len(text) > 256 or not _DECIMAL.fullmatch(text):
        raise ValueError("Invalid explicit decimal value")
    result = Decimal(text)
    if not result.is_finite() or abs(result.adjusted()) > 100:
        raise ValueError("Decimal exceeds the supported range")
    return result


def _number(value: Decimal | int) -> str:
    return format(value, "f")


def _documents(state: dict) -> dict[str, dict]:
    return {doc["id"]: doc for doc in state.get("documents", [])}


def _members(state: dict, party: str | None = None) -> list[dict]:
    return [member for member in state.get("members", state.get("memberships", []))
            if member.get("actor_id") and (party is None or member.get("party") == party)
            and member.get("active", True)]


def _refs(table: dict, rows: list[dict], columns: list[str]) -> list[dict]:
    unique = {}
    for row in rows:
        for key in columns:
            refs = row.get("lineage", {}).get(key)
            if refs is None:
                refs = [{"table_id": table["table_id"], "row_id": row["row_id"],
                         "column_key": key, "source_id": table.get("source_id"),
                         "locator": row.get("locators", {}).get(key)}]
            for reference in refs:
                unique[_hash(reference)] = reference
    return list(unique.values())


def _column_keys(table: dict, keys: Any, *, allow_empty: bool = False) -> list[str]:
    available = {column["key"] for column in table["columns"]}
    if (not isinstance(keys, list) or (not keys and not allow_empty)
            or any(not isinstance(key, str) or key not in available for key in keys)
            or len(set(keys)) != len(keys)):
        raise ValueError("A check refers to unknown, duplicate or missing columns")
    return keys


def validate_requirements(requirements: Any) -> list[dict]:
    """Structural validation for service writes; semantic errors remain evaluations."""
    if not isinstance(requirements, list) or len(requirements) > 100:
        raise ValueError("Requirements must be a list of at most 100 items")
    seen = set()
    for requirement in requirements:
        if not isinstance(requirement, dict):
            raise ValueError("Every requirement must be an object")
        identity = requirement.get("id")
        if not isinstance(identity, str) or not identity or len(identity) > 128 or identity in seen:
            raise ValueError("Requirements need distinct nonempty IDs")
        seen.add(identity)
        if requirement.get("kind") not in KINDS:
            raise ValueError("Unsupported requirement kind")
        if not isinstance(requirement.get("title"), str) or not requirement["title"].strip():
            raise ValueError("Requirement title is required")
        if type(requirement.get("blocking", True)) is not bool:
            raise ValueError("blocking must be a boolean")
        if requirement.get("owner_party", "account_manager") not in PARTIES:
            raise ValueError("Unknown owner party")
        document_ids = requirement.get("document_ids", [])
        if (not isinstance(document_ids, list) or len(document_ids) > 100
                or any(not isinstance(identity, str) or not identity for identity in document_ids)
                or len(set(document_ids)) != len(document_ids)):
            raise ValueError("document_ids must contain distinct logical document IDs")
        if requirement.get("period") is not None and (not isinstance(requirement["period"], str) or not requirement["period"].strip()):
            raise ValueError("Period must be an explicit nonempty string")
        for field in ("freshness_days", "escalate_after_days"):
            if requirement.get(field) is not None and (type(requirement[field]) is not int or not 0 <= requirement[field] <= 3650):
                raise ValueError(field + " must be 0 through 3650 days")
        if requirement.get("due_at"):
            _time(requirement["due_at"])
        if not isinstance(requirement.get("parameters", {}), dict):
            raise ValueError("Requirement parameters must be an object")
    return deepcopy(requirements)


def _resolve_inputs(state: dict, requirement: dict, result: dict, now: datetime) -> tuple[list[dict], list[dict]]:
    documents = _documents(state)
    sources = {source["id"]: source for source in state.get("sources", [])}
    declared = requirement.get("document_ids", [])
    minimum = requirement.get("parameters", {}).get("minimum_documents", 1)
    if type(minimum) is not int or not 1 <= minimum <= 100:
        raise ValueError("minimum_documents must be 1 through 100")
    if len(declared) < minimum:
        raise PendingEvidence("MISSING_EVIDENCE", "The required logical documents have not been attached")
    resolved = []
    datasets = []
    pending = []
    for identity in declared:
        document = documents.get(identity)
        if not document or not document.get("current_revision_id"):
            pending.append(("MISSING_EVIDENCE", "A required logical document has no current revision"))
            result["inputs"].append({"document_id": identity, "source_id": None})
            continue
        source = sources.get(document["current_revision_id"])
        if not source:
            pending.append(("MISSING_EVIDENCE", "Current document revision is unavailable"))
            result["inputs"].append({"document_id": identity, "source_id": document["current_revision_id"]})
            continue
        descriptor = {"document_id": identity, "source_id": source["id"],
                      "source_hash": source.get("content_hash"), "period": source.get("period", document.get("period")),
                      "source_version": source.get("version", source.get("revision", 1))}
        result["inputs"].append(descriptor)
        resolved.append(source)
        current_datasets = [d for d in state.get("datasets", [])
                            if d.get("source_id") == source["id"] and d.get("kind", "extraction") == "extraction"]
        for dataset in current_datasets:
            datasets.append(dataset)
            result["inputs"].append({**descriptor, "dataset_id": dataset["id"],
                                     "dataset_version": dataset.get("version"), "data_hash": dataset.get("data_hash"),
                                     "accepted_hash": dataset.get("accepted_hash")})
        if not source.get("content_hash"):
            pending.append(("MISSING_EVIDENCE", "Document content identity is missing"))
        if requirement.get("period") is not None and descriptor["period"] != requirement["period"]:
            pending.append(("NEEDS_REVIEW", "Document period does not match the explicitly required period"))
        if requirement.get("freshness_days") is not None:
            raw_as_of = source.get("as_of", document.get("as_of"))
            if not raw_as_of:
                pending.append(("NEEDS_REVIEW", "Freshness requires an explicit document as-of date"))
            else:
                try:
                    as_of = datetime.fromisoformat(raw_as_of.replace("Z", "+00:00"))
                    if as_of.tzinfo is None and len(raw_as_of) == 10:
                        as_of = as_of.replace(tzinfo=timezone.utc)
                    as_of = _time(as_of)
                    if as_of.date() > now.date():
                        pending.append(("NEEDS_REVIEW", "Document has a future as-of date"))
                    elif now.date() - as_of.date() > timedelta(days=requirement["freshness_days"]):
                        pending.append(("MISSING_EVIDENCE", "Document is stale; provide evidence within the required freshness window"))
                except (ValueError, AttributeError):
                    pending.append(("NEEDS_REVIEW", "Document as-of date is invalid"))
        if source.get("status") in ("FAILED", "ERROR"):
            pending.append(("ERROR", "Required source processing failed"))
        elif source.get("status") != "EXTRACTED":
            pending.append(("NEEDS_REVIEW", "Required source processing has not completed"))
        if not current_datasets:
            pending.append(("MISSING_EVIDENCE", "Required source has no reviewable extraction dataset"))
        elif any(not d.get("accepted") or not d.get("data_hash") or d.get("accepted_hash") != d["data_hash"] for d in current_datasets):
            pending.append(("NEEDS_REVIEW", "Accept the exact current extraction dataset versions"))
        coverage = source.get("coverage", {})
        is_pdf = source.get("media_type") == "application/pdf"
        if is_pdf:
            if not (source.get("completeness_verified") is True
                    and source.get("completeness_verified_hash") == source.get("content_hash")):
                pending.append(("NEEDS_REVIEW", "PDF completeness needs explicit verification bound to these source bytes"))
        elif coverage.get("complete") is not True:
            pending.append(("MISSING_EVIDENCE", "Native extraction does not establish complete source coverage"))
        source_issues = [*source.get("issues", []), *[issue for issue in state.get("issues", []) if issue.get("source_id") == source["id"]]]
        if any(issue.get("severity") == "error" and not issue.get("resolved") for issue in source_issues):
            pending.append(("NEEDS_REVIEW", "Required source has unresolved extraction issues"))
    if pending:
        priority = {"ERROR": 0, "MISSING_EVIDENCE": 1, "NEEDS_REVIEW": 2}
        status = min(pending, key=lambda item: priority[item[0]])[0]
        messages = list(dict.fromkeys(message for _, message in pending))
        result["findings"] = [{"status": outcome, "message": message} for outcome, message in pending]
        raise PendingEvidence(status, "; ".join(messages))
    return resolved, datasets


def _selected_dataset(state: dict, requirement: dict, candidates: list[dict]) -> dict:
    selector = requirement.get("dataset_selector")
    if selector is not None:
        if not isinstance(selector, dict) or set(selector) != {"document_id", "table_title"}:
            raise ValueError("dataset_selector needs document_id and table_title")
        document_id, title = selector["document_id"], selector["table_title"]
        if document_id not in requirement.get("document_ids", []):
            raise ValueError("Selected dataset document must be required explicitly")
        source_id = _documents(state)[document_id]["current_revision_id"]
        selected = [d for d in candidates if d.get("source_id") == source_id and d.get("title") == title]
    elif requirement.get("table_title"):
        if len(requirement.get("document_ids", [])) != 1:
            raise ValueError("table_title requires exactly one logical document")
        selected = [d for d in candidates if d.get("title") == requirement["table_title"]]
    elif requirement.get("dataset_id"):
        selected = [d for d in candidates if d["id"] == requirement["dataset_id"]]
    else:
        raise PendingEvidence("NEEDS_REVIEW", "Select the exact source table for this requirement")
    if len(selected) != 1:
        raise PendingEvidence("NEEDS_REVIEW", "The table selector is missing, ambiguous or stale after a document revision")
    return selected[0]


def _numeric_values(table: dict, rows: list[dict], column: str) -> list[Decimal]:
    _column_keys(table, [column])
    if any(row["values"].get(column) in (None, "") for row in rows):
        raise PendingEvidence("MISSING_EVIDENCE", "A required numeric operand is missing")
    return [_decimal(row["values"][column]) for row in rows]


def _check_context(table: dict, rows: list[dict], parameters: dict, result: dict) -> None:
    result["operands"]["context"] = {}
    for field in ("currency", "entity"):
        column, expected = parameters.get(field + "_column"), parameters.get(field)
        if column is None and expected is None:
            result["operands"]["context"][field] = {"checked": False}
            continue
        if not column or not isinstance(expected, str) or not expected:
            raise ValueError(field + " requires both a column and an explicit expected value")
        _column_keys(table, [column])
        observed = sorted({str(row["values"].get(column)) for row in rows})
        result["operands"]["context"][field] = {"checked": True, "column": column, "expected": expected, "observed": observed}
        result["citations"].extend(_refs(table, rows, [column]))
        if any(row["values"].get(column) != expected for row in rows):
            raise PendingEvidence("NEEDS_REVIEW", "Rows do not share the explicitly required " + field)


def _calculate(state: dict, requirement: dict, table: dict, result: dict) -> None:
    rows = [row for row in table["rows"] if not row.get("excluded")]
    parameters = requirement.get("parameters", {})
    kind = requirement["kind"]
    result["operands"] = {"row_count": len(rows)}
    if not rows:
        raise PendingEvidence("MISSING_EVIDENCE", "No included rows are available for the required check")
    if kind in ("required_fields", "unique"):
        columns = _column_keys(table, parameters.get("columns"))
        seen = {}
        failures = []
        for row in rows:
            values = tuple(row["values"].get(column) for column in columns)
            if kind == "required_fields":
                for column, value in zip(columns, values, strict=True):
                    if value is None or not str(value).strip():
                        failures.append({"row_id": row["row_id"], "column_key": column})
            else:
                if values in seen:
                    failures.append({"row_id": row["row_id"], "duplicate_of": seen[values], "columns": columns})
                else:
                    seen[values] = row["row_id"]
        result["citations"] = _refs(table, rows, columns)
        result.update(expected="0", actual=str(len(failures)), difference=str(len(failures)),
                      status="FAIL" if failures else "PASS", message="Required data check failed" if failures else "Declared data check passed")
        result["operands"].update(columns=columns, failures=failures)
        return
    _check_context(table, rows, parameters, result)
    tolerance = _decimal(parameters.get("tolerance", "0"))
    if tolerance < 0:
        raise ValueError("Tolerance cannot be negative")
    result["operands"]["tolerance"] = _number(tolerance)
    with localcontext() as context:
        context.prec = 256
        context.traps[Inexact] = True
        if kind == "total":
            column = parameters.get("column")
            _column_keys(table, [column])
            result["citations"].extend(_refs(table, rows, [column]))
            values = _numeric_values(table, rows, column)
            expected, actual = _decimal(parameters.get("expected")), sum(values, Decimal(0))
            result["operands"].update(column=column, values=[_number(v) for v in values], expected_origin="requirements configuration")
            result["citations"].extend(_refs(table, rows, [column]))
        elif kind == "bank_balance":
            debit_column, credit_column = parameters.get("debit_column"), parameters.get("credit_column")
            if debit_column == credit_column:
                raise ValueError("Debit and credit columns must be distinct")
            debit_sign = parameters.get("debit_sign")
            if debit_sign not in ("positive", "negative"):
                raise ValueError("Bank balance requires an explicit debit_sign convention")
            # A bank may leave its unused side empty. Treat that side as zero only
            # under the explicit two-sided bank_balance operation; both missing is an error.
            _column_keys(table, [credit_column, debit_column])
            result["citations"].extend(_refs(table, rows, [credit_column, debit_column]))
            credit, debit = [], []
            for row in rows:
                c, d = row["values"].get(credit_column), row["values"].get(debit_column)
                if c in (None, "") and d in (None, ""):
                    raise PendingEvidence("MISSING_EVIDENCE", "A bank transaction has neither a debit nor a credit")
                c = Decimal(0) if c in (None, "") else _decimal(c)
                d = Decimal(0) if d in (None, "") else _decimal(d)
                if c < 0 or (debit_sign == "positive" and d < 0) or (debit_sign == "negative" and d > 0):
                    raise PendingEvidence("NEEDS_REVIEW", "Bank amount signs disagree with the explicit convention")
                if c != 0 and d != 0:
                    raise PendingEvidence("NEEDS_REVIEW", "A bank row has both a nonzero debit and credit")
                credit.append(c)
                debit.append(d)
            opening, expected = _decimal(parameters.get("opening")), _decimal(parameters.get("closing"))
            credits, debits = sum(credit, Decimal(0)), sum(debit, Decimal(0))
            actual = opening + credits + (debits if debit_sign == "negative" else -debits)
            result["operands"].update(opening=_number(opening), credits=_number(credits), debits=_number(debits),
                                      debit_sign=debit_sign, credit_column=credit_column, debit_column=debit_column,
                                      opening_origin="requirements configuration", closing_origin="requirements configuration")
            result["citations"].extend(_refs(table, rows, [credit_column, debit_column]))
        elif kind == "fee":
            if any(not isinstance(parameters.get(key), str) or not parameters[key].strip() for key in ("rule_id", "rule_version", "rule_approved_by")):
                raise PendingEvidence("NEEDS_REVIEW", "Fee treatment needs an explicit approved versioned rule")
            approver = parameters["rule_approved_by"]
            if not any(m["actor_id"] == approver and m.get("party") == "account_manager" for m in _members(state)):
                raise PendingEvidence("NEEDS_REVIEW", "The fee rule approver is not an active authorised management member")
            scale = parameters.get("scale", 2)
            if type(scale) is not int or not 0 <= scale <= 12:
                raise ValueError("Fee scale must be 0 through 12")
            base_column, actual_column = parameters.get("base_column"), parameters.get("actual_column")
            _column_keys(table, [base_column, actual_column])
            result["citations"].extend(_refs(table, rows, [base_column, actual_column]))
            bases = _numeric_values(table, rows, base_column)
            actual_values = _numeric_values(table, rows, actual_column)
            rate = _decimal(parameters.get("rate"))
            if rate < 0:
                raise ValueError("A fee rate cannot be negative")
            base = sum(bases, Decimal(0))
            # The versioned definition is aggregate base x explicit decimal rate,
            # rounded once, half-even. It does not infer annualisation or offsets.
            raw_expected = base * rate
            context.traps[Inexact] = False
            expected = raw_expected.quantize(Decimal(1).scaleb(-scale), rounding=ROUND_HALF_EVEN)
            context.traps[Inexact] = True
            actual = sum(actual_values, Decimal(0))
            result["operands"].update(base=_number(base), rate=_number(rate), base_column=base_column,
                                      actual_column=actual_column, scale=scale, rounding="ROUND_HALF_EVEN",
                                      rule_id=parameters["rule_id"], rule_version=parameters["rule_version"],
                                      rule_approved_by=approver, formula="sum(base) * rate; round once")
            result["citations"].extend(_refs(table, rows, [base_column, actual_column]))
        else:
            raise ValueError("Unsupported calculation kind")
        difference = actual - expected
        result.update(expected=_number(expected), actual=_number(actual), difference=_number(difference),
                      status="PASS" if abs(difference) <= tolerance else "FAIL",
                      message="Declared numeric relationship passed" if abs(difference) <= tolerance else "Declared numeric relationship failed")


def evaluate_requirements(state: dict, load_table: Callable[[dict], dict], now: datetime | str) -> list[dict]:
    """Evaluate current logical-document revisions without changing supplied state."""
    moment = _time(now)
    version = state.get("requirements_version", 1)
    requirements = state.get("requirements", [])
    if not requirements:
        return [{"requirement_id": "missing_check_policy", "title": "Configure required evidence and checks",
                 "kind": "evidence", "blocking": True, "status": "MISSING_EVIDENCE", "outcome": "MISSING_EVIDENCE",
                 "message": "No requirements are configured; an empty policy cannot establish readiness",
                 "requirement_version": version, "inputs": [], "citations": [], "operands": {},
                 "checked_at": _stamp(moment), "fingerprint": _hash(["missing_check_policy", version])}]
    validate_requirements(requirements)
    results = []
    for requirement in requirements:
        result = {"requirement_id": requirement["id"], "title": requirement["title"], "kind": requirement["kind"],
                  "blocking": requirement.get("blocking", True), "status": "ERROR", "message": "Not evaluated",
                  "requirement_version": version, "inputs": [], "citations": [], "operands": {}, "checked_at": _stamp(moment)}
        try:
            _, datasets = _resolve_inputs(state, requirement, result, moment)
            if requirement["kind"] == "evidence":
                result.update(status="PASS", message="Required current evidence is complete and accepted")
                result["operands"] = {"document_count": len(requirement["document_ids"]), "minimum_documents": requirement.get("parameters", {}).get("minimum_documents", 1)}
            else:
                dataset = _selected_dataset(state, requirement, datasets)
                table = load_table(dataset)
                if not isinstance(table, dict) or not isinstance(table.get("rows"), list) or not isinstance(table.get("columns"), list):
                    raise ValueError("Stored dataset is not a valid table")
                result["dataset_id"] = dataset["id"]
                _calculate(state, requirement, table, result)
        except PendingEvidence as exc:
            result.update(status=exc.status, message=str(exc))
        except (ValueError, KeyError, TypeError, InvalidOperation, Inexact) as exc:
            result.update(status="ERROR", message="Check could not execute: " + str(exc)[:500])
        except Exception:
            result.update(status="ERROR", message="Stored evidence could not be read")
        result["citations"] = list({_hash(ref): ref for ref in result["citations"]}.values())
        result["outcome"] = result["status"]
        result["fingerprint"] = _hash({"requirement": requirement, "version": version,
                                        "result": {key: value for key, value in result.items() if key not in ("checked_at", "fingerprint")}})
        results.append(result)
    return results


def requirements_blocked(evaluations: list[dict]) -> bool:
    return not evaluations or any(r.get("blocking", True) and r.get("status") != "PASS" for r in evaluations)


def tasks_blocked(state: dict) -> bool:
    return any(t.get("active", True) and t.get("blocking", True) and t.get("status") != "resolved" for t in state.get("tasks", []))


def _event(task: dict, action: str, actor: str, now: datetime | str, note: str = "") -> None:
    task.setdefault("events", []).append({"action": action, "actor_id": actor, "at": _stamp(now), "note": note})
    task["updated_at"] = _stamp(now)


def _actions(task: dict) -> list[str]:
    if not task.get("active", True):
        return []
    status = task["status"]
    if status == "pending_manager_release":
        return ["release"]
    if status == "resolved":
        return ["reopen"] if task["kind"] == "manual" else []
    actions = []
    if status == "open":
        actions.append("acknowledge")
    if status in ("open", "acknowledged"):
        actions.append("evidence_received")
    if status == "evidence_received":
        actions.append("request_verification")
    if task["kind"] == "manual":
        actions.append("resolve")
    return actions


def _notify(state: dict, task: dict, event: str, now: datetime | str, recipients: list[str] | None = None, *, revision: str | None = None) -> None:
    # Investor recipients receive nothing until account-manager release.
    if recipients is None:
        recipients = [task["owner_actor_id"]] if task.get("owner_actor_id") else []
        if event in ('evidence_received','request_verification','acknowledge'):
            recipients = list(set(recipients + ([task['created_by']] if task.get('created_by') else [m['actor_id'] for m in _members(state,'account_manager')])))
    if task["owner_party"] == "investor" and not task.get("released_at"):
        recipients = [m["actor_id"] for m in _members(state, "account_manager")]
    existing = {item["id"] for item in state.setdefault("notifications", [])}
    for recipient in sorted(set(recipients)):
        identity = "notification-" + _hash([task["id"], task.get("cycle", 1), event, recipient, revision])[:24]
        if identity in existing:
            continue
        state["notifications"].append({"id": identity, "task_id": task["id"], "request_id": task["id"],
            "event": event, "cycle": task.get("cycle", 1), "recipient_actor_id": recipient,
            "title": task["title"], "message": task.get("message", task.get("description", event.replace("_", " "))), "created_at": _stamp(now),
            "read_at": None, "delivery": "in_app", "document_ids": list(task.get("document_ids", []))})
        existing.add(identity)


def _owner(state: dict, requirement: dict) -> tuple[str, str | None]:
    party, actor = requirement.get("owner_party", "account_manager"), requirement.get("owner_actor_id")
    if actor and any(m["actor_id"] == actor and m.get("party") == party for m in _members(state)):
        return party, actor
    managers = sorted(m["actor_id"] for m in _members(state, "account_manager"))
    return "account_manager", managers[0] if managers else None


def _overdue(state: dict, task: dict, now: datetime) -> None:
    if not task.get("active", True) or task["status"] == "resolved" or not task.get("due_at"):
        task["overdue"] = False
        return
    deadline = _time(task["due_at"])
    if now <= deadline:
        task["overdue"] = False
        return
    task["overdue"] = True
    _notify(state, task, "overdue", now)
    delay = task.get("escalate_after_days")
    if delay is not None and now > deadline + timedelta(days=delay):
        managers = [m["actor_id"] for m in _members(state) if m.get("party") == "account_manager"]
        _notify(state, task, "escalated", now, managers)
        task["escalated"] = True


def tick_deadlines(state: dict, now: datetime | str) -> dict:
    """Emit due/escalation records once per persisted task cycle, without checks."""
    moment = _time(now)
    state.setdefault("tasks", [])
    state.setdefault("notifications", [])
    for task in state["tasks"]:
        _overdue(state, task, moment)
    return state


def sync_tasks(state: dict, evaluations: list[dict], now: datetime | str) -> dict:
    """Apply outcomes and deduplicated inbox records inside a locked transaction.

    Requirement bindings remain authoritative. Response attachments are retained
    separately until an account manager explicitly updates the requirement.
    """
    moment = _time(now)
    definitions = {r["id"]: r for r in state.get("requirements", [])}
    tasks = state.setdefault("tasks", [])
    state.setdefault("notifications", [])
    active_ids = {r["requirement_id"] for r in evaluations}
    for task in tasks:
        if task.get("kind") == "requirement" and task.get("requirement_id") not in active_ids and task.get("active", True):
            task["active"] = False
            task["allowed_actions"] = []
            _event(task, "requirement_withdrawn", "system", moment, "Requirement no longer belongs to the current version; this is not a passing check")
    for result in evaluations:
        identity = result["requirement_id"]
        requirement = definitions.get(identity, {"id": identity, "title": result["title"], "blocking": True,
                                                 "owner_party": "account_manager", "document_ids": []})
        task = next((t for t in tasks if t.get("kind") == "requirement" and t.get("requirement_id") == identity), None)
        outcome = result.get("outcome", result.get("status"))
        if outcome == "PASS" and task is None:
            continue
        # Review and execution errors are internal work, never an investor request.
        assignment = {"owner_party": "account_manager"} if outcome in ("NEEDS_REVIEW", "ERROR") else requirement
        party, actor = _owner(state, assignment)
        created = task is None
        if created:
            task = {"id": "task-" + _hash([state.get("id"), "requirement", identity])[:24],
                    "kind": "requirement", "requirement_id": identity, "title": requirement["title"],
                    "blocking": requirement.get("blocking", True), "owner_party": party, "owner_actor_id": actor,
                    "document_ids": list(requirement.get("document_ids", [])), "status": "pending_manager_release" if party == "investor" else "open",
                    "created_at": _stamp(moment), "updated_at": _stamp(moment), "events": [], "cycle": 1, "active": True}
            tasks.append(task)
        previous_status = task["status"]
        previous_fingerprint = task.get("evaluation_fingerprint")
        material_change = previous_fingerprint is not None and previous_fingerprint != result.get("fingerprint")
        reassigned = (task.get("owner_party"), task.get("owner_actor_id")) != (party, actor)
        reactivate = not task.get("active", True)
        task.update(active=True, title=requirement["title"], blocking=requirement.get("blocking", True),
                    document_ids=list(dict.fromkeys([*requirement.get("document_ids", []), *task.get("response_document_ids", [])])),
                    required_document_ids=list(requirement.get("document_ids", [])), due_at=requirement.get("due_at"),
                    escalate_after_days=requirement.get("escalate_after_days"), description=result["message"], message=result["message"],
                    requirement_version=result.get("requirement_version"), evaluation_status=outcome)
        if outcome == "PASS":
            # Keep the current recipient on closure; never expose an internal review
            # outcome to an investor who has not received an approved request.
            if task["status"] != "resolved":
                task["status"] = "resolved"
                task["resolved_at"] = _stamp(moment)
                _event(task, "verification_passed", "system", moment, result["message"])
                _notify(state, task, "resolved", moment)
        else:
            renew_release = party == "investor" and material_change and task.get("released_at")
            renewed = previous_status == "resolved" or reassigned or reactivate or renew_release
            if renewed:
                task["cycle"] += 1
                task["status"] = "pending_manager_release" if party == "investor" else "open"
                for field in ("resolved_at", "released_by", "released_at", "overdue", "escalated"):
                    task.pop(field, None)
                _event(task, "reopened" if previous_status == "resolved" or reactivate else "reassigned" if reassigned else "request_changed", "system", moment, result["message"])
            task["owner_party"], task["owner_actor_id"] = party, actor
            if created:
                _event(task, "created", "system", moment)
            if created or renewed:
                _notify(state, task, "manager_release_required" if party == "investor" else "assigned", moment)
            received = any(item.get("source_id") for item in result.get("inputs", []))
            if received and outcome == "NEEDS_REVIEW" and task["status"] in ("open", "acknowledged"):
                task["status"] = "evidence_received"
                _event(task, "evidence_received", "system", moment)
                _notify(state, task, "evidence_received", moment)
            if material_change and not renewed:
                _event(task, "evidence_changed", "system", moment, result["message"])
                _notify(state, task, "evidence_changed", moment, revision=result.get("fingerprint"))
        task["evaluation_fingerprint"] = result.get("fingerprint")
        task["allowed_actions"] = _actions(task)
    return tick_deadlines(state, moment)


def sync_processing_error(state: dict, error: Any, now: datetime | str) -> dict | None:
    """Maintain one internal operational task. Pass None after successful retry.

    Provider exception text is deliberately not copied into user-facing records.
    The persisted fingerprint deduplicates repeated failures without leaking it.
    """
    identity = "task-" + _hash([state.get("id"), "processing_error"])[:24]
    task = next((t for t in state.setdefault("tasks", []) if t["id"] == identity), None)
    if error is None:
        if task and task["status"] != "resolved":
            task.update(status="resolved", resolved_at=_stamp(now), message="Processing completed successfully")
            _event(task, "processing_recovered", "system", now)
            _notify(state, task, "resolved", now)
            task["allowed_actions"] = []
        return task
    fingerprint = _hash(error if isinstance(error, (str, dict, list, int, bool)) else str(error))
    party, actor = _owner(state, {"owner_party": "account_manager"})
    message = "Collection processing failed. Inspect the processing diagnostic and retry before release."
    if task is None:
        task = {"id": identity, "kind": "processing_error", "title": "Retry failed collection processing",
                "description": message, "message": message, "blocking": True, "owner_party": party, "owner_actor_id": actor,
                "document_ids": [], "status": "open", "created_at": _stamp(now), "updated_at": _stamp(now),
                "events": [], "cycle": 1, "active": True}
        state["tasks"].append(task)
        _event(task, "processing_failed", "system", now)
        _notify(state, task, "assigned", now)
    elif task["status"] == "resolved":
        task.update(status="open", cycle=task["cycle"] + 1)
        task.pop("resolved_at", None)
        _event(task, "processing_failed", "system", now)
        _notify(state, task, "assigned", now)
    elif task.get("error_fingerprint") != fingerprint:
        _event(task, "processing_error_changed", "system", now)
        _notify(state, task, "processing_error_changed", now, revision=fingerprint)
    task.update(error_fingerprint=fingerprint, owner_party=party, owner_actor_id=actor, active=True,
                message=message, description=message)
    task["allowed_actions"] = _actions(task)
    return task


def create_manual_flag(state: dict, flag: dict, actor_id: str, now: datetime | str) -> dict:
    """Create a durable manual task; root verifies scope, party and actor authority."""
    identity, title = flag.get("id"), flag.get("title")
    if not isinstance(identity, str) or not identity or not isinstance(title, str) or not title.strip():
        raise ValueError("Manual flags require an idempotent ID and title")
    if not isinstance(flag.get("reason"), str) or not flag["reason"].strip():
        raise ValueError("A manual flag needs a reason")
    document_ids = flag.get("document_ids", [])
    if (not isinstance(document_ids, list) or any(not isinstance(d, str) or d not in _documents(state) for d in document_ids)
            or len(set(document_ids)) != len(document_ids)):
        raise ValueError("Manual flag refers to unknown or duplicate logical documents")
    if type(flag.get("blocking", True)) is not bool:
        raise ValueError("Manual flag blocking must be a boolean")
    if flag.get("owner_party", "account_manager") not in PARTIES:
        raise ValueError("Unknown owner party")
    delay = flag.get("escalate_after_days")
    if delay is not None and (type(delay) is not int or not 0 <= delay <= 3650):
        raise ValueError("escalate_after_days must be 0 through 3650")
    if flag.get("due_at"):
        _time(flag["due_at"])
    task_id = "task-" + _hash([state.get("id"), "manual", identity])[:24]
    existing = next((t for t in state.get("tasks", []) if t["id"] == task_id), None)
    signature = _hash(flag)
    if existing:
        if existing.get("request_fingerprint") != signature:
            raise ValueError("Manual flag ID was already used with different content")
        return existing
    party, owner = _owner(state, flag)
    task = {"id": task_id, "kind": "manual", "title": title, "description": flag["reason"],
            "blocking": flag.get("blocking", True), "owner_party": party, "owner_actor_id": owner,
            "document_ids": list(document_ids), "status": "pending_manager_release" if party == "investor" else "open",
            "due_at": flag.get("due_at"), "escalate_after_days": flag.get("escalate_after_days"),
            "created_at": _stamp(now), "updated_at": _stamp(now), "created_by": actor_id,
            "events": [], "cycle": 1, "active": True, "request_fingerprint": signature}
    _event(task, "created", actor_id, now, flag["reason"])
    task["allowed_actions"] = _actions(task)
    state.setdefault("tasks", []).append(task)
    _notify(state, task, "manager_release_required" if party == "investor" else "assigned", now)
    return task


def apply_task_action(state: dict, task_id: str, action: str, actor_id: str, now: datetime | str,
                      *, note: str = "", document_ids: list[str] | None = None) -> dict:
    task = next((task for task in state.get("tasks", []) if task["id"] == task_id), None)
    if not task or action not in _actions(task):
        raise ValueError("Task action is unavailable in its current state")
    if not isinstance(note, str) or not note.strip():
        raise ValueError("A task action requires a recorded reason")
    if action == "release":
        if not any(m["actor_id"] == actor_id and m.get("party") == "account_manager" for m in _members(state)):
            raise ValueError("Only an account manager may release an investor request")
        task["status"] = "open"
        task.update(released_by=actor_id, released_at=_stamp(now))
    elif action == "acknowledge":
        task["status"] = "acknowledged"
    elif action == "evidence_received":
        attached = document_ids if document_ids is not None else task.get("document_ids", [])
        if (not isinstance(attached, list) or not attached
                or any(not isinstance(identity, str) or identity not in _documents(state) or not _documents(state)[identity].get("current_revision_id") for identity in attached)):
            raise ValueError("Evidence received requires attached logical documents with current revisions")
        task["response_document_ids"] = list(dict.fromkeys([*task.get("response_document_ids", []), *attached]))
        task["document_ids"] = list(dict.fromkeys([*task.get("document_ids", []), *attached]))
        task["status"] = "evidence_received"
    elif action == "request_verification":
        task["status"] = "verification_pending"
    elif action == "resolve":
        if task["kind"] != "manual":
            raise ValueError("Requirement tasks resolve only through passing reevaluation")
        task["status"] = "resolved"
        task["resolved_at"] = _stamp(now)
    elif action == "reopen":
        task["cycle"] += 1
        task["status"] = "pending_manager_release" if task["owner_party"] == "investor" else "open"
        for field in ("resolved_at", "released_at", "released_by", "overdue", "escalated"):
            task.pop(field, None)
    _event(task, action, actor_id, now, note)
    task["allowed_actions"] = _actions(task)
    _notify(state, task, "request_released" if action == "release" else action, now)
    _overdue(state, task, _time(now))
    return task


# Stable convenience name for the root service integration.
def task_action(state: dict, task_id: str, action: str, actor_id: str, now: datetime | str,
                *, note: str = "", document_ids: list[str] | None = None) -> dict:
    return apply_task_action(state, task_id, action, actor_id, now, note=note, document_ids=document_ids)
