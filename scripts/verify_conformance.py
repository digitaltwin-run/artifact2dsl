#!/usr/bin/env python3
"""Validate local contracts, artifact digests and wellmanifest/dsl adoption."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STANDARD = Path(os.environ.get("WELLMANIFEST_DSL_ROOT", Path.home() / "github/wellmanifest/dsl"))


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    problems: list[str] = []
    try:
        from jsonschema import Draft202012Validator
    except ImportError:
        print("jsonschema is required for contract conformance", file=sys.stderr)
        return 2
    schema_root = ROOT / "src/artifact2dsl/schemas"
    for path in sorted(schema_root.glob("*.json")):
        try:
            Draft202012Validator.check_schema(load(path))
        except Exception as exc:
            problems.append(f"invalid JSON Schema {path.relative_to(ROOT)}: {exc}")
    try:
        Draft202012Validator(load(schema_root / "rules.schema.json")).validate(
            load(ROOT / "examples/panel-dimensions.rules.json")
        )
    except Exception as exc:
        problems.append(f"invalid rules example: {exc}")
    manifest_path = ROOT / "dsl-manifest.json"
    manifest = load(manifest_path)
    for artifact in manifest.get("artifacts", []):
        target = ROOT / str(artifact.get("path", ""))
        if not target.is_file():
            problems.append(f"manifest artifact is missing: {artifact.get('path')}")
        elif artifact.get("digest") != digest(target):
            problems.append(f"manifest digest drift: {artifact.get('path')}")
    standard_schema = STANDARD / "schemas/dsl-manifest.schema.json"
    if standard_schema.is_file():
        for error in Draft202012Validator(load(standard_schema)).iter_errors(manifest):
            where = "/".join(str(item) for item in error.absolute_path) or "(root)"
            problems.append(f"wellmanifest/dsl {where}: {error.message}")
    else:
        problems.append(f"wellmanifest/dsl schema not found at {standard_schema}")
    for problem in problems:
        print(f"✗ {problem}", file=sys.stderr)
    if problems:
        return 1
    print("✓ artifact2dsl contracts, digests and wellmanifest/dsl manifest are consistent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
