"""Shared CLI projection used by every focused converter."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable

from .model import ConversionError


def emit(value: dict[str, Any], output: str | None, pretty: bool) -> None:
    text = (
        json.dumps(
            value, ensure_ascii=False, indent=2 if pretty else None, separators=None if pretty else (",", ":")
        )
        + "\n"
    )
    if output:
        Path(output).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)


def converter_main(
    converter: Callable[..., dict[str, Any]],
    description: str,
    argv: list[str] | None = None,
    *,
    add_arguments: Callable[[argparse.ArgumentParser], None] | None = None,
    options: Callable[[argparse.Namespace], dict[str, Any]] | None = None,
) -> int:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("artifact")
    parser.add_argument("-o", "--output")
    parser.add_argument("--compact", action="store_true")
    if add_arguments:
        add_arguments(parser)
    args = parser.parse_args(argv)
    try:
        value = converter(Path(args.artifact), **(options(args) if options else {}))
        emit(value, args.output, not args.compact)
        return 1 if any(item.get("severity") in {"error", "critical"} for item in value["findings"]) else 0
    except (ConversionError, OSError, UnicodeError, ValueError) as exc:
        print(f"{parser.prog}: {exc}", file=sys.stderr)
        return 2
