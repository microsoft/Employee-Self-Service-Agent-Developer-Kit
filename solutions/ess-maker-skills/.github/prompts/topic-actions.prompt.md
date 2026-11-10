---
mode: agent
description: "Preview whole ESS topic-set enable/disable plans and safety blockers"
---

# Topic actions

Read `src/skills/topic-actions/SKILL.md` first. It owns this route's narrower
target and workspace-preparation gate; do not require connection health or
`connect_ready: true`. Do not automatically start setup.

Use its proposed-catalog preview. If prerequisite inspection or the helper
fails, report the blocker and supported next step. Do not expose raw inputs,
exceptions, caller context or service bodies.
Distinguish setup not established, incomplete and broken. `/setup` is a
supported setup entry, not a universal repair command or package installer.
Do not label unavailable evidence as missing packages, access denial or an
already-correct result. Before writes, cancellation says "Canceled. No topics
were changed." Preserve confirmed caller progress without promising an
unverified automatic return or resume.

Native writes are not released. Do not bypass a blocker using Connect Workday
activation, topic authoring, publishing, local flags or another mutation path.
