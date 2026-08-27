from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for source in [ROOT / "src", *sorted((ROOT / "packages").glob("*/src"))]:
    sys.path.insert(0, str(source))
