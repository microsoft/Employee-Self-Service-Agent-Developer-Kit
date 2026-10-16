---
mode: agent
description: "Connect the active ESS HR agent to Workday"
---

# Connect Workday

Follow the same setup-state check and execution rules as
`.github/prompts/connect.prompt.md`, with `workday` supplied as the selected
integration. Then read `src/skills/connect/SKILL.md` and continue without
asking which system to connect.

Reuse the connect prompt's eligible profile entry after its existing
materialization, integration, and architecture/package gates. This alias
never counts or claims a second request and never changes the connect
script-executor output beyond its permitted optional onboarding conversation.
