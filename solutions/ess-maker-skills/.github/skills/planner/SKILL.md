---
name: planner
description: >-
  Plan an ESS rollout with the ESS Maker Kit from the Copilot CLI — the CLI equivalent of the kit's /planner command. Generate a grounded scenario plan and atomic, role-owned tasks, or answer "what am I assigned?". Use when the user asks to plan an ESS deployment, set up ESS for the first time, "where do I start / how do I get started", or types /planner. The planner is the one experience allowed before setup.
---

# ESS Maker Kit — Planner (CLI)

CLI-native entry point for the kit's `/planner`. In VS Code `/planner` is a prompt
file; the Copilot CLI has no typed `/planner`, so this skill provides the same
flow, invoked by intent ("plan an ESS rollout", "I want to set up ESS, where do I
start?", "what am I assigned?"). The name matches the VS Code command so the two
surfaces stay consistent.

This skill ships **inside** the kit; the kit root is the `ess-maker-skills` folder
that contains this skill's `.github/skills/` directory. Make it the working
directory before running anything.

## Steps

1. **Honor the kit rules first.** Read `.github/copilot-instructions.md` at the kit
   root and follow it (persona, communication rules — never narrate files/commands).
2. **Follow the planner exactly.** Read `src/skills/planner/SKILL.md` at the kit
   root and follow it. It **leads with a resume check**: it first pulls the shared
   plan (invisibly) and, if a plan exists — freshly pulled or already in
   `workspace/plan/plan.json` — shows its latest state and the role-gated tasks
   the person can pick up, do **not** re-run the interview or re-ask the
   objective. Only start a new plan if none exists (or on explicit confirmation);
   once built, it is published to the shared planner. Run
   `python scripts/planner/cli.py ...` from the kit root.

## What the planner does

It authors a local, structured **Plan** for an ESS rollout: grounds itself on
Microsoft Learn, interviews for what it can't ground, emits atomic tasks each owned
by a role and a person, and captures what each task produced. Its first task is
usually the **Power Platform admin running `/setup`**; once that pins the
environment, other personas are nudged to run `/setup` to connect their own kit to
it. To run environment setup directly (not plan), use the **setup** skill.
