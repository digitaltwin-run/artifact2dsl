# cad2dsl

Read-only structural conversion for CAD artifacts:

- OpenSCAD: top-level numeric parameters, modules and includes;
- STL: triangle count and bounding box;
- STEP: entity-type counts and product names;
- ASCII DXF: section/entity counts.

The package does not pretend to be a full CAD kernel. Unsupported or ambiguous
facts remain findings. `scad2dsl` is an alias of the focused CAD CLI.

```bash
cad2dsl panel.scad > panel.cad.dsl.json
```
