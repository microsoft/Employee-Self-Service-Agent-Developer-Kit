---
mode: agent
description: "Type Enter to modify an existing topic, workflow, or evaluation test set"
---

# Update

You are helping a customer modify an existing component in their ESS agent.
This edits the local working copy, pushes the change to Copilot Studio, and
then helps the maker **validate the change's runtime behaviour**.

**Setup-state check.** Read `.local/config.json`. If it does not exist, OR `setup` is not `"complete"`, show:

> Welcome to the ESS Maker Kit. Before running `/update`, type `/setup` to set up your environment.

and STOP. Otherwise proceed.

**IMPORTANT: When the user just types `/update` with no additional text, do
NOT silently route anywhere. Ask the user what they want to update first.**

## Flow

1. Ask the user: "What would you like to update - a **topic**, a **workflow**, or an **evaluation** test set?"
2. Wait for the user to answer.
3. Route based on their answer:
   - **topic**
     -> Read `src/skills/topics/update/SKILL.md` and follow its instructions.
   - **workflow**
     -> Read `src/skills/workflows/update/SKILL.md` and follow its instructions.
   - **evaluation**
     -> Read `src/skills/evaluations/update/SKILL.md` and follow its instructions.

Do NOT proceed without reading the appropriate skill file first.

## Completion gate — offer `/test` before finishing

A scan, a push, `validate.py` (flow **registration** check), or a publish is a
deploy step, **not** a behavioural test — do not treat any of them as validating
that the change works. The request is **not complete** until you have offered to
run the **`/test`** skill (`topics/test` or `workflows/test`) to drive the
just-changed component.

Before your final response, you MUST have asked the maker whether to run
**`/test`** against the changed component now (the offer defined in the skill's
final step — e.g. topics/update Step 9). Wait for their answer; if yes, run the
`/test` skill. This holds even when the publish is handed off to the maker or run
asynchronously — a deferred publish does not end the request.

Your final completion response MUST explicitly state whether **`/test`** was
offered and whether it was run, declined, or deferred.
