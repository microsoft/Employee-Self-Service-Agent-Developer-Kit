---
mode: agent
model: gpt6.1-sol
description: "Modify a workflow or evaluation test set"
---

# Update

You are helping a customer modify a workflow or evaluation test set. Topic
updates are not yet available in this release.

For every explicit or implicit request to update, modify, rename, or otherwise
change a topic, show this message and STOP before reading a topic-authoring
skill, creating a checkpoint, or writing any file:

> Topic updates are not yet available in this release. No local or remote files have been changed.

Render only that message. Do not offer workflow updates, evaluation test sets,
or other alternatives; do not add product-specific capability claims or a
follow-up question.

The topic-authoring tooling that remains visible in this repository is legacy
implementation retained for reference and future migration. It has not been
cleared for use with DA. Its presence does not indicate that topic creation or
updates are available, and it must not be invoked for direct user requests.

Do not route around this gate through
`src/skills/topics/update-eval-driven/SKILL.md`,
`src/skills/topics/update/SKILL.md`, workflow updates, or direct file edits.

**Setup-state note.** Workflow updates require a completed setup. Workspace-level
evaluation updates and review-tag workflows do not. Apply the setup gate only
after the user chooses a workflow, or when an evaluation operation needs a
configured agent for push. Read `.local/setup/config.json` and
`.local/config.json`; completed setup requires `schema_version: 4` and an
`agents` entry matching the active workspace slug with `connect_ready: true`.

For **workflow updates only**, continue with local authoring but skip every
instruction to push, publish, or
run server-backed validation. Finish by stating that the local files were
saved and DA-GA deployment is not yet available in this release. Do not offer
`/test` as validation of the local change because `/test` can exercise only
the unchanged deployed version.

This restriction does not apply to evaluation operations. Evaluation edit/add,
Request Review, Run, reviewer completion, and explicit evaluation push follow
`src/skills/evaluations/experience-contract.md` and
`src/skills/evaluations/deployment-flow.md`. Run and Request Review include their
required scoped deployment without a separate push command. Keep the existing
APIs: Dataverse push persists review metadata; new/changed native YAML creates a
new copy while retaining the old remote copy and local review sidecar.
Unchanged YAML, including review-only changes, uses verified reuse. Show
that behavior before consent and report the native shared-review limitation,
not a new API-parity blocker or a false reviewer-availability claim.

**IMPORTANT: When the user just types `/update` with no additional text, do
NOT silently route anywhere. Ask the user what they want to update first.**

## Routing additional text

When `/update` includes additional text, topic intent, whether explicit or
implicit, always wins:

1. If the user explicitly or implicitly asks to update any **topic**, including
   its evals, use the not-yet-available message above and STOP.
2. If the user explicitly asks to update an **evaluation**, **test set**, or
   **add test cases**,
   route to `src/skills/evaluations/update/SKILL.md`.
3. If the user explicitly asks to update a **workflow**, route to
   `src/skills/workflows/update/SKILL.md`.

## Flow

1. Ask the user: "What would you like to update - a **workflow** or an **evaluation** test set?"
2. Wait for the user to answer.
3. Route based on their answer:
   - **workflow**
     -> Apply the same setup check, then read
     `src/skills/workflows/update/SKILL.md` and follow its instructions.
   - **evaluation**
     -> Read `src/skills/evaluations/update/SKILL.md` and follow its
     instructions. Preserve exact selected context and visibly offer edit/add.
   - **mark/send evaluation sets for review**
     -> Read `src/skills/evaluations/update/SKILL.md` Flow R1. Do not stop at
     a local tag or ask for a separate push command.
   - **review evaluation test sets** / **review testsets**
     -> Read `src/skills/evaluations/review/SKILL.md` and follow it. Do not
     invoke quality validation before listing `review_requested` sets and
     obtaining a selection.

> Welcome to the ESS Maker Kit. Before updating workflows, type `/setup` to set up your environment.

Do NOT proceed without reading the appropriate skill file first.

## Workflow completion gate

This gate does not apply in this DA-only release. State that runtime testing
is deferred until a supported deployment path can make the local change live.

This gate applies only to workflow updates. Evaluation updates and
evaluation review workflows follow their evaluation skill's completion steps.

Do not offer `/test` for a locally updated workflow because the unchanged
deployed agent does not contain that update and DA-GA workflow run-history
inspection is not yet available.
