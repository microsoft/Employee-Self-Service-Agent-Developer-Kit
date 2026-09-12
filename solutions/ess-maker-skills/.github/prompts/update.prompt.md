---
mode: agent
description: "Update a simple topic with evals, or modify a workflow or evaluation test set"
---

# Update

You are helping a customer modify an existing component in their ESS agent.
This edits the local working copy, pushes the change to Copilot Studio, and
then helps the maker **validate the change's runtime behaviour**.

**Setup-state note.** Topic and workflow updates require a completed setup.
Workspace-level evaluation updates and review-tag workflows do not. Apply the
setup gate only after the user chooses a topic or workflow, or when an
evaluation operation needs a configured agent for push.

**IMPORTANT: When the user just types `/update` with no additional text, do
NOT silently route anywhere. Ask the user what they want to update first.**

## Routing additional text

When `/update` includes additional text, explicit component intent always wins:

1. If the user explicitly asks to update an **evaluation** or **test set**,
   route to `src/skills/evaluations/update/SKILL.md`.
2. If the user explicitly asks to update a **workflow**, route to
   `src/skills/workflows/update/SKILL.md`.
3. If the user explicitly asks to update a Workday, ServiceNow, SAP,
   connector-backed, flow-backed, or other integration **topic**, route to
   `src/skills/topics/update/SKILL.md` to preserve existing integration
   behavior.
4. If the user asks to update a simple informational, clarification, routing,
   or handoff **topic**, route to
   `src/skills/topics/update-eval-driven/SKILL.md`.
5. If the topic type cannot be known until the existing topic is inspected,
   route to the eval-driven update skill. It will delegate integration topics
   to the existing update skill without changing them.

## Flow

1. Ask the user: "What would you like to update - a **topic**, a **workflow**, or an **evaluation** test set?"
2. Wait for the user to answer.
3. Route based on their answer:
   - **topic**
     -> If `.local/config.json` is missing or `setup` is not `"complete"`,
     show the setup message below and STOP. Otherwise read
     `src/skills/topics/update-eval-driven/SKILL.md` and follow its
     instructions. It handles simple topics with evals and delegates
     integration topics to the existing topic-update skill.
   - **workflow**
     -> Apply the same setup check, then read
     `src/skills/workflows/update/SKILL.md` and follow its instructions.
   - **evaluation**
     -> Read `src/skills/evaluations/update/SKILL.md` and follow its
     instructions.
   - **review evaluation test sets** / **review testsets**
     -> Read `src/skills/evaluations/review/SKILL.md` and follow it. Do not
     invoke quality validation before listing `review_requested` sets and
     obtaining a selection.

> Welcome to the ESS Maker Kit. Before updating topics or workflows, type `/setup` to set up your environment.

Do NOT proceed without reading the appropriate skill file first.

## Topic/workflow completion gate — offer `/test` before finishing

This gate applies only to topic and workflow updates. Evaluation updates and
evaluation review workflows follow their evaluation skill's completion steps.

For a topic or workflow, a scan, a push, `validate.py` (flow
**registration** check), or a publish is a deploy step, **not** a behavioural
test. Before the final response, ask whether to run **`/test`** against the
changed component now. Wait for the answer; if yes, run the `topics/test` or
`workflows/test` skill.

For topic/workflow updates, the final response must state whether **`/test`**
was offered and whether it was run, declined, or deferred.
