---
mode: agent
description: "Type Enter to delete a topic, workflow, or evaluation test set from your agent"
---

# Delete

You are helping a customer delete a component from their ESS agent. This
removes it from the local working copy AND from Copilot Studio.

**Setup-state check.** Read `.local/setup/config.json` and `.local/config.json`. If canonical state does not have `schema_version: 1` and `status: "complete"`, or local config does not have `setup: "complete"`, show:

> Welcome to the ESS Maker Kit. Before running `/delete`, type `/setup` to set up your environment.

and STOP. Otherwise proceed.

If `.local/config.json` has `transport: "agentbuilder"`, show:

> Deleting components from a DA-GA agent is not yet available in this release. No local or remote files have been changed.

and STOP.

**IMPORTANT: When the user just types `/delete` with no additional text, do
NOT silently route anywhere. Ask the user what they want to delete first.**

## Flow

1. Ask the user: "What would you like to delete - a **topic**, a **workflow**, or an **evaluation** test set?"
2. Wait for the user to answer.
3. Route based on their answer:
   - **topic**
     -> Read `src/skills/topics/delete/SKILL.md` and follow its instructions.
   - **workflow**
     -> Read `src/skills/workflows/delete/SKILL.md` and follow its instructions.
   - **evaluation**
     -> Read `src/skills/evaluations/delete/SKILL.md` and follow its instructions.

Do NOT proceed without reading the appropriate skill file first.
