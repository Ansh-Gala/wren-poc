"""Shared entry-point setup for scripts/.

Puts the project root on sys.path and forces UTF-8 on stdout/stderr. The
second part matters on Windows: Wren's own output contains box-drawing and
warning glyphs that the cp1252 console default cannot encode, and a report
should not die on a character.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

for stream in (sys.stdout, sys.stderr):
    reconfigure = getattr(stream, "reconfigure", None)
    if reconfigure is not None:
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass
