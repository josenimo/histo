"""Put bin/ and tools/ on sys.path so the unit tests can import the scripts."""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

for d in ("bin", "tools"):
    p = str(REPO / d)
    if p not in sys.path:
        sys.path.insert(0, p)
