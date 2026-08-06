---
mode: agent
description: "Update a simple topic with evals, or modify a workflow or evaluation test set"
---

# Update

You are helping a customer modify an existing component in their ESS agent.
This edits the local working copy AND pushes the change to Copilot Studio.

**Setup-state check.** Read `.local/config.json`. If it does not exist, OR `setup` is not `"complete"`, show:

> Welcome to the ESS Maker Kit. Before running `/update`, type `/setup` to set up your environment.

and STOP. Otherwise proceed.

**IMPORTANT: When the user just types `/update` with no additional text, do
NOT silently route anywhere. Ask the user what they want to update first.**

## Routing additional text

When `/update` includes additional text, explicit component intent always wins:

1. If the user explicitly asks to update an **evaluation** or **test set**,
   route to `src/skills/evaluations/update/SKILL.md`.
2. If the user explicitly asks to update a **workflow**, route to
   `src/skills/workflows/update/SKILL.md`.
3. If the user explicitly asks to update a Workday, ServiceNow, SAP,
   connector-backed, flow-backed, or other integration **topic**, route to
   `src/skills/topics/update/SKILL.md` to preserve existing integration
   behavior.
4. If the user asks to update a simple informational, clarification, routing,
   or handoff **topic**, route to
   `src/skills/topics/update-eval-driven/SKILL.md`.
5. If the topic type cannot be known until the existing topic is inspected,
   route to the eval-driven update skill. It will delegate integration topics
   to the existing update skill without changing them.

## Flow

1. Ask the user: "What would you like to update - a **topic**, a **workflow**, or an **evaluation** test set?"
2. Wait for the user to answer.
3. Route based on their answer:
   - **topic**
     -> Read `src/skills/topics/update-eval-driven/SKILL.md` and follow its instructions.
       It handles simple topics with evals and delegates integration topics to
       the existing topic-update skill.
   - **workflow**
     -> Read `src/skills/workflows/update/SKILL.md` and follow its instructions.
   - **evaluation**
     -> Read `src/skills/evaluations/update/SKILL.md` and follow its instructions.

Do NOT proceed without reading the appropriate skill file first.
