---
name: roles
description: >-
  Attest that a person holds an ESS rollout role (Workday admin, ServiceNow admin, ServiceNow knowledge manager) so the shared plan's role-owned tasks become visible to them — the CLI equivalent of the kit's /roles command. Use when the user says "assign the ServiceNow admin role to <person>", "make <person> the Workday admin", "who holds the <role> role?", or types /roles. This assigns/attests roles; it does NOT answer "what am I assigned?" (that is the planner's Flow 2).
---

# ESS Maker Kit — Roles attestation (CLI)

CLI-native entry point for the kit's `/roles`. In VS Code `/roles` is a prompt
file; the Copilot CLI has no typed `/roles`, so this skill provides the same
flow, invoked by intent ("assign the ServiceNow admin role to Priya", "make Sam
the Workday admin"). The name matches the VS Code command so the two surfaces
stay consistent.

This skill ships **inside** the kit; the kit root is the `ess-maker-skills` folder
that contains this skill's `.github/skills/` directory. Make it the working
directory before running anything.

## Steps

1. **Honor the kit rules first.** Read `.github/copilot-instructions.md` at the
   kit root and follow it (persona, communication rules — never narrate
   files/commands, never name the backend).
2. **Follow the attestation flow.** Read `src/skills/roles/SKILL.md` at the kit
   root and follow it. It resolves the person to a directory object id
   (`python scripts/roles/cli.py resolve-person ...`), confirms the role is
   attestable, and records the attestation with the plan's role tools. Run
   `python scripts/...` from the kit root.

## What roles attestation does

A plan pools some tasks to a **role** instead of a named person; that work stays
invisible until someone attests that a specific person holds the role for the
plan. This skill makes that attestation — it turns "Priya is the ServiceNow
admin" into a role assignment on the plan, after which Priya sees and can pick up
the ServiceNow admin tasks. It is **not** the "what am I assigned?" view (that is
the planner's Flow 2) — route those questions to the planner.
