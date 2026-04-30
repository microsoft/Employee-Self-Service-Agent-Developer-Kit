---
mode: agent
description: "Type Enter to modify an existing topic or workflow"
---

# Update

You are helping a customer modify an existing component in their ESS agent.
This edits the local working copy AND pushes the change to Copilot Studio.

**IMPORTANT: When the user just types `/update` with no additional text, do
NOT silently route anywhere. Ask the user what they want to update first.**

## Flow

1. Ask the user: "What would you like to update — a **topic** or a **workflow**?"
2. Wait for the user to answer.
3. Route based on their answer:
   - If they said **topic**:
     → Read `src/skills/topics/update/SKILL.md` and follow its instructions.
   - If they said **workflow**:
     → Read `src/skills/workflows/update/SKILL.md` and follow its instructions.

Do NOT proceed without reading the appropriate skill file first.
