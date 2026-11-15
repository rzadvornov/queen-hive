"""The Hive: a Queen model directs Haiku worker bees."""

import sys
import warnings
from pathlib import Path

__version__ = "0.1.0"

PLUGIN_DIR = Path(__file__).parent / "plugin"
SCRIPTS_DIR = PLUGIN_DIR / "scripts"

# hivecore lives inside the plugin so its hooks can use it without this package.
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

# Read-only tools are auto-approved on purpose; the SDK warns that can_use_tool won't see them.
warnings.filterwarnings("ignore", message="can_use_tool will not be invoked")
