---
mode: agent
description: "Type Enter to create a new topic, workflow, or evaluation test set"
---

# Create

You are helping a customer create a new component for their ESS agent. This
generates and pushes the component, and then helps the maker **validate its
runtime behaviour**.

**Setup-state check.** Read `.local/config.json`. If it does not exist, OR `setup` is not `"complete"`, show:

> Welcome to the ESS Maker Kit. Before running `/create`, type `/setup` to set up your environment.

and STOP. Otherwise proceed.

**IMPORTANT: When the user just types `/create` with no additional text, do NOT silently route anywhere. Ask the user what they want to create first.**

## Flow

1. Ask the user: "What would you like to create - a **topic**, a **workflow**, or an **evaluation** test set?"
2. Wait for the user to answer.
3. Route based on their answer:
   - **topic** (e.g., "topic", "a topic", "new topic")
     -> Read `src/skills/topics/create/SKILL.md` and follow its instructions.
   - **workflow** (e.g., "workflow", "a workflow", "new workflow")
     -> Read `src/skills/workflows/create/SKILL.md` and follow its instructions.
   - **evaluation** (e.g., "evaluation", "test set", "eval")
     -> Read `src/skills/evaluations/create/SKILL.md` and follow its instructions.

Do NOT proceed without reading the appropriate skill file first.

## Completion gate — offer `/test` before finishing

A scan, a push, `validate.py` (flow **registration** check), or a publish is a
deploy step, **not** a behavioural test — do not treat any of them as validating
that the component works. The request is **not complete** until you have offered
to run the **`/test`** skill (`topics/test` or `workflows/test`) to drive the
just-created component.

Before your final response, you MUST have asked the maker whether to run
**`/test`** against the created component now (the offer defined in the skill's
final step — e.g. topics/create Step 7). Wait for their answer; if yes, run the
`/test` skill. This holds even when the publish is handed off to the maker or run
asynchronously — a deferred publish does not end the request.

Your final completion response MUST explicitly state whether **`/test`** was
offered and whether it was run, declined, or deferred.
