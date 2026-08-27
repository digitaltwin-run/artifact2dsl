"""Deterministic comparison of evidence-bearing artifact claims."""

from __future__ import annotations

import fnmatch
import itertools
import json
import math
from pathlib import Path
from typing import Any

from .model import RULES_SCHEMA, VALIDATION_SCHEMA, ConversionError, validate_document

_OUTCOMES = {"MATCH", "CONFLICT", "MISSING_LEFT", "MISSING_RIGHT", "UNEVALUABLE"}


def _claim_ref(document: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": document["source"],
        "claim_id": item["id"],
        "namespace": item["namespace"],
        "subject": item["subject"],
        "predicate": item["predicate"],
        "value": item["value"],
        **({"unit": item["unit"]} if "unit" in item else {}),
        "evidence": item.get("evidence") or {},
    }


def _outcome(left: list[dict[str, Any]], right: list[dict[str, Any]], operator: str, tolerance: float) -> str:
    if not left and not right:
        return "UNEVALUABLE"
    if not left:
        return "MISSING_LEFT"
    if not right:
        return "MISSING_RIGHT"
    if len(left) != 1 or len(right) != 1:
        return "UNEVALUABLE"
    first, second = left[0].get("value"), right[0].get("value")
    if operator == "numeric":
        left_unit, right_unit = left[0].get("unit"), right[0].get("unit")
        if left_unit is not None and right_unit is not None and left_unit != right_unit:
            return "UNEVALUABLE"
        if isinstance(first, bool) or isinstance(second, bool):
            return "UNEVALUABLE"
        try:
            return "MATCH" if abs(float(first) - float(second)) <= tolerance else "CONFLICT"
        except (TypeError, ValueError):
            return "UNEVALUABLE"
    if operator != "exact":
        return "UNEVALUABLE"
    same_unit = left[0].get("unit") == right[0].get("unit")
    return "MATCH" if first == second and same_unit else "CONFLICT"


def _result(
    identity: str,
    namespace: str,
    subject: str,
    predicate: str,
    left_doc: dict[str, Any],
    right_doc: dict[str, Any],
    left: list[dict[str, Any]],
    right: list[dict[str, Any]],
    *,
    operator: str = "exact",
    tolerance: float = 0.0,
) -> dict[str, Any]:
    outcome = _outcome(left, right, operator, tolerance)
    if outcome not in _OUTCOMES:  # defensive contract check
        raise ConversionError(f"unknown comparison outcome: {outcome}")
    return {
        "id": identity,
        "namespace": namespace,
        "subject": subject,
        "predicate": predicate,
        "operator": operator,
        "tolerance": tolerance,
        "outcome": outcome,
        "left": [_claim_ref(left_doc, item) for item in left],
        "right": [_claim_ref(right_doc, item) for item in right],
    }


def _index(document: dict[str, Any], namespace: str) -> dict[tuple[str, str], list[dict[str, Any]]]:
    result: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for item in document["claims"]:
        if item["namespace"] == namespace:
            result.setdefault((item["subject"], item["predicate"]), []).append(item)
    return result


def _automatic(documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for left_index, right_index in itertools.combinations(range(len(documents)), 2):
        left_doc, right_doc = documents[left_index], documents[right_index]
        shared = sorted(set(left_doc["namespaces"]) & set(right_doc["namespaces"]))
        if not shared:
            results.append(
                {
                    "id": f"auto:{left_index}:{right_index}:no-shared-namespace",
                    "namespace": "artifact.compatibility",
                    "subject": f"{left_doc['source']['path']}::{right_doc['source']['path']}",
                    "predicate": "shared_namespace",
                    "operator": "exact",
                    "tolerance": 0.0,
                    "outcome": "UNEVALUABLE",
                    "left": [],
                    "right": [],
                }
            )
        for namespace in shared:
            left, right = _index(left_doc, namespace), _index(right_doc, namespace)
            for subject, predicate in sorted(set(left) | set(right)):
                identity = f"auto:{left_index}:{right_index}:{namespace}:{subject}:{predicate}"
                results.append(
                    _result(
                        identity,
                        namespace,
                        subject,
                        predicate,
                        left_doc,
                        right_doc,
                        left.get((subject, predicate), []),
                        right.get((subject, predicate), []),
                    )
                )
    return results


def _matches(document: dict[str, Any], selector: dict[str, Any]) -> list[dict[str, Any]]:
    source_pattern = str(selector.get("source", "*"))
    converter_pattern = str(selector.get("converter", "*"))
    if not fnmatch.fnmatch(document["source"]["path"], source_pattern):
        return []
    if not fnmatch.fnmatch(document["converter"]["name"], converter_pattern):
        return []
    return [
        item
        for item in document["claims"]
        if fnmatch.fnmatch(item["namespace"], str(selector.get("namespace", "*")))
        and fnmatch.fnmatch(item["subject"], str(selector.get("subject", "*")))
        and fnmatch.fnmatch(item["predicate"], str(selector.get("predicate", "*")))
    ]


def _explicit(documents: list[dict[str, Any]], rules: dict[str, Any]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for rule in rules.get("rules", []):
        if (
            not isinstance(rule, dict)
            or not isinstance(rule.get("left"), dict)
            or not isinstance(rule.get("right"), dict)
        ):
            raise ConversionError("every comparison rule needs left and right selectors")
        left_matches = [(doc, _matches(doc, rule["left"])) for doc in documents]
        right_matches = [(doc, _matches(doc, rule["right"])) for doc in documents]
        left_matches = [(doc, items) for doc, items in left_matches if items]
        right_matches = [(doc, items) for doc, items in right_matches if items]
        if len(left_matches) > 1 or len(right_matches) > 1:
            identity = str(rule.get("id") or f"rule:{len(output)}")
            raise ConversionError(
                f"comparison rule {identity!r} selects claims from more than one "
                "document on one side; narrow its source or converter selector"
            )
        left_doc = left_matches[0][0] if left_matches else documents[0]
        right_doc = right_matches[0][0] if right_matches else documents[-1]
        left = [item for _doc, items in left_matches for item in items]
        right = [item for _doc, items in right_matches for item in items]
        output.append(
            _result(
                str(rule.get("id") or f"rule:{len(output)}"),
                str(rule.get("namespace") or "mapped"),
                str(rule.get("subject") or rule.get("id") or "mapped"),
                str(rule.get("predicate") or "value"),
                left_doc,
                right_doc,
                left,
                right,
                operator=str(rule.get("operator") or "exact"),
                tolerance=float(rule.get("tolerance") or 0.0),
            )
        )
    return output


def validate_rules(value: dict[str, Any]) -> None:
    if not isinstance(value, dict) or set(value) != {"schema_id", "rules"}:
        raise ConversionError(f"comparison rules must use {RULES_SCHEMA}")
    if (
        value.get("schema_id") != RULES_SCHEMA
        or not isinstance(value.get("rules"), list)
        or not value["rules"]
    ):
        raise ConversionError(f"comparison rules must use {RULES_SCHEMA} and contain at least one rule")
    allowed_rule = {
        "id",
        "namespace",
        "subject",
        "predicate",
        "operator",
        "tolerance",
        "left",
        "right",
    }
    allowed_selector = {"source", "converter", "namespace", "subject", "predicate"}
    identities: set[str] = set()
    for rule in value["rules"]:
        if not isinstance(rule, dict) or set(rule) - allowed_rule:
            raise ConversionError("comparison rule contains unknown fields")
        identity = rule.get("id")
        if not isinstance(identity, str) or not identity or identity in identities:
            raise ConversionError("comparison rule ids must be non-empty and unique")
        identities.add(identity)
        for field in ("namespace", "subject", "predicate"):
            if field in rule and not isinstance(rule[field], str):
                raise ConversionError(f"comparison rule {identity!r} field {field} must be a string")
        for side in ("left", "right"):
            selector = rule.get(side)
            if not isinstance(selector, dict) or set(selector) - allowed_selector:
                raise ConversionError(f"comparison rule {identity!r} has an invalid {side} selector")
            if any(not isinstance(item, str) for item in selector.values()):
                raise ConversionError(f"comparison rule {identity!r} selectors must contain strings")
        operator = rule.get("operator", "exact")
        if operator not in {"exact", "numeric"}:
            raise ConversionError(f"comparison rule {identity!r} has an invalid operator")
        tolerance = rule.get("tolerance", 0.0)
        if isinstance(tolerance, bool) or not isinstance(tolerance, (int, float)):
            raise ConversionError(f"comparison rule {identity!r} has an invalid tolerance")
        if not math.isfinite(float(tolerance)) or tolerance < 0:
            raise ConversionError(f"comparison rule {identity!r} tolerance must be finite and non-negative")


def load_rules(path: str | Path) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConversionError(f"cannot read comparison rules: {exc}") from exc
    validate_rules(value)
    return value


def compare_documents(documents: list[dict[str, Any]], rules: dict[str, Any] | None = None) -> dict[str, Any]:
    if len(documents) < 2:
        raise ConversionError("cross-artifact validation needs at least two documents")
    for item in documents:
        validate_document(item)
    if rules is not None:
        validate_rules(rules)
    results = _explicit(documents, rules) if rules is not None else _automatic(documents)
    counts = {outcome: sum(item["outcome"] == outcome for item in results) for outcome in sorted(_OUTCOMES)}
    source_findings = [
        {**item, "source": document["source"], "producer": document["converter"]["name"]}
        for document in documents
        for item in document["findings"]
    ]
    source_errors = sum(item["severity"] in {"error", "critical"} for item in source_findings)
    blocking = (
        counts["CONFLICT"]
        + counts["MISSING_LEFT"]
        + counts["MISSING_RIGHT"]
        + counts["UNEVALUABLE"]
        + source_errors
    )
    comparison_findings = [
        {
            "code": "ARTIFACT-DRIFT-001" if item["outcome"] == "CONFLICT" else "ARTIFACT-GAP-001",
            "severity": "error",
            "message": f"{item['outcome']}: {item['namespace']} {item['subject']} {item['predicate']}",
            "comparison_id": item["id"],
        }
        for item in results
        if item["outcome"] != "MATCH"
    ]
    return {
        "schema_id": VALIDATION_SCHEMA,
        "authority": "observation_only_no_execution_grant",
        "sources": [item["source"] for item in documents],
        "mode": "explicit_rules" if rules is not None else "shared_namespaces",
        "summary": {
            "comparisons": len(results),
            **counts,
            "source_errors": source_errors,
            "blocking": blocking,
        },
        "results": results,
        "findings": [*source_findings, *comparison_findings],
        "status": "passed" if blocking == 0 else "blocked",
    }
