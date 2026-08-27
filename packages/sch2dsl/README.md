# sch2dsl

Read-only conversion of KiCad schematics to `artifact2dsl.document/v1`.
Placed symbols become `eda.component` claims. When an authoritative KiCad XML
netlist is supplied, pins also become `eda.pin-net` claims. The package uses
`twin-kicad`; it does not infer logical connectivity from drawing geometry.

```bash
sch2dsl panel.kicad_sch --netlist panel.xml > panel.sch.dsl.json
```
