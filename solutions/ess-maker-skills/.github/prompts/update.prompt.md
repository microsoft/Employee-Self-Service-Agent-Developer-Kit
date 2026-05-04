---
mode: agent
description: "Type Enter to modify an existing topic, workflow, or evaluation test set"
---

# Update

You are helping a customer modify an existing component in their ESS agent.
This edits the local working copy AND pushes the change to Copilot Studio.

**Setup-state check.** Read `.local/config.json`. If it does not exist, OR `setup` is not `"complete"`, show:

> Welcome to the ESS Copilot Kit. Before running `/update`, type `/setup` to set up your environment.

and STOP. Otherwise proceed.

**IMPORTANT: When the user just types `/update` with no additional text, do
NOT silently route anywhere. Ask the user what they want to update first.**

## Flow

1. Ask the user: "What would you like to update - a **topic**, a **workflow**, or an **evaluation** test set?"
2. Wait for the user to answer.
3. Route based on their answer:
   - **topic**
     -> Read `src/skills/topics/update/SKILL.md` and follow its instructions.
   - **workflow**
     -> Read `src/skills/workflows/update/SKILL.md` and follow its instructions.
   - **evaluation**
     -> Read `src/skills/evaluations/update/SKILL.md` and follow its instructions.

Do NOT proceed without reading the appropriate skill file first.
