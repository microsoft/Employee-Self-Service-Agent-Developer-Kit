---
mode: agent
description: "Connect the active ESS HR agent to Workday"
---

# Connect Workday

Follow the same entry routing and execution rules as
`.github/prompts/connect.prompt.md`, with `workday` supplied as the selected
integration. Then read `src/skills/connect/SKILL.md` and continue without
asking which system to connect.

Route before probing `.local` metadata, even in a completely clean workspace.
The ordinary global setup gate does not apply to this command; the provider
entry point owns the automatic prerequisite handoff.
