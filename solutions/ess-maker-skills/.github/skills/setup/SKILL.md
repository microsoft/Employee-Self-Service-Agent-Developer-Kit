---
name: setup
description: >-
  ESS Maker Kit foundation setup for the Copilot CLI — the CLI equivalent of the kit's /setup command, running the same foundation flow. Use only when the user gives the direct setup invocation "run setup" (the CLI command-equivalent) or types /setup. Do NOT use for open-ended "set up ESS", "set up ESS for the first time", or "where do I start" — those get the first-run welcome, and greenfield planning is the planner. Checks Power Platform and Copilot Studio prerequisites, chooses or creates and locks the environment, configures the preferred unmanaged solution, installs an HR or IT ESS starter (or reuses an installed agent), verifies baseline readiness, binds this workspace, and hands off to /connect.
---

# ESS Maker Kit — Setup (CLI)

CLI-native entry point for the kit's `/setup`. In VS Code `/setup` is a prompt
file; the Copilot CLI has no typed `/setup`, so this skill provides the same flow,
invoked by the direct phrase "run setup" (the CLI command-equivalent). The name
matches the VS Code command so the two surfaces stay consistent.

This skill ships **inside** the kit, so the kit root is the `ess-maker-skills`
folder that contains this skill's `.github/skills/` directory. Make that folder the
working directory before running anything.

## Steps

1. **Honor the kit rules first.** Read `.github/copilot-instructions.md` at the kit
   root (persona, communication rules, security boundaries) and follow them — never
   expose internal terminology or narrate which files/commands you use.
2. **Follow foundation setup exactly.** Read `src/skills/foundation-setup/SKILL.md`
   at the kit root and follow it step by step — it is the single `/setup` entry
   for both hosts. Do not route directly to `src/skills/onboarding/SKILL.md`:
   foundation setup owns environment selection, prerequisites, starter
   installation, and readiness, and invokes onboarding itself only after the
   environment is locked and the foundation is ready. Preserve the assigned plan
   task and environment when handing off, and return to that task afterward.
   Every **Message** block is verbatim text to show the user — copy it, do not
   rephrase. Run `python scripts/...` from the kit root.

## What setup does (and doesn't)

`/setup` stands up the ESS **foundation** in a Power Platform environment, the
same flow in both hosts: it checks the Power Platform and Copilot Studio
prerequisites, chooses or creates and locks the target environment, configures
the preferred unmanaged solution, installs an HR or IT ESS starter (or reuses an
agent already installed there), verifies baseline readiness, binds this workspace
in `.local/config.json`, and hands off to `/connect`. When a plan's environment
and agent already exist, it reuses them and only binds this workspace.
Integrations, authentication, extension packs, and topics are outside setup. To
decide a greenfield rollout first, use the **planner** skill — it emits "run
setup" as a task.
