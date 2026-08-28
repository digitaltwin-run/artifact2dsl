from __future__ import annotations

from scripts.check_panel9 import parity_problems


def test_panel9_check_blocks_component_conflicts() -> None:
    parity = {
        "summary": {
            "CONFLICT": 3,
            "MISSING_LEFT": 0,
            "MISSING_RIGHT": 0,
            "UNEVALUABLE": 0,
            "source_errors": 0,
        }
    }

    assert parity_problems(parity) == ["SCH-PCB CONFLICT=3"]
