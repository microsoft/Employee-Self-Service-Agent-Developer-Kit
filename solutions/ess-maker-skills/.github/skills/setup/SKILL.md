---
name: setup
description: >-
  ESS Maker Kit environment setup (onboarding) for the Copilot CLI — the CLI equivalent of the kit's /setup command. Use when the user asks to set up ESS, run setup, onboard the kit, or types /setup. Connects the kit to an already-deployed ESS agent (Dataverse / Power Platform, discover the agent, extract its files, start the MCP server); it does not provision an environment or install ESS.
---

# ESS Maker Kit — Setup (CLI)

CLI-native entry point for the kit's `/setup`. In VS Code `/setup` is a prompt
file; the Copilot CLI has no typed `/setup`, so this skill provides the same flow,
invoked by intent ("set up ESS", "run setup"). The name matches the VS Code
command so the two surfaces stay consistent.

This skill ships **inside** the kit, so the kit root is the `ess-maker-skills`
folder that contains this skill's `.github/skills/` directory. Make that folder the
working directory before running anything.

## Steps

1. **Honor the kit rules first.** Read `.github/copilot-instructions.md` at the kit
   root (persona, communication rules, security boundaries) and follow them — never
   expose internal terminology or narrate which files/commands you use.
2. **Follow onboarding exactly.** Read `src/skills/onboarding/SKILL.md` at the kit
   root and follow it step by step (it is the setup script: Dataverse / Power
   Platform → discover the agent → extract → start the MCP server → optional
   readiness). Every **Message** block is verbatim text to show the user — copy it,
   do not rephrase. Run `python scripts/...` from the kit root.

## What setup does (and doesn't)

`/setup` **connects** the kit to an ESS agent that is **already deployed** in a
Power Platform environment and records its details into `.local/config.json`. It
does **not** create the environment or install ESS. To decide a greenfield
rollout, use the **planner** skill instead — it emits "run setup" as a task.
