---
mode: agent
description: "View an ESS agent's display name/logo, rename Dev, Test or Prod, or change its Dev logo without publishing"
---

# Agent Basics

**Setup-state check.** Apply the shared completed-setup gate in
`.github/copilot-instructions.md` before continuing.

Read `src/skills/agent-basics/SKILL.md` and follow it.

Preserve the maker's selected target and requested name/logo changes.
In a new chat, reuse completed saved Dev setup and retain the requested
quality gate. "Agent name", "display name" and "displayName" mean the same
rename operation. If no replacement was supplied, ask only for the new
display name; do not show generic help or ask which operation they want.
Follow the skill's target checks, input validation, preview, protected save
and read-back flow. Require explicit approval before saving.

For rename-only requests, review the name only; do not inspect images or ask
about service-side image processing. No separate image-processing consent is
required for name or logo edits.
Logo edits use one source PNG; the platform derives outlines. Do not offer
independent outline customization or silently drop an unsupported request.

Do not publish, edit agent instructions or other settings, or route these
name/logo edits through the landing-page AgentConfiguration update tool.
