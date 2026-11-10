---
mode: agent
description: "Check the selected ESS target without changing topics"
---

# Topic actions entry

Read `src/skills/topic-actions/SKILL.md` first. It owns this route's
target and workspace-preparation gate. Do not require connection health
or `connect_ready: true`. Do not automatically start setup.

Use its nonmutating account/target check. Distinguish setup not established,
incomplete and broken; `/setup` is not a universal repair command.
Preserve confirmed caller progress without promising an unverified return.
Report blockers explicitly without exposing raw inputs or service bodies.

This milestone cannot discover, plan, enable, disable or publish topics.
