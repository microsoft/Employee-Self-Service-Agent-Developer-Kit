---
name: setup
description: >-
  ESS Maker Kit setup for the Copilot CLI — the CLI equivalent of the kit's /setup command, running the same foundation setup flow. Use only when the user gives the direct setup invocation "run setup" (the CLI command-equivalent) or types /setup. Do NOT use for open-ended "set up ESS", "set up ESS for the first time", or "where do I start" — those get the first-run welcome, and greenfield planning is the planner. Chooses the target Power Platform environment (it never creates one), verifies access and agent identity, creates a fresh ESS agent or connects an existing editable Dev agent, brings the agent's local copy into this workspace, and reviews the setup handoff.
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
2. **Follow the `/setup` prompt exactly.** Read `.github/prompts/setup.prompt.md`
   at the kit root and follow it — it is the same `/setup` entry VS Code runs. It
   sends you to `src/skills/foundation-setup/SKILL.md`, whose **Command runtime**
   instructions resolve the Python launcher, and it defines the setup progress
   checklist. Follow the foundation skill step by step: render every **Message**
   block verbatim — copy it, do not rephrase — and present its choices with this
   host's interactive question control. Run every command from the kit root.
3. **Stay on foundation setup.** Do not route to Dataverse foundation or
   onboarding playbooks. Foundation setup owns environment and editable Dev-agent
   selection, workspace materialization, and setup completion.

## What setup does (and doesn't)

`/setup` connects this workspace to an ESS agent in Copilot Studio, the same flow
in both hosts: it chooses the starting point and target Power Platform
environment, verifies access and agent identity, establishes an editable Dev
agent — a fresh ESS agent or one that already exists — brings the agent's local
copy into this workspace, and reviews the setup handoff. It never creates a Power
Platform environment: when none is available, it shows the Power Platform admin
center steps to create one, then lists environments again once it is ready. When
a saved rollout plan pins an environment, setup targets that environment and
never creates or selects a different one. Integrations, authentication, extension
packs, and topics are outside setup. To decide a greenfield rollout first, choose
**Plan my ESS rollout first** when setup offers it (only when no plan is saved),
or use the **planner** skill.
