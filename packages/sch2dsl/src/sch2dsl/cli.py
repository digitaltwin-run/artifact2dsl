from __future__ import annotations

import argparse

from artifact2dsl.cli_support import converter_main

from . import convert_path


def _arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--netlist", help="Authoritative KiCad XML netlist exported by kicad-cli.")
    parser.add_argument(
        "--kicad-cli", action="store_true", help="Export the authoritative XML netlist automatically."
    )


def main(argv: list[str] | None = None) -> int:
    return converter_main(
        convert_path,
        "Convert a KiCad schematic to evidence-bound observation DSL.",
        argv,
        add_arguments=_arguments,
        options=lambda args: {"netlist": args.netlist, "auto_netlist": args.kicad_cli},
    )
