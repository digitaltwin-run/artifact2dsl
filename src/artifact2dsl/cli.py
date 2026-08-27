"""CLI dispatcher and cross-artifact validator."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .cli_support import emit
from .compare import compare_documents, load_rules
from .model import ConversionError, load_document
from .registry import convert_path, converters


def _conversion_options(
    artifacts: list[str], netlist: str | None, auto_netlist: bool
) -> list[dict[str, object]]:
    schematic_indexes = [
        index for index, value in enumerate(artifacts) if Path(value).suffix.lower() == ".kicad_sch"
    ]
    if netlist and len(schematic_indexes) != 1:
        raise ConversionError("--netlist requires exactly one .kicad_sch input")
    result: list[dict[str, object]] = [{} for _item in artifacts]
    if netlist:
        result[schematic_indexes[0]]["netlist"] = netlist
    if auto_netlist:
        for index in schematic_indexes:
            result[index]["auto_netlist"] = True
    return result


def _convert_many(artifacts: list[str], netlist: str | None, auto_netlist: bool) -> list[dict[str, object]]:
    options = _conversion_options(artifacts, netlist, auto_netlist)
    return [convert_path(path, **item_options) for path, item_options in zip(artifacts, options, strict=True)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="artifact2dsl")
    sub = parser.add_subparsers(dest="command", required=True)
    convert = sub.add_parser("convert", help="Convert one or more native artifacts to observation DSL.")
    convert.add_argument("artifacts", nargs="+")
    convert.add_argument("-o", "--output")
    convert.add_argument("--compact", action="store_true")
    convert.add_argument("--netlist", help="Existing KiCad XML netlist for the single SCH input.")
    convert.add_argument(
        "--kicad-cli", action="store_true", help="Export netlists for SCH inputs with kicad-cli."
    )
    validate = sub.add_parser("validate", help="Compare native artifacts or existing DSL documents.")
    validate.add_argument("artifacts", nargs="+")
    validate.add_argument(
        "--dsl", action="store_true", help="Inputs are already artifact2dsl JSON documents."
    )
    validate.add_argument("--rules", help="Explicit artifact2dsl.rules/v1 mapping.")
    validate.add_argument("-o", "--output")
    validate.add_argument("--compact", action="store_true")
    validate.add_argument("--netlist", help="Existing KiCad XML netlist for the single SCH input.")
    validate.add_argument(
        "--kicad-cli", action="store_true", help="Export netlists for SCH inputs with kicad-cli."
    )
    sub.add_parser("converters", help="List installed suffix converters.")
    args = parser.parse_args(argv)
    try:
        if args.command == "converters":
            print("\n".join(sorted(converters())) or "no converters installed")
            return 0
        if args.command == "convert":
            documents = _convert_many(args.artifacts, args.netlist, args.kicad_cli)
            value = (
                documents[0]
                if len(documents) == 1
                else {
                    "schema_id": "artifact2dsl.bundle/v1",
                    "documents": documents,
                    "authority": "observation_only_no_execution_grant",
                }
            )
            emit(value, args.output, not args.compact)
            return (
                1
                if any(
                    finding.get("severity") in {"error", "critical"}
                    for document in documents
                    for finding in document["findings"]
                )
                else 0
            )
        documents = (
            [load_document(path) for path in args.artifacts]
            if args.dsl
            else _convert_many(args.artifacts, args.netlist, args.kicad_cli)
        )
        result = compare_documents(documents, load_rules(args.rules) if args.rules else None)
        emit(result, args.output, not args.compact)
        return 1 if result["summary"]["blocking"] else 0
    except (ConversionError, OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        print(f"artifact2dsl: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
