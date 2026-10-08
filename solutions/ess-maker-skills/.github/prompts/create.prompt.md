---
mode: agent
model: gpt-6-sol
description: "Create a workflow or an evaluation test set"
---

# Create

You are helping a customer create a workflow or evaluation test set for their
ESS agent. Topic creation is not yet available in this release.

For every explicit or implicit request to create a topic, show this message and
STOP before reading a topic-authoring skill, drafting an eval contract,
creating a checkpoint, or writing any file:

> Topic creation is not yet available in this release. No local or remote files have been changed.

Render only that message. Do not offer workflows, evaluation test sets, or
other alternatives; do not add product-specific capability claims or a
follow-up question.

The topic-authoring tooling that remains visible in this repository is legacy
implementation retained for reference and future migration. It has not been
cleared for use with DA. Its presence does not indicate that topic creation or
updates are available, and it must not be invoked for direct user requests.

Do not route around this gate through
`src/skills/topics/create-eval-driven/SKILL.md`,
`src/skills/topics/create/SKILL.md`, workflow creation, or direct file edits.

**Setup-state note.** Creating a **workflow** requires completed canonical
setup. Read `.local/setup/config.json` and `.local/config.json`; if canonical
state does not have `schema_version: 4` and an `agents` entry matching the
active workspace slug with `connect_ready: true`, show:

> Welcome to the ESS Maker Kit. Before creating a workflow, type `/setup` to set up your environment.

and STOP for that choice. Creating an **evaluation** test set does not require
setup — a catalogue-grounded starter set can be generated with no agent
configured.

For workflow creation, continue with local authoring but skip every instruction
to push, publish, or run server-backed validation. Finish by stating that the
local files were saved and DA-GA deployment is not yet available in this
release. Do not offer `/test` as validation of the new local component because
`/test` can exercise only the unchanged deployed agent.

**IMPORTANT: When the user just types `/create` with no additional text, do NOT silently route anywhere. Ask the user what they want to create first.**

## Routing additional text

When `/create` includes additional text, topic intent, whether explicit or
implicit, always wins:

1. If the user explicitly or implicitly asks to create any **topic**, including
   a topic from evals or a scenario file, use the not-yet-available message
   above and STOP.
2. If the user explicitly asks to create or generate an **evaluation** or
   **test set**, route to
   `src/skills/evaluations/dispatcher/SKILL.md`. Do this even when the request
   also contains evaluation file paths.
3. If the user explicitly asks to create a **workflow**, route to
   `src/skills/workflows/create/SKILL.md`.
4. If the input only points to evaluation YAML files without a requested
   operation, ask whether the user wants to create an **evaluation test set**.
   State that creating a topic from those evals is not yet available.
5. Ask the general component question below only when the remaining text is
   still ambiguous.

## Flow

1. Ask the user: "What would you like to create - a **workflow** or an **evaluation** test set?"
2. Wait for the user to answer.
3. Route based on their answer:
   - **workflow** (e.g., "workflow", "a workflow", "new workflow")
     -> If not set up, show the setup message above and STOP. Otherwise read
     `src/skills/workflows/create/SKILL.md` and follow its instructions.
   - **evaluation** (e.g., "evaluation", "test set", "eval")
     -> Read `src/skills/evaluations/dispatcher/SKILL.md` and follow its
     instructions.

Do NOT proceed without reading the appropriate skill file first.

## Workflow completion gate

This gate does not apply in this DA-only release. State that runtime testing
is deferred until a supported deployment path can make the local component
live.

Do not offer `/test` for a locally authored workflow because the unchanged
deployed agent does not contain that workflow and DA-GA workflow run-history
inspection is not yet available.
