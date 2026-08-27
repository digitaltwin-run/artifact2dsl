# CONVERT

`artifact2dsl convert ARTIFACT...` chooses an installed converter by suffix.
One input returns one `artifact2dsl.document/v1`; multiple inputs return an
`artifact2dsl.bundle/v1`. Conversion reads regular files only and never writes
the source.

For schematics, add `--kicad-cli` or `--netlist FILE` if pin connectivity is
required. A conversion without a netlist is valid but advertises only the
`eda.component` namespace.
