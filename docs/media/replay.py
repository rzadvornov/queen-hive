"""Replays the output of a real hive run (demo-run.txt, from the benchmark's discounts task) for the demo GIF.

The recording itself (vhs) can't wait out a several-minute live run, so the GIF shows the real output at a
faster, steady pace instead.
"""

import sys
import time
from pathlib import Path

for line in (Path(__file__).parent / "demo-run.txt").read_text().splitlines():
    print(line, flush=True)
    pause = 0.5 if line.startswith(("👑 →", "   🐝", "👑 🔍")) else 0.12 if line.strip() else 0.05
    time.sleep(pause / float(sys.argv[1]) if len(sys.argv) > 1 else pause)
