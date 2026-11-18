---
mode: agent
description: "Run evaluation test sets or view evaluation run results"
---

# Run Evaluation Test Sets

Read `.local/setup/config.json` and `.local/config.json`. If canonical state
does not have `schema_version: 4` and an `agents` entry matching the active
workspace slug with `connect_ready: true`, show:

> Welcome to the ESS Maker Kit. Before running evaluation test sets, type `/setup` to set up your environment.

and STOP.

Read `src/skills/evaluations/run/SKILL.md` and follow it.

If the user's request does not distinguish starting a run from viewing
results, ask whether they want to **run a test set** or **view run results**.

For an ad hoc start-run request, candidate discovery and execution must occur in
separate user turns. First list the eligible test sets, ask the user to select
or confirm one, and STOP. Do not execute a set merely because it is the only
candidate, appeared in prior conversation, or resembles the user's wording.
When the maker chose a run option from ADK's next-step menu for one exact set,
follow Flow A's workflow handoff exception instead of asking again.

Flow A includes the selected set's required scoped deployment through
`src/skills/evaluations/deployment-flow.md` before starting the current deployed
identity. Include preparable workspace/current-agent sets, not just previously
deployed IDs. Run does not require a separate push command, does not request or
complete review. When exactly one connected profile matches the signed-in
account, Run uses it and shows the maker which user runs the evals instead of
asking; otherwise it asks the maker to choose.

After `evaluation_runs.py run-prepared` succeeds, copy its `userGuidance` field verbatim
into the response. Never finish a successful run-start turn without the
10-15-minute wait notice and direction to return to chat for results.

Render the returned `agentStudioUrl` immediately as an optional **Copilot Studio** link
with the selected set, new run ID, and actual state. Do not say "Done" before
completion. If the start has no valid run ID, do not show a success link. If
navigation identity is unavailable after a real start, report the run ID/state
and missing link without guessing a URL or starting the run again.
