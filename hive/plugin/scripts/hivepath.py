"""Print the hive memory folder for a project folder, creating it if missing."""

import sys

from hivecore import ensure_project

if __name__ == "__main__":
    print(ensure_project(sys.argv[1] if len(sys.argv) > 1 else "."))
