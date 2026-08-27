"""Structural CAD observation adapters without a geometry-kernel dependency."""

from __future__ import annotations

import math
import re
import struct
from collections import Counter
from pathlib import Path
from typing import Any

from artifact2dsl import ConversionError, claim, document, entity, evidence, finding

__version__ = "0.1.0"
_VARIABLE = re.compile(
    r"(?<![A-Za-z0-9_])(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*"
    r"(?P<literal>[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*;"
)
_MODULE = re.compile(r"\bmodule\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(")
_INCLUDE = re.compile(r"\b(include|use)\s*<([^>]+)>")
_STEP_ENTITY = re.compile(r"(?m)^\s*#\d+\s*=\s*([A-Z][A-Z0-9_]*)\s*\(")
_STEP_PRODUCT = re.compile(r"PRODUCT\s*\(\s*'([^']*)'", re.IGNORECASE)
_ASCII_VERTEX = re.compile(rb"\bvertex\s+([+-]?[\d.eE]+)\s+([+-]?[\d.eE]+)\s+([+-]?[\d.eE]+)", re.IGNORECASE)


def _mask_scad(source: str) -> str:
    """Mask comments and strings while preserving offsets and line numbers."""
    result = list(source)
    index = 0
    state = "code"
    quote = ""
    while index < len(source):
        current = source[index]
        following = source[index + 1] if index + 1 < len(source) else ""
        if state == "code":
            if current == "/" and following == "/":
                result[index] = result[index + 1] = " "
                state = "line-comment"
                index += 2
                continue
            if current == "/" and following == "*":
                result[index] = result[index + 1] = " "
                state = "block-comment"
                index += 2
                continue
            if current in {'"', "'"}:
                quote = current
                result[index] = " "
                state = "string"
        elif state == "line-comment":
            if current == "\n":
                state = "code"
            else:
                result[index] = " "
        elif state == "block-comment":
            if current == "*" and following == "/":
                result[index] = result[index + 1] = " "
                state = "code"
                index += 2
                continue
            if current != "\n":
                result[index] = " "
        else:
            if current == "\\" and following:
                result[index] = " "
                if following != "\n":
                    result[index + 1] = " "
                index += 2
                continue
            if current == quote:
                state = "code"
            if current != "\n":
                result[index] = " "
        index += 1
    return "".join(result)


def _scad(raw: bytes, path: str) -> dict[str, Any]:
    source = raw.decode("utf-8")
    structural_source = _mask_scad(source)
    entities: list[dict[str, Any]] = []
    claims: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    variables: dict[str, list[tuple[float, int, str]]] = {}
    depth = 0
    for line_number, line in enumerate(structural_source.splitlines(), start=1):
        if depth == 0:
            for match in _VARIABLE.finditer(line):
                value = float(match.group("literal"))
                if math.isfinite(value):
                    variables.setdefault(match.group("name"), []).append(
                        (value, line_number, match.group("literal"))
                    )
        depth += line.count("{") - line.count("}")
        if depth < 0:
            findings.append(
                finding(
                    "CAD-SCAD-BRACE-001",
                    "error",
                    "Closing brace has no matching opening brace.",
                    subject="scad:document",
                    source_evidence=evidence(line=line_number),
                )
            )
            depth = 0
    if depth:
        findings.append(
            finding(
                "CAD-SCAD-BRACE-001",
                "error",
                f"OpenSCAD source ends with brace depth {depth}.",
                subject="scad:document",
            )
        )
    for name, occurrences in sorted(variables.items()):
        if len(occurrences) != 1:
            findings.append(
                finding(
                    "CAD-SCAD-PARAMETER-AMBIGUOUS-001",
                    "error",
                    f"Top-level parameter {name} is assigned {len(occurrences)} times.",
                    subject=f"parameter:{name}",
                    source_evidence=evidence(line=occurrences[0][1]),
                )
            )
            continue
        value, line, literal = occurrences[0]
        subject = f"parameter:{name}"
        source_evidence = evidence(line=line, pointer=subject)
        entities.append(
            entity(
                subject,
                "scad-parameter",
                name,
                attributes={"value": value, "literal": literal},
                source_evidence=source_evidence,
            )
        )
        claims.append(
            claim(
                f"scad:{name}:value",
                "cad.parameter",
                subject,
                "value",
                value,
                source_evidence=source_evidence,
            )
        )
    for index, match in enumerate(_MODULE.finditer(structural_source)):
        name = match.group(1)
        subject = f"module:{name}"
        source_evidence = evidence(line=source.count("\n", 0, match.start()) + 1, pointer=subject)
        entities.append(entity(f"{subject}:{index}", "scad-module", name, source_evidence=source_evidence))
        claims.append(
            claim(
                f"scad:module:{index}:exists",
                "cad.module",
                subject,
                "exists",
                True,
                source_evidence=source_evidence,
            )
        )
    for index, match in enumerate(_INCLUDE.finditer(structural_source)):
        mode, target = match.groups()
        subject = f"dependency:{target}"
        source_evidence = evidence(line=source.count("\n", 0, match.start()) + 1, pointer=subject)
        entities.append(
            entity(
                f"{subject}:{index}",
                "scad-dependency",
                target,
                attributes={"mode": mode},
                source_evidence=source_evidence,
            )
        )
        claims.append(
            claim(
                f"scad:dependency:{index}:mode",
                "cad.dependency",
                subject,
                "mode",
                mode,
                source_evidence=source_evidence,
            )
        )
    return document(
        converter="cad2dsl",
        converter_version=__version__,
        path=path,
        media_type="application/x-openscad",
        content=raw,
        namespaces=["cad.parameter", "cad.module", "cad.dependency"],
        entities=entities,
        claims=claims,
        findings=findings,
        metadata={"format": "openscad"},
    )


def _bounds(vertices: list[tuple[float, float, float]]) -> dict[str, float] | None:
    if not vertices:
        return None
    return {
        "min_x": min(item[0] for item in vertices),
        "max_x": max(item[0] for item in vertices),
        "min_y": min(item[1] for item in vertices),
        "max_y": max(item[1] for item in vertices),
        "min_z": min(item[2] for item in vertices),
        "max_z": max(item[2] for item in vertices),
    }


def _stl(raw: bytes, path: str) -> dict[str, Any]:
    vertices: list[tuple[float, float, float]] = []
    triangle_count = 0
    format_name = "ascii"
    nonfinite = False
    incomplete = False
    if len(raw) >= 84:
        declared = struct.unpack_from("<I", raw, 80)[0]
        if 84 + declared * 50 == len(raw):
            format_name = "binary"
            triangle_count = declared
            for index in range(declared):
                values = struct.unpack_from("<12fH", raw, 84 + index * 50)
                triangle_vertices = [tuple(values[3:6]), tuple(values[6:9]), tuple(values[9:12])]
                nonfinite = nonfinite or any(
                    not math.isfinite(coordinate) for vertex in triangle_vertices for coordinate in vertex
                )
                vertices.extend(triangle_vertices)
    if format_name == "ascii":
        for match in _ASCII_VERTEX.finditer(raw):
            vertex = tuple(float(value) for value in match.groups())
            nonfinite = nonfinite or any(not math.isfinite(coordinate) for coordinate in vertex)
            vertices.append(vertex)
        incomplete = bool(len(vertices) % 3)
        triangle_count = len(vertices) // 3
    bbox = None if nonfinite else _bounds(vertices)
    entities = [
        entity(
            "mesh", "triangle-mesh", Path(path).name, attributes={"triangles": triangle_count, "bounds": bbox}
        )
    ]
    claims = [claim("stl:mesh:triangles", "cad.mesh", "mesh", "triangle_count", triangle_count)]
    if bbox:
        for name, value in bbox.items():
            claims.append(claim(f"stl:mesh:{name}", "cad.mesh", "mesh", f"bounds.{name}", value))
    findings: list[dict[str, Any]] = []
    if not triangle_count:
        findings.append(
            finding(
                "CAD-STL-EMPTY-001",
                "error",
                "STL contains no complete triangles.",
                subject="mesh",
            )
        )
    if incomplete:
        findings.append(
            finding(
                "CAD-STL-INCOMPLETE-001",
                "error",
                "ASCII STL vertex count is not divisible by three.",
                subject="mesh",
            )
        )
    if nonfinite:
        findings.append(
            finding(
                "CAD-STL-NONFINITE-001",
                "error",
                "STL contains a NaN or infinite vertex coordinate.",
                subject="mesh",
            )
        )
    return document(
        converter="cad2dsl",
        converter_version=__version__,
        path=path,
        media_type="model/stl",
        content=raw,
        namespaces=["cad.mesh"],
        entities=entities,
        claims=claims,
        findings=findings,
        metadata={"format": format_name},
    )


def _step(raw: bytes, path: str) -> dict[str, Any]:
    source = raw.decode("utf-8", errors="replace")
    counts = Counter(_STEP_ENTITY.findall(source))
    products = _STEP_PRODUCT.findall(source)
    entities = [
        entity(f"step-type:{name}", "step-entity-type", name, attributes={"count": count})
        for name, count in sorted(counts.items())
    ]
    claims = [
        claim(f"step:{name}:count", "cad.brep", f"entity-type:{name}", "count", count)
        for name, count in sorted(counts.items())
    ]
    for index, name in enumerate(products):
        entities.append(entity(f"product:{index}", "step-product", name))
        claims.append(claim(f"step:product:{index}:name", "cad.product", f"product:{index}", "name", name))
    findings = []
    if "HEADER;" not in source or "DATA;" not in source or "END-ISO-10303-21;" not in source:
        findings.append(
            finding(
                "CAD-STEP-STRUCTURE-001",
                "error",
                "STEP exchange file is missing HEADER, DATA or final marker.",
                subject="step:document",
            )
        )
    return document(
        converter="cad2dsl",
        converter_version=__version__,
        path=path,
        media_type="model/step",
        content=raw,
        namespaces=["cad.brep", "cad.product"],
        entities=entities,
        claims=claims,
        findings=findings,
        metadata={"format": "step", "entity_count": sum(counts.values())},
    )


def _dxf(raw: bytes, path: str) -> dict[str, Any]:
    if raw.startswith(b"AutoCAD Binary DXF"):
        raise ConversionError("cad2dsl supports ASCII DXF only; binary DXF needs a dedicated parser")
    source = raw.decode("utf-8", errors="replace").replace("\r\n", "\n")
    lines = source.splitlines()
    findings: list[dict[str, Any]] = []
    if len(lines) % 2:
        findings.append(
            finding(
                "CAD-DXF-PAIR-001",
                "error",
                "ASCII DXF has an odd number of group-code/value lines.",
                subject="dxf:document",
            )
        )
    pairs = [(lines[index].strip(), lines[index + 1].strip()) for index in range(0, len(lines) - 1, 2)]
    section = ""
    expect_section = False
    counts: Counter[str] = Counter()
    sections: set[str] = set()
    for code, value in pairs:
        if code == "0" and value == "SECTION":
            expect_section = True
            continue
        if expect_section and code == "2":
            section = value
            sections.add(section)
            expect_section = False
            continue
        if code == "0" and value == "ENDSEC":
            section = ""
        elif section == "ENTITIES" and code == "0":
            counts[value] += 1
    entities = [
        entity(f"dxf-entity:{name}", "dxf-entity-type", name, attributes={"count": count})
        for name, count in sorted(counts.items())
    ]
    claims = [
        claim(f"dxf:{name}:count", "cad.drawing", f"entity-type:{name}", "count", count)
        for name, count in sorted(counts.items())
    ]
    if "ENTITIES" not in sections:
        findings.append(
            finding(
                "CAD-DXF-ENTITIES-MISSING-001",
                "warning",
                "DXF has no ENTITIES section.",
                subject="dxf:document",
            )
        )
    return document(
        converter="cad2dsl",
        converter_version=__version__,
        path=path,
        media_type="image/vnd.dxf",
        content=raw,
        namespaces=["cad.drawing"],
        entities=entities,
        claims=claims,
        findings=findings,
        metadata={"format": "dxf", "sections": sorted(sections)},
    )


def convert_path(path: str | Path, **_options: Any) -> dict[str, Any]:
    target = Path(path)
    raw = target.read_bytes()
    suffix = target.suffix.lower()
    if suffix == ".scad":
        return _scad(raw, target.as_posix())
    if suffix == ".stl":
        return _stl(raw, target.as_posix())
    if suffix in {".step", ".stp"}:
        return _step(raw, target.as_posix())
    if suffix == ".dxf":
        return _dxf(raw, target.as_posix())
    raise ConversionError("cad2dsl accepts .scad, .stl, .step, .stp and .dxf")
