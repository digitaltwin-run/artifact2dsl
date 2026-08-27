# pcb2dsl

Read-only conversion of KiCad boards to `artifact2dsl.document/v1`. It reuses
the typed `twin-kicad` PCB model and exposes components and pad-net assignments
in the same namespaces as `sch2dsl`.

```bash
pcb2dsl panel.kicad_pcb > panel.pcb.dsl.json
```
