# artifact2dsl

`artifact2dsl` converts engineering artifacts into one evidence-bound,
read-only JSON AST and compares facts that are declared comparable. The
workspace publishes focused Python packages instead of hiding every parser in
one product:

| Package | Inputs | Reused boundary |
|---|---|---|
| `sch2dsl` | `.kicad_sch`, optional KiCad XML netlist | `twin-kicad` S-expressions and netlist model |
| `pcb2dsl` | `.kicad_pcb` | `twin-kicad` PCB model; straight `Edge.Cuts` dimensions |
| `svg2dsl` | `.svg` | Python XML structure, no raster/vision guesses |
| `cad2dsl` | `.scad`, `.stl`, `.step/.stp`, ASCII `.dxf` | conservative format-specific structural readers |
| `artifact2dsl` | all installed adapters or existing DSL JSON | discovery, bundles, mappings and comparison |

`scad2dsl` is a CLI alias provided by `cad2dsl`. New domains plug in through
the `artifact2dsl.converters` entry-point group. A PNG or Markdown renderer
does not get a package merely because it is a file extension: a converter is
added when it can expose deterministic domain facts and evidence.

## Why this is a different DSL from an edit plan

The canonical document is `artifact2dsl.document/v1`. It contains:

- the native source path, media type, byte size and SHA-256;
- stable entities such as `component:R1`, `pin:U1:GP14`, `parameter:W`;
- typed claims grouped into explicit namespaces;
- source pointers/lines as evidence;
- deterministic findings;
- `authority=observation_only_no_execution_grant`.

It never contains an apply URL, write grant or inferred human decision.
TwinStudio's change DSL may consume an observation later, but it remains a
separate propose/approve/apply process.

## Install from the workspace

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/pip install -e packages/sch2dsl -e packages/pcb2dsl \
  -e packages/svg2dsl -e packages/cad2dsl
```

Each focused package can also be installed and used separately.

## Convert

```bash
sch2dsl pcb/panel9.kicad_sch --kicad-cli > panel9.sch.dsl.json
pcb2dsl pcb/panel9.kicad_pcb > panel9.pcb.dsl.json
svg2dsl drawings/01-widok-klawiatury.svg > keyboard.svg.dsl.json
cad2dsl drawings/panel-frame.scad > panel-frame.cad.dsl.json

# Dispatcher selected by suffix
artifact2dsl convert pcb/panel9.kicad_sch pcb/panel9.kicad_pcb
```

`sch2dsl --kicad-cli` asks Eeschema for the authoritative logical netlist.
Without it the document still contains placed components, but deliberately
does not guess connectivity from wires or labels. An existing export can be
passed with `--netlist panel.xml`.

## Validate between artifacts

Artifacts sharing a namespace compare automatically:

```bash
artifact2dsl validate panel.kicad_sch panel.kicad_pcb --kicad-cli
```

For distinct namespaces the relationship must be explicit. This compares
OpenSCAD parameters `W/H` to the board outline with 0.01 mm tolerance:

```bash
artifact2dsl validate drawings/panel-frame.scad pcb/panel9.kicad_pcb \
  --rules examples/panel-dimensions.rules.json
```

The result is `artifact2dsl.validation/v1` and distinguishes:

- `MATCH` — both evidence-bound facts agree;
- `CONFLICT` — both exist but differ;
- `MISSING_LEFT` / `MISSING_RIGHT` — absence is not treated as zero;
- `UNEVALUABLE` — selectors are ambiguous or values cannot be compared.

Any non-match or source-level error blocks the CLI (`exit 1`). Conversion
failures and malformed rules return `exit 2`.

## Current panel9 evidence

The first real run found two different classes of result:

- OpenSCAD `W=148`, `H=64` matches PCB `Edge.Cuts` exactly;
- all 81 SCH pin-net claims match PCB after authoritative Eeschema export;
- SCH and PCB share all 17 component references, but currently have 15
  metadata conflicts: capacitor values/footprints, the RJ45 footprint variant
  and nine switch display values. These are now visible facts; policy or a
  human must decide which are defects and which are allowed presentation
  differences.

This is the intended distinction: electrical connectivity can pass while
BOM/footprint metadata drift remains visible.

## Architecture

```text
native files
   │
   ├── sch2dsl ─┐
   ├── pcb2dsl ─┤
   ├── svg2dsl ─┼── artifact2dsl.document/v1
   └── cad2dsl ─┘              │
                               ├── shared namespaces (automatic)
                               └── explicit rules (mapped)
                                           │
                              artifact2dsl.validation/v1
```

The core has no CAD or EDA parser dependency. Domain packages own extraction;
the comparator owns only selection, typed equality/tolerance and factual gaps.
Project authority, allowed divergence and remediation belong in external
manifests such as `wellmanifest/pcb`, not inside the converters.

## Development

```bash
make check
make wheel-smoke
make panel9
```

`make panel9` treats reported component metadata conflicts as reviewable drift,
but fails on missing/ambiguous claims, source errors or geometry mismatch. To
include authoritative electrical parity, provide a KiCad XML export:

```bash
PANEL9_NETLIST=/path/to/panel9.xml make panel9
```

The workspace adopts `wellmanifest.dsl/manifest/v1`; the observation AST is
canonical JSON and all projections are descriptive/read-only.
