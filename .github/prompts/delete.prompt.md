---
mode: agent
description: "Type Enter to delete a topic or workflow from your agent"
---

# Delete

You are helping a customer delete a component from their ESS agent. This
removes it from the local working copy AND from Copilot Studio.

**IMPORTANT: When the user just types `/delete` with no additional text, do
NOT silently route anywhere. Ask the user what they want to delete first.**

## Flow

1. Ask the user: "What would you like to delete — a **topic** or a **workflow**?"
2. Wait for the user to answer.
3. Route based on their answer:
   - If they said **topic**:
     → Read `src/skills/topics/delete/SKILL.md` and follow its instructions.
   - If they said **workflow**:
     → Read `src/skills/workflows/delete/SKILL.md` and follow its instructions.

Do NOT proceed without reading the appropriate skill file first.
