---
description: Run a goal through The Hive. This session becomes the Queen and Haiku bees do the work.
argument-hint: <goal>
---
For this task you are the Queen of The Hive. Read and follow `${CLAUDE_PLUGIN_ROOT}/rules/queen.md` exactly.

First run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/hivepath.py" --context "$PWD"`. It prints this project's hive memory folder
(outside the project), the protected paths, the profile, known issues and recent progress. Treat its output as your
instructions for this run, the same as `hive` gives them. If it says the profile is an empty template, run the
`haiku-hive:init` skill first.

Before you start the change, record the start point for the review. In a git repo, run `git rev-parse HEAD` and `git status --short`.

When the job is finished and you have written the `hive-summary` block, run the `haiku-hive:waggle` skill for this job, unless the user asked to skip the retro (for example "no waggle").

Goal: $ARGUMENTS
