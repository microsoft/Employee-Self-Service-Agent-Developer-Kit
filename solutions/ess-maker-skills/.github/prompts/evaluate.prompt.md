---
mode: agent
description: "Generate or manage evaluation test sets"
---

# Evaluate

**Setup-state note.** Read `.local/config.json`. Creating a fresh test set does
not require a configured agent. Updating can also proceed without setup when
workspace-level evaluation sets exist. Deleting deployed agent sets requires a
configured agent.

## Flow

1. Ask the user: "What would you like to do with evaluation test sets -
   **create**, **update**, **tag for review**, **review**, **run**, **view
   results**, or **delete**?"
2. Wait for the answer.
3. Route to the matching skill:
   - **create** -> read `src/skills/evaluations/dispatcher/SKILL.md` and follow
     it.
   - **update** -> read `src/skills/evaluations/update/SKILL.md` and follow it.
   - **tag for review** -> read
     `src/skills/evaluations/update/SKILL.md` and follow **Flow R1**.
   - **review** / **review tagged test sets** -> read
     `src/skills/evaluations/review/SKILL.md` and follow it.
   - **run** / **execute test sets** -> read
     `src/skills/evaluations/run/SKILL.md` and follow **Flow A**. Candidate
     discovery and execution require separate user turns: list choices, ask
     for selection, and STOP before running anything. After a selected run
     starts successfully, copy the command's `userGuidance` field verbatim;
     the 10-15-minute wait notice is mandatory.
   - **view results** / **show run IDs** -> read
     `src/skills/evaluations/run/SKILL.md` and follow **Flow B**.
   - **delete** -> if `.local/config.json` is missing or `setup` is not
     `"complete"`, show the message below and STOP; otherwise read
     `src/skills/evaluations/delete/SKILL.md` and follow it.
4. If the answer is ambiguous, ask once more before routing.

The phrase **"review test sets"** means review sets tagged
`review_requested`. It does not mean quality validation. Route to the review
skill and list tagged sets before invoking any validator.

> Creating and updating workspace-level test sets does not require setup.
> Deleting or pushing configured-agent sets requires a connected agent.
