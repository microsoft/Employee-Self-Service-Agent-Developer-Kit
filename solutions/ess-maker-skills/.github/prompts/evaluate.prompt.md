---
mode: agent
model: gpt-6-sol
description: "Generate or manage evaluation test sets"
---

# Evaluate

**Setup-state check.** Read `.local/setup/config.json` and `.local/config.json`.
Canonical runtime operations require `schema_version: 4` and an `agents` entry
matching the active workspace slug with `connect_ready: true`. When that state is
not ready, continue generating or editing evaluation files locally and skip every
instruction to push them, request remote review, or run them. Do not block local
catalogue generation, editing, CSV synchronization, or quality review.

**Workspace note.** Creating a fresh test set does not require a configured
agent. Updating can also proceed without setup when workspace-level evaluation
sets exist. Deleting deployed agent sets requires completed canonical setup and
a configured agent.

Read `src/skills/evaluations/experience-contract.md` for the shared maker
experience. Run and Request Review include required scoped deployment through
`src/skills/evaluations/deployment-flow.md`; no separate push command is required.
Explicit standalone evaluation push remains supported. Local editing and
test-set quality review never deploy automatically. Compare Meaning is this
feature's only test method; incompatible multi-turn generation is not offered.

## Flow

1. If the request already clearly identifies an action, route it directly;
   preserve all selection/confirmation gates in its skill. Otherwise ask:
   "What would you like to do with evaluation test sets - **create**,
   **update/add cases**, **tag for review**, **review**, **quality review**,
   **run**, **view results**, or **delete**?"
2. Wait for the answer.
3. Route to the matching skill:
   - **create** -> read `src/skills/evaluations/dispatcher/SKILL.md` and follow
     it.
   - **update** / **edit** / **add cases** -> read
     `src/skills/evaluations/update/SKILL.md` and follow it with the exact
     selected set context, if any.
   - **tag for review** / **Mark this test set ready for review** -> read
     `src/skills/evaluations/update/SKILL.md` and follow **Flow R1**.
   - **review** / **review tagged test sets** -> read
     `src/skills/evaluations/review/SKILL.md` and follow it.
   - **quality review** / **Run another quality review** -> select the exact
     local set through `src/skills/evaluations/update/SKILL.md`, follow its
     Step 5 with the shared quality/run explanation, then return to four maker
     actions without deployment or runtime execution.
   - **run** / **execute test sets** -> read
     `src/skills/evaluations/run/SKILL.md` and follow **Flow A**. Candidate
     discovery and execution require separate user turns: list choices, ask
     for selection, and STOP before running anything. After a selected run
     starts successfully, copy the command's `userGuidance` field verbatim;
     the 10-15-minute wait notice and direction to return to chat are mandatory.
     Show its returned `agentStudioUrl` as an optional link beside the newly started run using the run skill's
     link/error rules; never guess a URL or wait for completion to show it.
   - **view results** / **show run IDs** -> read
     `src/skills/evaluations/run/SKILL.md` and follow **Flow B**.
   - **explicitly push a test set** -> discover/select it through
     `src/skills/evaluations/update/SKILL.md`, then follow the shared deployment
     flow with helper action `push`. Do not tag or run it automatically.
   - **delete** -> read `.local/setup/config.json` and `.local/config.json`. If
     canonical state does not have `schema_version: 4` and an `agents` entry
     matching the active workspace slug with `connect_ready: true`, show the message below and
     STOP; otherwise read `src/skills/evaluations/delete/SKILL.md` and follow
     it.
4. If the answer is ambiguous, ask once more before routing.

The phrase **"review test sets"** means review sets tagged
`review_requested`. It does not mean quality validation. Route to the review
skill and list tagged sets before invoking any validator.

> Creating and updating workspace-level test sets does not require setup.
> Deleting or pushing configured-agent sets requires a connected agent.
