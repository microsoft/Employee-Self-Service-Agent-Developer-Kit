---
mode: agent
description: "Check the selected ESS target for topic-set actions (preview; no changes)"
---

# Topic actions preview

First follow the canonical setup gate in `.github/copilot-instructions.md`.
When setup is missing or incomplete, immediately display its setup-required
Message block and finish the request. Do not silently stop, wait for target IDs
or topic-set keys, authenticate, or automatically start setup.

Only after the setup gate passes, read `src/skills/topic-actions/SKILL.md`
and follow its nonmutating entry. If prerequisite inspection or the helper
fails, report the blocker and its supported next step instead of leaving the
maker without a response. Do not expose raw inputs, exceptions or service bodies.

This placeholder cannot enable or disable topics. Do not route it to Connect
Workday activation, topic authoring, publishing or another mutation path.

<!-- TODO(M7): integrate the approved final caller/chat experience. -->
