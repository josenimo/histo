"""Make the scripts in bin/ and tools/ importable by the unit tests.

They are executables rather than an installed package, so there is no import path
to them by default. Adding both directories here keeps the test files themselves
free of sys.path manipulation.
"""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

for d in ("bin", "tools"):
    p = str(REPO / d)
    if p not in sys.path:
        sys.path.insert(0, p)
