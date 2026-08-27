"""Dependency-free canonical JSON AST for artifact observations."""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any

DOCUMENT_SCHEMA = "artifact2dsl.document/v1"
VALIDATION_SCHEMA = "artifact2dsl.validation/v1"
RULES_SCHEMA = "artifact2dsl.rules/v1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SEVERITIES = {"info", "warning", "error", "critical"}


class ConversionError(ValueError):
    """The input cannot be converted without inventing facts."""


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def evidence(*, pointer: str = "", line: int | None = None, detail: str = "") -> dict[str, Any]:
    result: dict[str, Any] = {}
    if pointer:
        result["pointer"] = pointer
    if line is not None:
        result["line"] = line
    if detail:
        result["detail"] = detail
    return result


def entity(
    identity: str,
    kind: str,
    name: str,
    *,
    attributes: dict[str, Any] | None = None,
    source_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": identity,
        "kind": kind,
        "name": name,
        "attributes": attributes or {},
        "evidence": source_evidence or {},
    }


def claim(
    identity: str,
    namespace: str,
    subject: str,
    predicate: str,
    value: Any,
    *,
    unit: str | None = None,
    source_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result = {
        "id": identity,
        "namespace": namespace,
        "subject": subject,
        "predicate": predicate,
        "value": value,
        "evidence": source_evidence or {},
    }
    if unit is not None:
        result["unit"] = unit
    return result


def finding(
    code: str,
    severity: str,
    message: str,
    *,
    subject: str = "",
    source_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if severity not in _SEVERITIES:
        raise ConversionError(f"unsupported finding severity: {severity}")
    return {
        "code": code,
        "severity": severity,
        "message": message,
        "subject": subject,
        "evidence": source_evidence or {},
    }


def document(
    *,
    converter: str,
    converter_version: str,
    path: str,
    media_type: str,
    content: bytes,
    namespaces: list[str],
    entities: list[dict[str, Any]],
    claims: list[dict[str, Any]],
    findings: list[dict[str, Any]],
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result = {
        "schema_id": DOCUMENT_SCHEMA,
        "converter": {"name": converter, "version": converter_version},
        "source": {
            "path": path,
            "media_type": media_type,
            "sha256": sha256_bytes(content),
            "size": len(content),
        },
        "namespaces": sorted(set(namespaces)),
        "entities": entities,
        "claims": claims,
        "findings": findings,
        "metadata": metadata or {},
        "authority": "observation_only_no_execution_grant",
    }
    validate_document(result)
    return result


def _require_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ConversionError(f"{field} must be a non-empty string")
    return value


def _validate_json_value(value: Any, path: str = "$") -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ConversionError(f"{path} contains a non-finite number")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_json_value(item, f"{path}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ConversionError(f"{path} contains a non-string object key")
            _validate_json_value(item, f"{path}.{key}")
        return
    raise ConversionError(f"{path} contains a non-JSON value of type {type(value).__name__}")


def validate_document(value: dict[str, Any]) -> None:
    if not isinstance(value, dict) or value.get("schema_id") != DOCUMENT_SCHEMA:
        raise ConversionError(f"expected {DOCUMENT_SCHEMA}")
    _validate_json_value(value)
    converter = value.get("converter")
    source = value.get("source")
    if not isinstance(converter, dict) or not isinstance(source, dict):
        raise ConversionError("converter and source objects are required")
    _require_string(converter.get("name"), "converter.name")
    _require_string(converter.get("version"), "converter.version")
    _require_string(source.get("path"), "source.path")
    _require_string(source.get("media_type"), "source.media_type")
    if not isinstance(source.get("sha256"), str) or not _SHA256.fullmatch(source["sha256"]):
        raise ConversionError("source.sha256 must be a lowercase SHA-256")
    if not isinstance(source.get("size"), int) or source["size"] < 0:
        raise ConversionError("source.size must be a non-negative integer")
    if value.get("authority") != "observation_only_no_execution_grant":
        raise ConversionError("an observation document cannot grant execution authority")
    namespaces = value.get("namespaces")
    if not isinstance(namespaces, list) or any(not isinstance(item, str) or not item for item in namespaces):
        raise ConversionError("namespaces must contain non-empty strings")
    for collection in ("entities", "claims", "findings"):
        if not isinstance(value.get(collection), list):
            raise ConversionError(f"{collection} must be an array")
    for collection in ("entities", "claims"):
        identities = [item.get("id") for item in value[collection] if isinstance(item, dict)]
        if len(identities) != len(value[collection]) or any(
            not isinstance(item, str) or not item for item in identities
        ):
            raise ConversionError(f"every {collection} item needs a non-empty id")
        if len(identities) != len(set(identities)):
            raise ConversionError(f"duplicate {collection} id")
    declared = set(namespaces)
    for item in value["claims"]:
        if item.get("namespace") not in declared:
            raise ConversionError(f"claim {item.get('id')} uses an undeclared namespace")
        _require_string(item.get("subject"), "claim.subject")
        _require_string(item.get("predicate"), "claim.predicate")
        if "value" not in item:
            raise ConversionError("claim.value is required; missing is not null")
    for item in value["findings"]:
        if not isinstance(item, dict) or item.get("severity") not in _SEVERITIES:
            raise ConversionError("finding severity is invalid")


def load_document(path: str | Path) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConversionError(f"cannot read DSL document: {exc}") from exc
    validate_document(value)
    return value
