from artifact2dsl.cli_support import converter_main

from . import convert_path


def main(argv: list[str] | None = None) -> int:
    return converter_main(convert_path, "Convert SVG structure to evidence-bound observation DSL.", argv)
