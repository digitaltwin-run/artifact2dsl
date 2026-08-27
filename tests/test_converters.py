from __future__ import annotations

import json
import struct
import subprocess
from pathlib import Path

import cad2dsl
import pcb2dsl
import pytest
import sch2dsl
import svg2dsl
from jsonschema import Draft202012Validator

from artifact2dsl import ConversionError, compare_documents, validate_document
from artifact2dsl.compare import load_rules
from artifact2dsl.registry import convert_path, converters

SCH = """(kicad_sch (version 20240108) (generator eeschema)
  (symbol (lib_id "Device:R") (at 10 20 0)
    (uuid sym-1)
    (property "Reference" "R1")
    (property "Value" "1k")
    (property "Footprint" "local:R_0603")))
"""

PCB = """(kicad_pcb (version 20240108) (generator pcbnew)
  (net 0 "") (net 1 "GND")
  (footprint "local:R_0603" (layer "B.Cu") (uuid fp-1) (at 100 50)
    (property "Reference" "R1") (property "Value" "1k")
    (pad "1" smd rect (at 0 0) (net 1 "GND")))
  (gr_line (start 100 60) (end 248 60) (layer "Edge.Cuts"))
  (gr_line (start 248 60) (end 248 124) (layer "Edge.Cuts"))
  (gr_line (start 248 124) (end 100 124) (layer "Edge.Cuts"))
  (gr_line (start 100 124) (end 100 60) (layer "Edge.Cuts")))
"""

NETLIST = """<?xml version="1.0" encoding="UTF-8"?>
<export><components><comp ref="R1"><value>1k</value><footprint>local:R_0603</footprint>
<libsource lib="Device" part="R"/></comp></components>
<libparts><libpart lib="Device" part="R"><pins><pin num="1" name="~" type="passive"/></pins></libpart></libparts>
<nets><net code="1" name="GND"><node ref="R1" pin="1"/></net></nets></export>
"""


def test_schematic_and_pcb_share_component_and_pin_claims() -> None:
    schematic = sch2dsl.convert_source(SCH, "panel.kicad_sch", netlist_xml=NETLIST)
    board = pcb2dsl.convert_source(PCB, "panel.kicad_pcb")

    validate_document(schematic)
    validate_document(board)
    result = compare_documents([schematic, board])

    assert result["status"] == "passed"
    assert result["summary"] == {
        "comparisons": 4,
        "CONFLICT": 0,
        "MATCH": 4,
        "MISSING_LEFT": 0,
        "MISSING_RIGHT": 0,
        "UNEVALUABLE": 0,
        "source_errors": 0,
        "blocking": 0,
    }
    assert {item["namespace"] for item in result["results"]} == {"eda.component", "eda.pin-net"}


def test_component_drift_is_evidence_bound() -> None:
    schematic = sch2dsl.convert_source(SCH, "panel.kicad_sch")
    board = pcb2dsl.convert_source(PCB.replace('"1k"', '"2k"'), "panel.kicad_pcb")

    result = compare_documents([schematic, board])
    conflict = next(item for item in result["results"] if item["outcome"] == "CONFLICT")

    assert result["status"] == "blocked"
    assert conflict["subject"] == "component:R1"
    assert conflict["predicate"] == "value"
    assert conflict["left"][0]["source"]["sha256"] == schematic["source"]["sha256"]


def test_scad_parameters_map_explicitly_to_pcb_outline(tmp_path: Path) -> None:
    scad = cad2dsl._scad(b"W = 148; H = 64; T = 3;\n", "panel.scad")
    board = pcb2dsl.convert_source(PCB, "panel.kicad_pcb")
    rule_path = Path(__file__).resolve().parents[1] / "examples" / "panel-dimensions.rules.json"

    result = compare_documents([scad, board], load_rules(rule_path))

    assert result["status"] == "passed"
    assert result["summary"]["MATCH"] == 2


def test_svg_reports_missing_references_and_duplicate_ids() -> None:
    source = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 20"><g id="x"/><g id="x" fill="url(#missing)"/></svg>'

    result = svg2dsl.convert_source(source, "drawing.svg")

    assert result["source"]["media_type"] == "image/svg+xml"
    assert {item["code"] for item in result["findings"]} == {
        "SVG-ID-DUPLICATE-001",
        "SVG-REFERENCE-MISSING-001",
    }
    assert next(item for item in result["claims"] if item["id"] == "svg:canvas:height")["value"] == 20.0


def test_cad_supports_binary_stl_and_rejects_empty_mesh() -> None:
    triangle = struct.pack("<12fH", 0, 0, 1, 0, 0, 0, 2, 0, 0, 0, 3, 0, 0)
    valid = cad2dsl._stl(b"binary".ljust(80, b"\0") + struct.pack("<I", 1) + triangle, "part.stl")
    empty = cad2dsl._stl(b"solid empty\nendsolid\n", "empty.stl")

    assert valid["metadata"]["format"] == "binary"
    assert next(item for item in valid["claims"] if item["predicate"] == "triangle_count")["value"] == 1
    assert empty["findings"][0]["code"] == "CAD-STL-EMPTY-001"


def test_dispatcher_discovers_source_checkout_packages(tmp_path: Path) -> None:
    board = tmp_path / "panel.kicad_pcb"
    board.write_text(PCB, encoding="utf-8")

    result = convert_path(board)

    assert result["converter"]["name"] == "pcb2dsl"
    assert {".kicad_sch", ".kicad_pcb", ".svg", ".scad"}.issubset(converters())


def test_invalid_root_fails_closed() -> None:
    with pytest.raises(ConversionError, match="kicad_sch"):
        sch2dsl.convert_source("(kicad_pcb)", "wrong.kicad_sch")


def test_sch_can_export_authoritative_netlist_with_kicad_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    schematic_path = tmp_path / "panel.kicad_sch"
    schematic_path.write_text(SCH, encoding="utf-8")
    commands: list[list[str]] = []

    def fake_run(command: list[str], **_options: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        output = Path(command[command.index("-o") + 1])
        output.write_text(NETLIST, encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(sch2dsl.subprocess, "run", fake_run)

    result = sch2dsl.convert_path(schematic_path, auto_netlist=True, kicad_cli="test-kicad-cli")

    assert result["metadata"]["netlist"] is True
    assert ["--format", "kicadxml"] == commands[0][4:6]
    assert any(item["namespace"] == "eda.pin-net" for item in result["claims"])


def test_document_can_round_trip_as_json() -> None:
    value = json.loads(json.dumps(sch2dsl.convert_source(SCH, "panel.kicad_sch")))
    validate_document(value)


def test_published_json_schemas_accept_runtime_documents() -> None:
    root = Path(__file__).resolve().parents[1]
    schemas = root / "src" / "artifact2dsl" / "schemas"
    schematic = sch2dsl.convert_source(SCH, "panel.kicad_sch", netlist_xml=NETLIST)
    board = pcb2dsl.convert_source(PCB, "panel.kicad_pcb")
    validation = compare_documents([schematic, board])

    Draft202012Validator(json.loads((schemas / "document.schema.json").read_text(encoding="utf-8"))).validate(
        schematic
    )
    Draft202012Validator(
        json.loads((schemas / "validation.schema.json").read_text(encoding="utf-8"))
    ).validate(validation)
    Draft202012Validator(json.loads((schemas / "rules.schema.json").read_text(encoding="utf-8"))).validate(
        json.loads((root / "examples" / "panel-dimensions.rules.json").read_text(encoding="utf-8"))
    )
