---
mode: agent
description: "Create a topic, workflow notice, or evaluation test set"
---

# Create

Route creation to the operation's current owner. When the request is ambiguous, ask whether the maker wants a **topic**, **workflow**, or **evaluation test set**.

**Setup-state check.** Topic creation requires `.local/setup/config.json` with
`schema_version: 4` and the active workspace's matching `agents` entry with
`connect_ready: true`, plus `.local/config.json`. Apply this gate only after the
maker chooses a topic. Evaluation creation and the workflow notice do not
require setup.

## Topic

For any explicit or implicit topic creation request, read `src/skills/topics/create/SKILL.md` and follow it completely. This includes requests based on evaluation files or intended scenarios. Carry supplied intent, cases, wording, and thresholds as context; do not start a separate scenario/materializer lifecycle.

The topic owner handles the ordinary `.mcs.yml` draft, current native inventory, instruction alignment, applicable scoped approvals, native save, readback, testing handoff, and end-of-iteration evaluation impact. Read `src/skills/topics/experience-contract.md` and use its summary, Routing Conflicts section, initial routing-conflict decision before Push, targeted instruction preview and exact two-component review, truthful outcomes and state-aware testing continuation. Honor the earlier decision; use the combined routing-conflict/testing decision only for a newly discovered or materially changed conflict after Push. Carry valid Push/debugging authorization to the owner rather than imposing another unchanged-scope approval or duplicate testing offer.

## Evaluation

For an explicit evaluation or test-set request, read `src/skills/evaluations/dispatcher/SKILL.md`. Evaluation files remain owned by the evaluation skills even when they refer to a topic.

If the input only points to evaluation files without requesting an operation, ask whether the maker wants an evaluation test set or a topic informed by those cases.

## Workflow

For workflow creation, read `src/skills/workflows/create/SKILL.md`. It is notice-only: ADK does not author Power Automate flows through this route. Do not offer a calling-topic follow-up. Do not offer `/test`.
