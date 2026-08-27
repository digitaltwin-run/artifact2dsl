from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import cad2dsl
import pcb2dsl
import pytest
import sch2dsl
import svg2dsl

from artifact2dsl import ConversionError, compare_documents, load_document
from artifact2dsl.compare import load_rules

from .test_converters import PCB, SCH


def test_automatic_comparison_distinguishes_missing_and_ambiguous_claims() -> None:
    schematic = sch2dsl.convert_source(SCH, "panel.kicad_sch")
    board = pcb2dsl.convert_source(PCB, "panel.kicad_pcb")
    board["claims"] = [item for item in board["claims"] if item["predicate"] != "value"]

    missing = compare_documents([schematic, board])

    assert missing["summary"]["MISSING_RIGHT"] == 1
    duplicate = deepcopy(board["claims"][0])
    duplicate["id"] += ":duplicate"
    board["claims"].append(duplicate)

    ambiguous = compare_documents([schematic, board])

    assert ambiguous["summary"]["UNEVALUABLE"] == 1


def test_exact_comparison_treats_different_units_as_conflict() -> None:
    left = cad2dsl._scad(b"W = 10;\n", "left.scad")
    right = deepcopy(left)
    right["source"] = {**right["source"], "path": "right.scad"}
    left["claims"][0]["unit"] = "mm"
    right["claims"][0]["unit"] = "mil"

    result = compare_documents([left, right])

    assert result["summary"]["CONFLICT"] == 1


def test_numeric_comparison_refuses_different_explicit_units() -> None:
    left = cad2dsl._scad(b"W = 10;\n", "left.scad")
    right = cad2dsl._scad(b"W = 10;\n", "right.scad")
    left["claims"][0]["unit"] = "mm"
    right["claims"][0]["unit"] = "mil"
    rules = {
        "schema_id": "artifact2dsl.rules/v1",
        "rules": [
            {
                "id": "width",
                "operator": "numeric",
                "left": {"source": "left.scad"},
                "right": {"source": "right.scad"},
            }
        ],
    }

    result = compare_documents([left, right], rules)

    assert result["summary"]["UNEVALUABLE"] == 1


def test_automatic_comparison_never_passes_unrelated_domains() -> None:
    drawing = svg2dsl.convert_source(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"/>', "drawing.svg"
    )
    board = pcb2dsl.convert_source(PCB, "panel.kicad_pcb")

    result = compare_documents([drawing, board])

    assert result["status"] == "blocked"
    assert result["summary"]["comparisons"] == 1
    assert result["summary"]["UNEVALUABLE"] == 1


def test_explicit_rule_must_select_at_most_one_document_per_side() -> None:
    first = cad2dsl._scad(b"W = 10;\n", "first.scad")
    second = cad2dsl._scad(b"W = 10;\n", "second.scad")
    board = pcb2dsl.convert_source(PCB, "panel.kicad_pcb")
    rules = {
        "schema_id": "artifact2dsl.rules/v1",
        "rules": [
            {
                "id": "width",
                "left": {"source": "*.scad", "namespace": "cad.parameter"},
                "right": {"source": "*.kicad_pcb", "namespace": "board.geometry"},
            }
        ],
    }

    with pytest.raises(ConversionError, match="more than one document"):
        compare_documents([first, second, board], rules)


@pytest.mark.parametrize("tolerance", [-1, float("inf"), True, "0.1"])
def test_rule_loader_rejects_invalid_tolerance(tmp_path: Path, tolerance: object) -> None:
    rules = {
        "schema_id": "artifact2dsl.rules/v1",
        "rules": [{"id": "x", "left": {}, "right": {}, "tolerance": tolerance}],
    }
    path = tmp_path / "rules.json"
    path.write_text(json.dumps(rules), encoding="utf-8")

    with pytest.raises(ConversionError, match="tolerance"):
        load_rules(path)


def test_scad_ignores_assignments_and_braces_in_comments_or_strings() -> None:
    source = b"""W = 148; // H = 999; }
/* T = 42; { */
label = "not a } brace";
module panel() { cube([1, 1, 1]); }
"""

    result = cad2dsl._scad(source, "panel.scad")

    assert not result["findings"]
    assert [
        (item["subject"], item["value"]) for item in result["claims"] if item["namespace"] == "cad.parameter"
    ] == [("parameter:W", 148.0)]
    assert any(item["subject"] == "module:panel" for item in result["claims"])


@pytest.mark.parametrize("source", [b"W=10; /* unfinished\n", b'W=10; label="unfinished\n'])
def test_scad_reports_unterminated_lexical_constructs(source: bytes) -> None:
    result = cad2dsl._scad(source, "broken.scad")

    assert "CAD-SCAD-LEXICAL-001" in {item["code"] for item in result["findings"]}


def test_cad_structural_readers_cover_ascii_stl_step_and_dxf() -> None:
    stl = cad2dsl._stl(
        b"solid p\nfacet normal 0 0 1\nouter loop\nvertex 0 0 0\nvertex 2 0 0\nvertex 0 3 0\nendloop\nendfacet\nendsolid\n",
        "part.stl",
    )
    step = cad2dsl._step(
        b"ISO-10303-21;\nHEADER;\nENDSEC;\nDATA;\n#1=PRODUCT('Panel','','',());\n#2=CARTESIAN_POINT('',(0.,0.,0.));\nENDSEC;\nEND-ISO-10303-21;\n",
        "part.step",
    )
    dxf = cad2dsl._dxf(
        b"0\nSECTION\n2\nENTITIES\n0\nLINE\n0\nCIRCLE\n0\nENDSEC\n0\nEOF\n",
        "part.dxf",
    )

    assert not stl["findings"]
    assert {item["predicate"]: item["value"] for item in stl["claims"]}["triangle_count"] == 1
    assert step["metadata"]["entity_count"] == 2
    assert any(item["value"] == "Panel" for item in step["claims"])
    assert {item["subject"]: item["value"] for item in dxf["claims"]} == {
        "entity-type:CIRCLE": 1,
        "entity-type:LINE": 1,
    }


def test_stl_nonfinite_coordinate_is_blocking_and_json_safe() -> None:
    result = cad2dsl._stl(
        b"solid p\nvertex 1e999 0 0\nvertex 0 0 0\nvertex 0 1 0\nendsolid\n",
        "bad.stl",
    )

    assert "CAD-STL-NONFINITE-001" in {item["code"] for item in result["findings"]}
    json.dumps(result, allow_nan=False)


def test_binary_dxf_fails_closed() -> None:
    with pytest.raises(ConversionError, match="ASCII DXF only"):
        cad2dsl._dxf(b"AutoCAD Binary DXF\r\n\x1a\x00", "binary.dxf")


def test_converter_errors_block_otherwise_matching_claims() -> None:
    first = cad2dsl._stl(b"solid empty\nendsolid\n", "first.stl")
    second = cad2dsl._stl(b"solid empty\nendsolid\n", "second.stl")

    result = compare_documents([first, second])

    assert result["summary"]["MATCH"] == 1
    assert result["summary"]["source_errors"] == 2
    assert result["status"] == "blocked"


def test_saved_dsl_rejects_nonfinite_json_numbers(tmp_path: Path) -> None:
    document = cad2dsl._scad(b"W=10;\n", "panel.scad")
    document["claims"][0]["value"] = float("nan")
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(ConversionError, match="non-finite"):
        load_document(path)
