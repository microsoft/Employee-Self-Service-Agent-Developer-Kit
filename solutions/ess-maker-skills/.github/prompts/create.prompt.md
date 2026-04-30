---
mode: agent
description: "Type Enter to create a new topic or workflow"
---

# Create

You are helping a customer create a new component for their ESS agent.

**IMPORTANT: When the user just types `/create` with no additional text, do NOT silently route anywhere. Ask the user what they want to create first.**

## Flow

1. Ask the user: "What would you like to create — a **topic** or a **workflow**?"
2. Wait for the user to answer.
3. Route based on their answer:
   - If they said **topic** (e.g., "topic", "a topic", "new topic"):
     → Read `src/skills/topics/create/SKILL.md` and follow its instructions.
   - If they said **workflow** (e.g., "workflow", "a workflow", "new workflow"):
     → Read `src/skills/workflows/create/SKILL.md` and follow its instructions.

Do NOT proceed without reading the appropriate skill file first.
