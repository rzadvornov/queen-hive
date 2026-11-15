---
name: waggle
description: Session retro for The Hive (alias /retro). Lists what went wrong or took extra time in this session and proposes minimal edits to the hive rules, agents or project memory. Use when the user asks for a waggle or retro, usually at the end of a session.
---
Like the waggle dance, share with the hive what this session taught.

1. Go through this session and list what went wrong: returned briefs, unnecessary steps, unclear briefs, bee mistakes, review findings that should have been caught earlier, wasted tokens.
2. For each item, propose **one minimal edit** that would have prevented it, in one of these places:
   - the project memory: `known-issues.md`, `decisions.md` or `profile.md` in the hive memory folder for this project (under `~/.hive/projects/`)
   - the hive rules: `${CLAUDE_PLUGIN_ROOT}/rules/queen.md`
   - a bee: `${CLAUDE_PLUGIN_ROOT}/agents/<name>.md`
   Show each edit as **before** and **after**.
3. Propose only what actually happened. No edits "just in case".
4. Change nothing until the user approves a specific item. Then apply exactly that item.
