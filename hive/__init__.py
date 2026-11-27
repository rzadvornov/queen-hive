"""Queen Hive: a Queen model directs cheap worker bees, in Claude Code, Codex or the Gemini CLI."""

import sys
from pathlib import Path

__version__ = "1.8.0"

CORE_DIR = Path(__file__).parent / "core"   # the rules, bees, hooks and skills; a Claude Code plugin
SCRIPTS_DIR = CORE_DIR / "scripts"

# hivecore lives inside the plugin so its hooks can use it without this package.
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
