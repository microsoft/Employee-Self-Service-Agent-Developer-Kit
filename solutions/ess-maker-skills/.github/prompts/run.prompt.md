---
mode: agent
description: "Run evaluation test sets or view evaluation run results"
---

# Run Evaluation Test Sets

Read `.local/config.json`. If it is missing or `setup` is not `"complete"`,
show:

> Welcome to the ESS Maker Kit. Before running evaluation test sets, type `/setup` to set up your environment.

and STOP.

Read `src/skills/evaluations/run/SKILL.md` and follow it.

If the user's request does not distinguish starting a run from viewing
results, ask whether they want to **run a test set** or **view run results**.

For a start-run request, candidate discovery and execution must occur in
separate user turns. First list the eligible test sets, ask the user to select
or confirm one, and STOP. Do not execute a set merely because it is the only
candidate, appeared in prior conversation, or resembles the user's wording.

After `evaluation_runs.py run` succeeds, copy its `userGuidance` field verbatim
into the response. Never finish a successful run-start turn without the
10-15-minute wait notice.
