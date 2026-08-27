"""SVG structural observation adapter."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from artifact2dsl import ConversionError, claim, document, entity, evidence, finding

__version__ = "0.1.0"
_NUMBER = re.compile(r"^\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*([A-Za-z%]*)\s*$")
_URL_REFERENCE = re.compile(r"url\(\s*#([^)\s]+)\s*\)")


def _tag(value: str) -> str:
    return value.rsplit("}", 1)[-1]


def _numeric(value: str | None) -> tuple[float, str] | None:
    match = _NUMBER.match(value or "")
    return (float(match.group(1)), match.group(2) or "user") if match else None


def convert_source(source: str, path: str, *, content: bytes | None = None) -> dict[str, Any]:
    raw = content if content is not None else source.encode("utf-8")
    if len(raw) > 20 * 1024 * 1024:
        raise ConversionError("SVG exceeds the 20 MiB structural inspection limit")
    try:
        root = ET.fromstring(source)
    except ET.ParseError as exc:
        raise ConversionError(f"invalid SVG XML: {exc}") from exc
    if _tag(root.tag) != "svg":
        raise ConversionError("expected an svg root element")
    entities: list[dict[str, Any]] = []
    claims: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    identifiers: dict[str, int] = {}
    known_ids = {item.attrib["id"] for item in root.iter() if item.attrib.get("id")}
    view_box = root.attrib.get("viewBox", "")
    view_values: list[float] = []
    try:
        view_values = [float(value) for value in view_box.replace(",", " ").split()]
    except ValueError:
        view_values = []
    if len(view_values) != 4:
        findings.append(
            finding(
                "SVG-VIEWBOX-MISSING-001",
                "warning",
                "SVG has no valid four-number viewBox.",
                subject="canvas",
                source_evidence=evidence(pointer="/svg/@viewBox"),
            )
        )
    width = _numeric(root.attrib.get("width"))
    height = _numeric(root.attrib.get("height"))
    if width is None and len(view_values) == 4:
        width = (view_values[2], "user")
    if height is None and len(view_values) == 4:
        height = (view_values[3], "user")
    canvas_attributes = {"viewBox": view_values if len(view_values) == 4 else None, **root.attrib}
    entities.append(
        entity(
            "canvas",
            "svg-canvas",
            path,
            attributes=canvas_attributes,
            source_evidence=evidence(pointer="/svg"),
        )
    )
    if width is not None:
        claims.append(
            claim(
                "svg:canvas:width",
                "vector.canvas",
                "canvas",
                "width",
                width[0],
                unit=width[1],
                source_evidence=evidence(pointer="/svg/@width"),
            )
        )
    if height is not None:
        claims.append(
            claim(
                "svg:canvas:height",
                "vector.canvas",
                "canvas",
                "height",
                height[0],
                unit=height[1],
                source_evidence=evidence(pointer="/svg/@height"),
            )
        )
    if len(view_values) == 4:
        claims.append(
            claim(
                "svg:canvas:viewBox",
                "vector.canvas",
                "canvas",
                "viewBox",
                view_values,
                source_evidence=evidence(pointer="/svg/@viewBox"),
            )
        )

    for ordinal, node in enumerate(root.iter()):
        tag = _tag(node.tag)
        if node is root:
            continue
        declared_id = node.attrib.get("id", "")
        if declared_id:
            identifiers[declared_id] = identifiers.get(declared_id, 0) + 1
        target = f"svg:{tag}:{ordinal}"
        source_evidence = evidence(pointer=f"/svg/{tag}[{ordinal}]")
        entities.append(
            entity(
                target,
                f"svg-{tag}",
                declared_id or tag,
                attributes={
                    "tag": tag,
                    "id": declared_id or None,
                    "attributes": dict(sorted(node.attrib.items())),
                    "text": (node.text or "").strip(),
                },
                source_evidence=source_evidence,
            )
        )
        claims.append(
            claim(f"{target}:tag", "vector.element", target, "tag", tag, source_evidence=source_evidence)
        )
        if declared_id:
            claims.append(
                claim(
                    f"{target}:id",
                    "vector.element",
                    target,
                    "id",
                    declared_id,
                    source_evidence=source_evidence,
                )
            )
        text_value = (node.text or "").strip()
        if text_value:
            claims.append(
                claim(
                    f"{target}:text",
                    "vector.element",
                    target,
                    "text",
                    text_value,
                    source_evidence=source_evidence,
                )
            )
        for name, value in sorted(node.attrib.items()):
            claims.append(
                claim(
                    f"{target}:attr:{name}",
                    "vector.element",
                    target,
                    f"attribute.{name}",
                    value,
                    source_evidence=source_evidence,
                )
            )
            references = list(_URL_REFERENCE.findall(value))
            href = value[1:] if name.rsplit("}", 1)[-1] == "href" and value.startswith("#") else None
            if href:
                references.append(href)
            for referenced in references:
                if referenced not in known_ids:
                    findings.append(
                        finding(
                            "SVG-REFERENCE-MISSING-001",
                            "error",
                            f"Element references missing id #{referenced}.",
                            subject=target,
                            source_evidence=evidence(pointer=f"{source_evidence['pointer']}/@{name}"),
                        )
                    )
    for identifier, count in sorted(identifiers.items()):
        if count > 1:
            findings.append(
                finding(
                    "SVG-ID-DUPLICATE-001",
                    "error",
                    f"SVG id {identifier!r} occurs {count} times.",
                    subject=f"svg-id:{identifier}",
                )
            )
    return document(
        converter="svg2dsl",
        converter_version=__version__,
        path=path,
        media_type="image/svg+xml",
        content=raw,
        namespaces=["vector.canvas", "vector.element"],
        entities=entities,
        claims=claims,
        findings=findings,
        metadata={"elements": len(entities) - 1},
    )


def convert_path(path: str | Path, **_options: Any) -> dict[str, Any]:
    target = Path(path)
    if target.suffix.lower() != ".svg":
        raise ConversionError("svg2dsl accepts only .svg files")
    raw = target.read_bytes()
    return convert_source(raw.decode("utf-8"), target.as_posix(), content=raw)
