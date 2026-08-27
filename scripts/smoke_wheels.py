#!/usr/bin/env python3
"""Build every distribution and exercise its installed console entry point."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TWIN_KICAD = ROOT.parent / "twin-kicad"

SCH = """(kicad_sch (version 20240108) (generator eeschema)
  (symbol (lib_id "Device:R") (at 10 20 0) (uuid sym-1)
    (property "Reference" "R1") (property "Value" "1k")
    (property "Footprint" "local:R_0603")))
"""
PCB = """(kicad_pcb (version 20240108) (generator pcbnew)
  (net 0 "") (net 1 "GND")
  (footprint "local:R_0603" (layer "B.Cu") (uuid fp-1) (at 100 50)
    (property "Reference" "R1") (property "Value" "1k")
    (pad "1" smd rect (at 0 0) (net 1 "GND")))
  (gr_rect (start 100 60) (end 110 70) (layer "Edge.Cuts")))
"""


def run(command: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=180,
    )


def json_command(command: list[str]) -> dict:
    return json.loads(run(command).stdout)


def main() -> int:
    twin_kicad = Path(os.environ.get("TWIN_KICAD_ROOT", DEFAULT_TWIN_KICAD)).resolve()
    if not (twin_kicad / "pyproject.toml").is_file():
        print(
            f"twin-kicad checkout not found at {twin_kicad}; set TWIN_KICAD_ROOT",
            file=sys.stderr,
        )
        return 2
    package_roots = [
        ROOT,
        ROOT / "packages/sch2dsl",
        ROOT / "packages/pcb2dsl",
        ROOT / "packages/svg2dsl",
        ROOT / "packages/cad2dsl",
        twin_kicad,
    ]
    with tempfile.TemporaryDirectory(prefix="artifact2dsl-wheel-smoke-") as temporary:
        work = Path(temporary)
        wheels = work / "wheels"
        wheels.mkdir()
        run(
            [
                sys.executable,
                "-m",
                "pip",
                "wheel",
                "--no-deps",
                "--no-build-isolation",
                "--disable-pip-version-check",
                "-w",
                str(wheels),
                *(str(item) for item in package_roots),
            ]
        )
        environment = work / "venv"
        venv.EnvBuilder(with_pip=True).create(environment)
        binary = environment / "bin"
        run(
            [
                str(binary / "pip"),
                "install",
                "--no-deps",
                "--disable-pip-version-check",
                *(str(item) for item in sorted(wheels.glob("*.whl"))),
            ]
        )
        artifacts = work / "artifacts"
        artifacts.mkdir()
        schematic = artifacts / "panel.kicad_sch"
        board = artifacts / "panel.kicad_pcb"
        drawing = artifacts / "drawing.svg"
        model = artifacts / "panel.scad"
        schematic.write_text(SCH, encoding="utf-8")
        board.write_text(PCB, encoding="utf-8")
        drawing.write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 20"/>', encoding="utf-8")
        model.write_text("W = 10; H = 10;\n", encoding="utf-8")

        suffixes = set(run([str(binary / "artifact2dsl"), "converters"]).stdout.splitlines())
        expected = {".kicad_sch", ".kicad_pcb", ".svg", ".scad", ".stl", ".step", ".stp", ".dxf"}
        if suffixes != expected:
            raise RuntimeError(f"installed converter registry mismatch: {sorted(suffixes)}")
        documents = [
            json_command([str(binary / "sch2dsl"), str(schematic), "--compact"]),
            json_command([str(binary / "pcb2dsl"), str(board), "--compact"]),
            json_command([str(binary / "svg2dsl"), str(drawing), "--compact"]),
            json_command([str(binary / "cad2dsl"), str(model), "--compact"]),
            json_command([str(binary / "scad2dsl"), str(model), "--compact"]),
        ]
        if any(item.get("schema_id") != "artifact2dsl.document/v1" for item in documents):
            raise RuntimeError("an installed converter returned a non-document payload")
        validation = json_command(
            [
                str(binary / "artifact2dsl"),
                "validate",
                str(schematic),
                str(board),
                "--compact",
            ]
        )
        if validation.get("status") != "passed":
            raise RuntimeError(f"installed cross-artifact validation failed: {validation['summary']}")
        names = sorted(item.name for item in wheels.glob("*.whl"))
        print(f"✓ installed and exercised {len(names)} wheels: {', '.join(names)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
