"""Run a Done-when command and print only its verdict and the last lines of its output.

    python3 check.py "npm test"            # PASS · exit 0 · 4.2s   + the last 5 lines
    python3 check.py --lines 15 "pytest"   # more of the output, e.g. to write a fix brief

The Queen re-runs every check herself, but she needs the verdict, not the whole log: each line of output
she reads is paid for again on every later turn. Stdlib only.
"""

import subprocess
import sys
import time


def main(argv: list[str]) -> int:
    lines = 5
    if argv[:1] == ["--lines"] and len(argv) > 2:
        lines, argv = int(argv[1]), argv[2:]
    if not argv:
        print("usage: check.py [--lines N] COMMAND")
        return 2
    command = " ".join(argv)
    started = time.time()
    try:
        done = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=900)
        code, output = done.returncode, (done.stdout + done.stderr).strip()
    except subprocess.TimeoutExpired:
        code, output = None, "timed out after 900s"
    verdict = "PASS" if code == 0 else "FAIL"
    print(f"{verdict} · exit {code} · {time.time() - started:.1f}s")
    tail = [line for line in output.splitlines() if line.strip()][-lines:]
    if tail:
        print("\n".join(tail))
    return 0 if code == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
