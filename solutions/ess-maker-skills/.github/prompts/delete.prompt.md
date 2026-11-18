---
mode: agent
description: "Type Enter to delete a topic, workflow, or evaluation test set from your agent"
---

# Delete

You are helping a customer delete a component from their ESS agent.

**Route before checking setup.** Evaluation test-set and test-case deletion is
local-only. For an explicit evaluation deletion request, immediately read
`src/skills/evaluations/delete/SKILL.md` and follow it without checking setup or
backend availability. Make no API calls and do not push or delete anything in
Copilot Studio.

**IMPORTANT: When the user just types `/delete` with no additional text, do
NOT silently route anywhere. Ask the user what they want to delete first.**

Topic and workflow deletion retain their respective entry-point restrictions.
Only for those requests, apply the following setup-state check before following
the selected entry point.

**Setup-state check (topics and workflows only).** Read `.local/setup/config.json` and `.local/config.json`. If canonical state does not have `schema_version: 4` and an `agents` entry matching the active workspace slug with `connect_ready: true`, show:

> Welcome to the ESS Maker Kit. Before running `/delete`, type `/setup` to set up your environment.

and STOP. Otherwise proceed.

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
