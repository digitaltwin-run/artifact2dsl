"""Converter discovery without coupling the core to domain parsers."""

from __future__ import annotations

from importlib import import_module
from importlib.metadata import entry_points
from pathlib import Path
from typing import Any, Callable

from .model import ConversionError

Converter = Callable[..., dict[str, Any]]

_FALLBACKS = {
    ".kicad_sch": ("sch2dsl", "convert_path"),
    ".kicad_pcb": ("pcb2dsl", "convert_path"),
    ".svg": ("svg2dsl", "convert_path"),
    ".scad": ("cad2dsl", "convert_path"),
    ".stl": ("cad2dsl", "convert_path"),
    ".step": ("cad2dsl", "convert_path"),
    ".stp": ("cad2dsl", "convert_path"),
    ".dxf": ("cad2dsl", "convert_path"),
}


def converters() -> dict[str, Converter]:
    result: dict[str, Converter] = {}
    try:
        available = entry_points(group="artifact2dsl.converters")
    except TypeError:  # Python 3.11 compatibility with older importlib metadata
        available = entry_points().get("artifact2dsl.converters", [])
    for item in available:
        result[item.name] = item.load()
    for suffix, (module_name, attribute) in _FALLBACKS.items():
        if suffix in result:
            continue
        try:
            result[suffix] = getattr(import_module(module_name), attribute)
        except (ImportError, AttributeError):
            continue
    return result


def convert_path(path: str | Path, **options: Any) -> dict[str, Any]:
    target = Path(path)
    if not target.is_file() or target.is_symlink():
        raise ConversionError(f"artifact is not a regular file: {target}")
    suffix = target.suffix.lower()
    converter = converters().get(suffix)
    if converter is None:
        raise ConversionError(f"no installed converter for {suffix or '<no extension>'}")
    return converter(target, **options)
