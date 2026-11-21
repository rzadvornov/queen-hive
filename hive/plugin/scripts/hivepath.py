"""Print the hive memory folder for a project folder, creating it if missing.

    python3 hivepath.py DIR             # the memory folder
    python3 hivepath.py --context DIR   # memory folder, protected paths, profile, known issues, recent progress
"""

import sys

from hivecore import ensure_project, run_context

if __name__ == "__main__":
    args = sys.argv[1:]
    if args[:1] == ["--context"]:
        print(run_context(args[1] if len(args) > 1 else "."))
    else:
        print(ensure_project(args[0] if args else "."))
