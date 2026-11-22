"""The Hive: a Queen model directs Haiku worker bees."""

import sys
from pathlib import Path

__version__ = "0.2.0"

PLUGIN_DIR = Path(__file__).parent / "plugin"
SCRIPTS_DIR = PLUGIN_DIR / "scripts"

# hivecore lives inside the plugin so its hooks can use it without this package.
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
