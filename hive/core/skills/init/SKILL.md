---
name: init
description: Draft or refresh a project's hive profile (stack, folder map, commands, protected paths, notes) in the hive memory folder. Use when the profile is an empty template, or when the user asks to set up or refresh the hive for a project.
---
1. Find the memory folder: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/hivepath.py" "$PWD"`. The profile is `profile.md` there.
2. Send one `queen-hive:scout` (description `S0 draft profile`) with the rules below and the current `profile.md` as the template.
3. Show the user the draft and ask them to confirm or correct it, especially **Commands** and **Protected paths**.
4. Save the confirmed profile to `profile.md` in the memory folder. Never write it into the project.

## Profile rules
Read the project (README, manifests, top-level folders, test setup) and return the profile in exactly the template's Markdown structure:
- Stack: languages, frameworks, package manager, runtime versions if stated.
- Folder map: the 5-15 most important folders/files, one line each, what they hold.
- Commands: real commands that work in this project (check package scripts, Makefile, CI config, README).
- Protected paths: only human-owned acceptance/spec folders or files that agents must never edit. Do not protect normal unit test folders.
- Notes: conventions worth knowing (style, architecture rules), at most 5 bullets.
