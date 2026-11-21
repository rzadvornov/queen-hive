---
name: waggle
description: Session retro for The Hive (alias /retro). Lists what went wrong or took extra time in a hive job and proposes minimal edits to the hive rules, agents or project memory. Use when the user asks for a waggle or retro, and after each finished hive job.
---
Like the waggle dance, share with the hive what this job taught.

1. **Get the facts.** If the job happened in this conversation, use what you saw. Otherwise run
   `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/lastrun.py" "$PWD"`: it prints the last recorded run (returned briefs,
   failed checks and reports, acceptance, review findings, cost by stage).
2. **Read `retro-log.md`** in the project's hive memory folder (under `~/.hive/projects/`). Don't propose again an edit
   the user rejected, unless this job gives new evidence for it.
3. **List at most 3 items**, the most costly first: returned briefs, unclear briefs, bee mistakes, review findings that
   should have been caught earlier, wasted tokens. Each item names its evidence: the brief ID, the failed command or
   the review finding. Propose only what actually happened, no edits "just in case". If nothing went wrong, say so.
4. For each item, propose **one minimal edit** that would have prevented it, shown as **before** and **after**, in one of:
   - the project memory: `known-issues.md`, `decisions.md` or `profile.md` in the hive memory folder
   - the hive rules: `rules/queen.md` in the hive's plugin folder (your instructions name it; else `${CLAUDE_PLUGIN_ROOT}`)
   - a bee: `agents/<name>.md` in the same plugin folder
5. End your message after the list and wait for the user's answer. Change nothing until the user approves a specific
   item, then apply exactly that item.
6. Append one line per item to `retro-log.md`: `date · approved | rejected · the edit, in a few words`.

The retro and applying approved items are not jobs: no briefs, no review and **no `hive-summary` block**.
