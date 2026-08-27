"""KiCad schematic observation adapter."""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from twin_kicad.netlist import NetlistError, parse_netlist_xml
from twin_kicad.sexp import SexpError, child, children, head, number, parse, text

from artifact2dsl import ConversionError, claim, document, entity, evidence, finding

__version__ = "0.1.0"


def _line(source: str, offset: int) -> int:
    return source.count("\n", 0, max(0, offset)) + 1


def _properties(node: Any) -> dict[str, str]:
    return {text(item, 1): text(item, 2) for item in children(node, "property") if text(item, 1)}


def convert_source(
    source: str,
    path: str,
    *,
    content: bytes | None = None,
    netlist_xml: str | None = None,
) -> dict[str, Any]:
    raw = content if content is not None else source.encode("utf-8")
    try:
        root = parse(source)
    except SexpError as exc:
        raise ConversionError(f"invalid KiCad schematic: {exc}") from exc
    if head(root) != "kicad_sch":
        raise ConversionError("expected a kicad_sch root expression")
    namespaces = ["eda.component"]
    entities: list[dict[str, Any]] = []
    claims: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    references: dict[str, int] = {}
    placed = children(root, "symbol")
    for ordinal, node in enumerate(placed):
        fields = _properties(node)
        reference = fields.get("Reference", "").strip()
        value = fields.get("Value", "").strip()
        footprint = fields.get("Footprint", "").strip()
        uuid = text(child(node, "uuid"), 1)
        lib_id = text(child(node, "lib_id"), 1)
        at = child(node, "at")
        identity = f"component:{reference}" if reference else f"symbol:{uuid or ordinal}"
        source_evidence = evidence(pointer=identity, line=_line(source, node.start))
        entities.append(
            entity(
                identity,
                "schematic-symbol",
                reference or lib_id or identity,
                attributes={
                    "reference": reference,
                    "value": value,
                    "footprint": footprint,
                    "library_id": lib_id,
                    "uuid": uuid,
                    "x": number(at, 1),
                    "y": number(at, 2),
                    "rotation": number(at, 3),
                },
                source_evidence=source_evidence,
            )
        )
        if not reference:
            findings.append(
                finding(
                    "SCH-REFERENCE-MISSING-001",
                    "error",
                    "Placed symbol has no Reference property.",
                    subject=identity,
                    source_evidence=source_evidence,
                )
            )
            continue
        references[reference] = references.get(reference, 0) + 1
        base = f"sch:{reference}"
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
                    value,
                    source_evidence=source_evidence,
                ),
                claim(
                    f"{base}:footprint",
                    "eda.component",
                    identity,
                    "footprint",
                    footprint,
                    source_evidence=source_evidence,
                ),
            ]
        )
        if not footprint and not reference.startswith("#"):
            findings.append(
                finding(
                    "SCH-FOOTPRINT-MISSING-001",
                    "warning",
                    "Placed symbol has no footprint assignment.",
                    subject=identity,
                    source_evidence=source_evidence,
                )
            )
    for reference, count in sorted(references.items()):
        if count > 1:
            findings.append(
                finding(
                    "SCH-REFERENCE-DUPLICATE-001",
                    "error",
                    f"Reference {reference} occurs {count} times.",
                    subject=f"component:{reference}",
                )
            )

    if netlist_xml is not None:
        try:
            netlist = parse_netlist_xml(netlist_xml)
        except NetlistError as exc:
            raise ConversionError(str(exc)) from exc
        namespaces.append("eda.pin-net")
        for net in netlist.nets:
            net_identity = f"net:{net.name or net.code}"
            entities.append(
                entity(
                    net_identity,
                    "schematic-net",
                    net.name or net.code,
                    attributes={
                        "code": net.code,
                        "nodes": len(net.nodes),
                    },
                    source_evidence=evidence(pointer=f"net:{net.code}"),
                )
            )
            technical_unconnected = net.name.startswith("unconnected-(")
            for node_index, node in enumerate(net.nodes):
                if node.reference.startswith("#"):
                    continue
                subject = f"pin:{node.reference}:{node.pin}"
                claims.append(
                    claim(
                        f"sch-net:{net.code}:{node_index}:{node.reference}:{node.pin}",
                        "eda.pin-net",
                        subject,
                        "net",
                        None if technical_unconnected else net.name,
                        source_evidence=evidence(pointer=f"net:{net.code}/node:{node_index}"),
                    )
                )
        netlist_references = {
            item.reference for item in netlist.components if not item.reference.startswith("#")
        }
        source_references = set(references)
        for reference in sorted(source_references ^ netlist_references):
            findings.append(
                finding(
                    "SCH-NETLIST-DRIFT-001",
                    "error",
                    f"Reference {reference} is present only in "
                    f"{'the schematic source' if reference in source_references else 'the exported netlist'}.",
                    subject=f"component:{reference}",
                )
            )

    version = text(child(root, "version"), 1)
    return document(
        converter="sch2dsl",
        converter_version=__version__,
        path=path,
        media_type="application/x-kicad-schematic",
        content=raw,
        namespaces=namespaces,
        entities=entities,
        claims=claims,
        findings=findings,
        metadata={
            "kicad_version": int(version) if version.isdigit() else None,
            "netlist": netlist_xml is not None,
        },
    )


def _export_netlist(path: Path, executable: str | None = None) -> str:
    binary = executable or os.environ.get("KICAD_CLI", "kicad-cli")
    with tempfile.TemporaryDirectory(prefix="sch2dsl-") as workdir:
        output = Path(workdir) / "netlist.xml"
        try:
            process = subprocess.run(
                [binary, "sch", "export", "netlist", "--format", "kicadxml", "-o", str(output), str(path)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=120,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ConversionError(f"cannot run kicad-cli netlist export: {exc}") from exc
        if process.returncode != 0 or not output.is_file():
            detail = (process.stderr or process.stdout).strip()[-800:]
            raise ConversionError(f"kicad-cli netlist export failed: {detail or process.returncode}")
        return output.read_text(encoding="utf-8")


def convert_path(
    path: str | Path,
    *,
    netlist: str | Path | None = None,
    auto_netlist: bool = False,
    kicad_cli: str | None = None,
    **_options: Any,
) -> dict[str, Any]:
    target = Path(path)
    if target.suffix.lower() != ".kicad_sch":
        raise ConversionError("sch2dsl accepts only .kicad_sch files")
    raw = target.read_bytes()
    source = raw.decode("utf-8")
    if netlist and auto_netlist:
        raise ConversionError("choose either an existing --netlist or --kicad-cli export")
    netlist_xml = Path(netlist).read_text(encoding="utf-8") if netlist else None
    if auto_netlist:
        netlist_xml = _export_netlist(target.resolve(), kicad_cli)
    return convert_source(source, target.as_posix(), content=raw, netlist_xml=netlist_xml)
