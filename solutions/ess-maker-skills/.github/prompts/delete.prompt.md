---
mode: agent
description: "Type Enter to delete a topic, workflow, or evaluation test set from your agent"
---

# Delete

You are helping a customer delete a component from their ESS agent. This
removes it from the local working copy AND from Copilot Studio.

**Setup-state check.** Read `.local/config.json`. If it does not exist, OR `setup` is not `"complete"`, show:

> Welcome to the ESS Copilot Kit. Before running `/delete`, type `/setup` to set up your environment.

and STOP. Otherwise proceed.

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
