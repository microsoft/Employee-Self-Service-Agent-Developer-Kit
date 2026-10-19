---
mode: agent
description: "Type Enter to set up your ESS customization environment"
---

# Setup

Read `src/skills/foundation-setup/SKILL.md` and follow it.

The same entry handles clear natural-language requests to set up or install ESS;
never require the maker to repeat the request as `/setup`. Preserve the assigned
plan task and environment when handing off, and return to that task afterward.

Do not route directly to `src/skills/onboarding/SKILL.md`. Foundation setup owns
environment selection, prerequisites, starter installation, and readiness. It
invokes onboarding itself only after the environment is locked and the
foundation is ready.
