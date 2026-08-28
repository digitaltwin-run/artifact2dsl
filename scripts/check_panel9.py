#!/usr/bin/env python3
"""Exercise artifact2dsl against the panel9 fixture used by Artifact Viewer."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import pcb2dsl
import sch2dsl
import svg2dsl

from artifact2dsl import compare_documents
from artifact2dsl.compare import load_rules
from artifact2dsl.registry import convert_path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARTIFACTS = Path("/home/tom/github/maskservice/viewer/artifacts")


def parity_problems(parity: dict[str, object]) -> list[str]:
    """Turn every non-match outcome into a blocking panel9 diagnostic."""
    summary = parity["summary"]
    assert isinstance(summary, dict)
    problems: list[str] = []
    for outcome in ("CONFLICT", "MISSING_LEFT", "MISSING_RIGHT", "UNEVALUABLE"):
        if summary[outcome]:
            problems.append(f"SCH-PCB {outcome}={summary[outcome]}")
    if summary["source_errors"]:
        problems.append(f"SCH-PCB source_errors={summary['source_errors']}")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts-root", type=Path, default=DEFAULT_ARTIFACTS)
    configured_netlist = os.environ.get("PANEL9_NETLIST")
    parser.add_argument(
        "--netlist", type=Path, default=Path(configured_netlist) if configured_netlist else None
    )
    args = parser.parse_args()

    artifacts = args.artifacts_root.resolve()
    schematic_path = artifacts / "pcb/panel9.kicad_sch"
    board_path = artifacts / "pcb/panel9.kicad_pcb"
    scad_path = artifacts / "drawings/panel-frame.scad"
    required = [schematic_path, board_path, scad_path]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        parser.error("missing panel9 artifacts: " + ", ".join(missing))

    schematic = sch2dsl.convert_path(schematic_path, netlist=args.netlist)
    board = pcb2dsl.convert_path(board_path)
    parity = compare_documents([schematic, board])
    geometry = compare_documents(
        [convert_path(scad_path), board],
        load_rules(ROOT / "examples/panel-dimensions.rules.json"),
    )
    svg_documents = [svg2dsl.convert_path(path) for path in sorted((artifacts / "drawings").glob("*.svg"))]

    problems = parity_problems(parity)
    if geometry["status"] != "passed":
        problems.append(f"CAD-PCB geometry={geometry['summary']}")
    pin_results = [item for item in parity["results"] if item["namespace"] == "eda.pin-net"]
    if args.netlist:
        if not pin_results:
            problems.append("SCH netlist produced no eda.pin-net comparisons")
        elif any(item["outcome"] != "MATCH" for item in pin_results):
            problems.append("SCH-PCB pin-net parity is not complete")
    svg_errors = sum(
        finding["severity"] in {"error", "critical"}
        for document in svg_documents
        for finding in document["findings"]
    )
    if svg_errors:
        problems.append(f"SVG source_errors={svg_errors}")

    payload = {
        "status": "passed" if not problems else "blocked",
        "artifacts_root": artifacts.as_posix(),
        "netlist_supplied": bool(args.netlist),
        "sch_pcb": parity["summary"],
        "pin_net": {
            "comparisons": len(pin_results),
            "matches": sum(item["outcome"] == "MATCH" for item in pin_results),
        },
        "cad_pcb": geometry["summary"],
        "svg": {"documents": len(svg_documents), "source_errors": svg_errors},
        "problems": problems,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
