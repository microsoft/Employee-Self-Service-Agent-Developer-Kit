---
mode: agent
description: "Connect native ESS HR or IT Development to ServiceNow Knowledge"
---

# Connect ServiceNow Knowledge

Follow `.github/prompts/connect.prompt.md` with `servicenow-kb` supplied as
the selected integration. Read `src/skills/connect/SKILL.md` and continue
without asking which system to connect. This is not the transactional
`servicenow` provider.

Route before probing setup metadata. The provider owns its workspace
preparation handoff and Dev-only boundary; the global setup gate does not
apply to this command.
