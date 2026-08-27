"""KiCad PCB observation adapter."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from twin_kicad.pcb import inspect_pcb
from twin_kicad.sexp import SexpError, child, children, head, number, parse, text

from artifact2dsl import ConversionError, claim, document, entity, evidence, finding

__version__ = "0.1.0"


def convert_source(source: str, path: str, *, content: bytes | None = None) -> dict[str, Any]:
    raw = content if content is not None else source.encode("utf-8")
    try:
        root = parse(source)
        board = inspect_pcb(root)
    except SexpError as exc:
        raise ConversionError(f"invalid KiCad PCB: {exc}") from exc
    entities: list[dict[str, Any]] = []
    claims: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    references: dict[str, int] = {}
    net_codes: dict[int, str] = {}
    for net in board.nets:
        if net.code in net_codes and net_codes[net.code] != net.name:
            findings.append(
                finding(
                    "PCB-NET-CODE-DUPLICATE-001",
                    "error",
                    f"Net code {net.code} names both {net_codes[net.code]!r} and {net.name!r}.",
                    subject=f"net-code:{net.code}",
                )
            )
        net_codes[net.code] = net.name
        entities.append(entity(f"net:{net.code}", "pcb-net", net.name, attributes={"code": net.code}))
    for ordinal, footprint in enumerate(board.footprints):
        reference = footprint.reference.strip()
        identity = f"component:{reference}" if reference else f"footprint:{footprint.uuid or ordinal}"
        source_evidence = evidence(pointer=identity)
        entities.append(
            entity(
                identity,
                "pcb-footprint",
                reference or footprint.library_id or identity,
                attributes={
                    "reference": reference,
                    "value": footprint.value,
                    "footprint": footprint.library_id,
                    "uuid": footprint.uuid,
                    "layer": footprint.layer,
                    "x": footprint.x,
                    "y": footprint.y,
                    "rotation": footprint.rotation,
                    "pads": len(footprint.pads),
                },
                source_evidence=source_evidence,
            )
        )
        if not reference:
            findings.append(
                finding(
                    "PCB-REFERENCE-MISSING-001",
                    "error",
                    "Placed footprint has no reference.",
                    subject=identity,
                    source_evidence=source_evidence,
                )
            )
            continue
        references[reference] = references.get(reference, 0) + 1
        base = f"pcb:{reference}"
        claims.extend(
            [
                claim(
                    f"{base}:exists",
                    "eda.component",
                    identity,
                    "exists",
                    True,
                    source_evidence=source_evidence,
                ),
                claim(
                    f"{base}:value",
                    "eda.component",
                    identity,
                    "value",
                    footprint.value.strip(),
                    source_evidence=source_evidence,
                ),
                claim(
                    f"{base}:footprint",
                    "eda.component",
                    identity,
                    "footprint",
                    footprint.library_id.strip(),
                    source_evidence=source_evidence,
                ),
            ]
        )
        pad_nets: dict[str, list[tuple[str | None, dict[str, Any]]]] = {}
        for pad_index, pad in enumerate(footprint.pads):
            subject = f"pin:{reference}:{pad.number}"
            pad_evidence = evidence(pointer=f"{identity}/pad:{pad.number}")
            entities.append(
                entity(
                    f"pad:{reference}:{pad.number}:{pad_index}",
                    "pcb-pad",
                    pad.number,
                    attributes={
                        "reference": reference,
                        "number": pad.number,
                        "uuid": pad.uuid,
                        "net": pad.net_name or None,
                        "net_code": pad.net_code,
                        "x": pad.x,
                        "y": pad.y,
                    },
                    source_evidence=pad_evidence,
                )
            )
            pad_nets.setdefault(pad.number, []).append((pad.net_name or None, pad_evidence))
        for pad_number, assignments in pad_nets.items():
            values = {value for value, _item_evidence in assignments}
            subject = f"pin:{reference}:{pad_number}"
            if len(values) > 1:
                findings.append(
                    finding(
                        "PCB-PAD-NET-AMBIGUOUS-001",
                        "error",
                        f"Physical pads sharing {reference}.{pad_number} have different net assignments.",
                        subject=subject,
                        source_evidence=assignments[0][1],
                    )
                )
            claims.append(
                claim(
                    f"pcb-net:{reference}:{pad_number}",
                    "eda.pin-net",
                    subject,
                    "net",
                    assignments[0][0] if len(values) == 1 else sorted(str(value) for value in values),
                    source_evidence=assignments[0][1],
                )
            )
    for reference, count in sorted(references.items()):
        if count > 1:
            findings.append(
                finding(
                    "PCB-REFERENCE-DUPLICATE-001",
                    "error",
                    f"Reference {reference} occurs {count} times.",
                    subject=f"component:{reference}",
                )
            )
    outline_points: list[tuple[float, float]] = []
    unsupported_outline: list[str] = []
    for node in children(root):
        node_head = head(node) or ""
        layer = text(child(node, "layer"), 1)
        if layer != "Edge.Cuts":
            continue
        if node_head in {"gr_line", "gr_rect"}:
            for point_name in ("start", "end"):
                point = child(node, point_name)
                if point is not None:
                    outline_points.append((number(point, 1), number(point, 2)))
        elif node_head.startswith("gr_"):
            unsupported_outline.append(node_head)
    if outline_points:
        min_x = min(item[0] for item in outline_points)
        max_x = max(item[0] for item in outline_points)
        min_y = min(item[1] for item in outline_points)
        max_y = max(item[1] for item in outline_points)
        geometry_evidence = evidence(pointer="Edge.Cuts")
        entities.append(
            entity(
                "board",
                "pcb-outline",
                "board",
                attributes={
                    "min_x": min_x,
                    "max_x": max_x,
                    "min_y": min_y,
                    "max_y": max_y,
                    "width": max_x - min_x,
                    "height": max_y - min_y,
                },
                source_evidence=geometry_evidence,
            )
        )
        claims.extend(
            [
                claim(
                    "pcb:board:width",
                    "board.geometry",
                    "board",
                    "width",
                    max_x - min_x,
                    unit="mm",
                    source_evidence=geometry_evidence,
                ),
                claim(
                    "pcb:board:height",
                    "board.geometry",
                    "board",
                    "height",
                    max_y - min_y,
                    unit="mm",
                    source_evidence=geometry_evidence,
                ),
            ]
        )
    else:
        findings.append(
            finding(
                "PCB-OUTLINE-MISSING-001",
                "warning",
                "No straight Edge.Cuts outline was found.",
                subject="board",
            )
        )
    if unsupported_outline:
        findings.append(
            finding(
                "PCB-OUTLINE-PARTIAL-001",
                "warning",
                "Outline dimensions use straight primitives only; unsupported: "
                + ", ".join(sorted(set(unsupported_outline))),
                subject="board",
                source_evidence=evidence(pointer="Edge.Cuts"),
            )
        )
    return document(
        converter="pcb2dsl",
        converter_version=__version__,
        path=path,
        media_type="application/x-kicad-pcb",
        content=raw,
        namespaces=["eda.component", "eda.pin-net", "board.geometry"],
        entities=entities,
        claims=claims,
        findings=findings,
        metadata={"kicad_version": board.version},
    )


def convert_path(path: str | Path, **_options: Any) -> dict[str, Any]:
    target = Path(path)
    if target.suffix.lower() != ".kicad_pcb":
        raise ConversionError("pcb2dsl accepts only .kicad_pcb files")
    raw = target.read_bytes()
    return convert_source(raw.decode("utf-8"), target.as_posix(), content=raw)
