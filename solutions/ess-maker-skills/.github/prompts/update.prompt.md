---
mode: agent
description: "Update a topic, workflow notice, or evaluation test set"
---

# Update

Route updates to the operation's current owner. When the request is ambiguous, ask whether the maker wants to update a **topic**, **workflow**, or **evaluation test set**.

**Setup-state check.** Topic updates require `.local/setup/config.json` with
`schema_version: 4` and the active workspace's matching `agents` entry with
`connect_ready: true`, plus `.local/config.json`. Apply this gate only after the
maker chooses a topic. Workspace evaluation updates and the workflow notice do
not require setup.

## Topic

For any explicit or implicit topic change, read `src/skills/topics/update/SKILL.md` and follow it completely. Carry the exact selected topic and any supplied evaluation cases or findings. Do not use a separate eval-driven save/materialization workflow.

The topic owner handles fresh native readback, mapped identity, ordinary `.mcs.yml` drafting, instruction alignment, separate approvals, scoped native save, optional testing handoff, and end-of-iteration evaluation impact.

## Evaluation

For evaluation edits, additions, review, deployment, or runs, use the applicable evaluation skill. A request to change evaluation cases about a topic is not permission to modify the topic.

Workspace-level evaluation updates and review-tag workflows do not require configured-agent setup. Preserve the exact selected folder/source and the evaluation skill's separate deployment and run approvals.

## Workflow

For workflow updates, read `src/skills/workflows/update/SKILL.md`. It is notice-only: ADK does not author Power Automate flows through this route. Do not offer calling-topic changes. Do not offer `/test`.
