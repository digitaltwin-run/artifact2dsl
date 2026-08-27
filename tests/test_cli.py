from __future__ import annotations

import json
from pathlib import Path

from artifact2dsl.cli import main

from .test_converters import PCB, SCH


def test_cli_converts_and_validates_native_artifacts(tmp_path: Path, capsys) -> None:
    schematic = tmp_path / "panel.kicad_sch"
    board = tmp_path / "panel.kicad_pcb"
    schematic.write_text(SCH, encoding="utf-8")
    board.write_text(PCB, encoding="utf-8")

    assert main(["convert", str(schematic), "--compact"]) == 0
    converted = json.loads(capsys.readouterr().out)
    assert converted["schema_id"] == "artifact2dsl.document/v1"

    assert main(["validate", str(schematic), str(board), "--compact"]) == 0
    validation = json.loads(capsys.readouterr().out)
    assert validation["status"] == "passed"


def test_cli_exit_codes_distinguish_drift_from_invalid_input(tmp_path: Path, capsys) -> None:
    schematic = tmp_path / "panel.kicad_sch"
    board = tmp_path / "panel.kicad_pcb"
    unknown = tmp_path / "panel.unknown"
    schematic.write_text(SCH, encoding="utf-8")
    board.write_text(PCB.replace('"1k"', '"2k"'), encoding="utf-8")
    unknown.write_text("unknown", encoding="utf-8")

    assert main(["validate", str(schematic), str(board), "--compact"]) == 1
    validation = json.loads(capsys.readouterr().out)
    assert validation["summary"]["CONFLICT"] == 1

    assert main(["convert", str(unknown), "--compact"]) == 2
    assert "no installed converter" in capsys.readouterr().err


def test_cli_validates_saved_dsl_documents(tmp_path: Path, capsys) -> None:
    schematic = tmp_path / "panel.kicad_sch"
    board = tmp_path / "panel.kicad_pcb"
    schematic_dsl = tmp_path / "panel.sch.json"
    board_dsl = tmp_path / "panel.pcb.json"
    schematic.write_text(SCH, encoding="utf-8")
    board.write_text(PCB, encoding="utf-8")

    assert main(["convert", str(schematic), "-o", str(schematic_dsl)]) == 0
    assert main(["convert", str(board), "-o", str(board_dsl)]) == 0
    capsys.readouterr()

    assert main(["validate", str(schematic_dsl), str(board_dsl), "--dsl", "--compact"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "passed"
