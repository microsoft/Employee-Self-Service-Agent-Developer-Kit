---
mode: agent
description: "Create a simple topic with evals, a workflow, or an evaluation test set"
---

# Create

You are helping a customer create a new component for their ESS agent. Topics
and workflows are generated and pushed, then the maker is helped to **validate
their runtime behaviour**. Evaluation test sets may instead be generated as
local starter artifacts, depending on the source the maker chooses.

**Setup-state note.** Read `.local/config.json`. Creating a **topic** or
**workflow** requires a configured agent; if `.local/config.json` does not exist
OR `setup` is not `"complete"`, show the message below and STOP **for those two
choices**. Creating an **evaluation** test set does NOT require setup — a
catalogue-grounded starter set can be generated with no agent configured.

> Welcome to the ESS Maker Kit. Before creating a topic or workflow, type `/setup` to set up your environment.

**IMPORTANT: When the user just types `/create` with no additional text, do NOT silently route anywhere. Ask the user what they want to create first.**

## Routing additional text

When `/create` includes additional text, explicit component intent always wins:

1. If the user explicitly asks to create or generate an **evaluation** or
   **test set**, route to
   `src/skills/evaluations/dispatcher/SKILL.md`. Do this even when the request
   also contains evaluation file paths.
2. If the user explicitly asks to create a **workflow**, route to
   `src/skills/workflows/create/SKILL.md`.
3. If the user explicitly asks to create a **topic** involving Workday,
   ServiceNow, SAP, a connector, a cloud flow, or another external system,
   route to `src/skills/topics/create/SKILL.md` to preserve the existing
   integration behavior.
4. If the user explicitly asks to create a **simple topic**, clearly describes
   a new informational, clarification, routing, or handoff topic, says to
   create a topic from evals, or supplies a Phase 1 scenario YAML file, route
   to `src/skills/topics/create-eval-driven/SKILL.md`.
5. If the input only points to evaluation YAML files and does not say whether
   the user wants a topic or an evaluation test set, ask:
   "Would you like to create a **topic from these evals**, or create an
   **evaluation test set**?"
6. Ask the general component question below only when the remaining text is
   still ambiguous.

## Flow

1. Ask the user: "What would you like to create - a **topic**, a **workflow**, or an **evaluation** test set?"
2. Wait for the user to answer.
3. Route based on their answer:
   - **topic** (e.g., "topic", "a topic", "new topic")
     -> If not set up, show the setup message above and STOP. Otherwise read
     `src/skills/topics/create-eval-driven/SKILL.md` and follow its
     instructions. This path accepts a plain-language request, a scenario YAML
     file, or existing evaluation YAML files for simple topics. It delegates
     integration topics to the existing topic-create skill.
   - **workflow** (e.g., "workflow", "a workflow", "new workflow")
     -> If not set up, show the setup message above and STOP. Otherwise read
     `src/skills/workflows/create/SKILL.md` and follow its instructions.
   - **evaluation** (e.g., "evaluation", "test set", "eval")
     -> Read `src/skills/evaluations/dispatcher/SKILL.md` and follow its
     instructions.

Do NOT proceed without reading the appropriate skill file first.

## Topic/workflow completion gate — offer `/test` before finishing

For topic or workflow creation, a scan, a push, `validate.py` (flow
**registration** check), or a publish is a deploy step, **not** a behavioural
test — do not treat any of them as validating that the component works. A topic
or workflow request is **not complete** until you have offered to run the
**`/test`** skill (`topics/test` or `workflows/test`) to drive the just-created
component. This gate does not apply when the user creates only an evaluation
test set.

Before your final response, you MUST have asked the maker whether to run
**`/test`** against the created component now (the offer defined in the skill's
final step — e.g. topics/create Step 7). Wait for their answer; if yes, run the
`/test` skill. This holds even when the publish is handed off to the maker or run
asynchronously — a deferred publish does not end the request.

For topic or workflow creation, the final completion response MUST explicitly
state whether **`/test`** was offered and whether it was run, declined, or
deferred.
