---
mode: agent
description: "Type Enter to create a new topic, workflow, or evaluation test set"
---

# Create

You are helping a customer create a new component for their ESS agent.

**Setup-state check.** Read `.local/config.json`. If it does not exist, OR `setup` is not `"complete"`, show:

> Welcome to the ESS Copilot Kit. Before running `/create`, type `/setup` to set up your environment.

and STOP. Otherwise proceed.

**IMPORTANT: When the user just types `/create` with no additional text, do NOT silently route anywhere. Ask the user what they want to create first.**

## Flow

1. Ask the user: "What would you like to create - a **topic**, a **workflow**, or an **evaluation** test set?"
2. Wait for the user to answer.
3. Route based on their answer:
   - **topic** (e.g., "topic", "a topic", "new topic")
     -> Read `src/skills/topics/create/SKILL.md` and follow its instructions.
   - **workflow** (e.g., "workflow", "a workflow", "new workflow")
     -> Read `src/skills/workflows/create/SKILL.md` and follow its instructions.
   - **evaluation** (e.g., "evaluation", "test set", "eval")
     -> Read `src/skills/evaluations/create/SKILL.md` and follow its instructions.

Do NOT proceed without reading the appropriate skill file first.
