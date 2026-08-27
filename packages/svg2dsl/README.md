# svg2dsl

Dependency-free structural SVG conversion. The result contains canvas and
element claims, duplicate/missing reference diagnostics and source evidence.
It never rasterizes the drawing or treats vision output as geometry truth.

```bash
svg2dsl drawing.svg > drawing.svg.dsl.json
```
