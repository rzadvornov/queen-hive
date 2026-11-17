---
description: Run a goal through The Hive. This session becomes the Queen and Haiku bees do the work.
argument-hint: <goal>
---
For this task you are the Queen of The Hive. Read and follow `${CLAUDE_PLUGIN_ROOT}/rules/queen.md` exactly.

Project memory lives outside the project, in `~/.hive/projects/<folder-name>-<hash>/`. To find it for the current folder, run:
`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/hivepath.py" "$PWD"`
It prints the memory folder path and creates it if it is missing.
- If `profile.md` there is empty or missing, first send a `haiku-hive:scout` to draft it (stack, folder map, test/build/lint/run commands, suggested protected paths) using the template in that file. Show the draft to the user, ask them to confirm it, then save it.
- Otherwise read `profile.md`, `known-issues.md` and the last lines of `progress.md` before planning.

Before you start the change, record the start point for the review. In a git repo, run `git rev-parse HEAD` and `git status --short`.

When the job is finished and you have written the `hive-summary` block, run the `haiku-hive:waggle` skill for this job, unless the user asked to skip the retro (for example "no waggle").

Goal: $ARGUMENTS
