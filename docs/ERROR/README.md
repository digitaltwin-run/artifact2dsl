# Error catalog

Converter findings use stable domain prefixes (`SCH-*`, `PCB-*`, `SVG-*`,
`CAD-*`). Cross-artifact validation adds `ARTIFACT-DRIFT-001` for unequal facts
and `ARTIFACT-GAP-001` for missing or unevaluable facts. The JSON result retains
the exact source hash and evidence pointer for both sides.
