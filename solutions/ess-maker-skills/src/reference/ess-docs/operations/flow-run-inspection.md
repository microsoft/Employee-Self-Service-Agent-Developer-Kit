# Reading a cloud flow's run history to diagnose a topic

When a flow-backed topic misbehaves — a generic error reply, a blank field, a branch that seems not to fire — the **per-action run history** is the decisive "why" surface. The bot reply tells you _what the user saw_; the flow source tells you _what was authored_; only the run-action view tells you _what actually happened, action by action_.

This doc teaches you to read that cascade. The read is performed by `scripts/flow_run_inspect.py` (read-only — it never invokes, patches, or deletes anything). Consult this doc when a topic that calls a custom flow returns a wrong or generic result and you need to localize the fault. It is Step 3 of the `topics/test` skill (`src/skills/topics/test/SKILL.md`); this doc is the interpretation reference that step points at.

## What the tooling gives you

`flow_run_inspect.py` exposes read-only helpers over the Flow Management API:

- `get_latest_run(environment, flow_id, token)` — the most recent run (or `None` if never run).
- `get_run_by_id(environment, flow_id, run_id, token)` — one run by id (`None` if it is gone).
- `get_run_actions(environment, flow_id, run_id, token)` — the run's actions as `[{name, status, outputs}]`.
- `summarize_actions(actions)` — reduces that to the `[{name, status, statusCode}]` cascade you interpret.

`token` is a Flow Management API bearer token (resource `https://service.flow.microsoft.com/`). The CLI acquires one automatically via the kit's MSAL sign-in (Flow-scoped, using your active agent's environment for tenant discovery); set `FLOW_API_TOKEN` to supply your own instead (CI, or bring-your-own token).

A summarized cascade looks like:

```text
Invoke_ServiceNow      Failed      400
Set_error_body         Succeeded   200
Switch_on_result       Failed      —
Success_Response       Skipped     —
CatchAll_Response       Succeeded   500
```

## How to read the cascade

### 1. A `Succeeded` handler does not mean the flow succeeded

This is the single most important trap.

An action with `runAfter: [Failed]` (a failure/catch handler) reports **`Succeeded`** when _it_ ran to completion — even though it only ran _because something upstream failed_. Worse: the **containing scope** (a `Switch`, `Scope`, or `Condition`) is still marked **`Failed`** if any action inside it failed, regardless of the handler succeeding. A `Failed` scope commonly routes to a **catch-all Response** that returns a generic message and **discards** the handler's carefully-set output.

So a run can end with:

- the connector action `Failed` (the real fault),
- its failure handler `Succeeded` (it did its job — set an error body),
- the containing scope `Failed` (because the connector failed),
- a catch-all Response `Succeeded` returning a generic 500 — **which is all the user saw.**

Neither the reply (generic 500) nor the source (looks fine) reveals this. The run-action view does. **Always look at scope status, not just handler status.**

### 2. `Skipped` shows the path _not_ taken

A `Skipped` action is one whose `runAfter` condition wasn't met — the branch was not taken. Reading which actions are `Skipped` tells you which way a `Condition` or `Switch` actually went. A success branch that is `Skipped` while an error branch ran is a strong signal the flow took its failure path.

### 3. `Failed` + statusCode localizes the fault

The **first** `Failed` action is usually the true fault; everything after it is fallout. Its `statusCode` (from the connector/HTTP outputs) localizes _why_:

- `400` — bad request: check the request body the orchestrator built (a missing or mis-mapped field).
- `401` / `403` — auth / permission: the connection isn't consented, is stale, or lacks the entitlement.
- `404` — wrong table/endpoint or the record doesn't exist.
- `429` / `5xx` — throttling or a transient backend error; retry before assuming a logic bug.

### 4. Map action names back to the source flow

The action `name` values match the actions in the flow's `workflow.json`. Once you know _which_ action failed and _which_ branch was skipped, open the source and compare the **intended** path to the **actual** path. The gap between them is the bug.

## Worked example (the trap in one run)

Given the cascade above:

1. `Invoke_ServiceNow Failed 400` — the real fault: ServiceNow rejected the request (400). Start here.
2. `Set_error_body Succeeded` — the failure handler ran and set an error body. Do **not** be reassured by "Succeeded."
3. `Switch_on_result Failed` — the scope failed _because_ the connector failed, despite the handler.
4. `Success_Response Skipped` — the success branch was not taken. Confirms the failure path.
5. `CatchAll_Response Succeeded 500` — the generic 500 the user saw. It discarded the handler's error body.

Conclusion: the user's "something went wrong (500)" is a **masked 400** from ServiceNow. Fix the request body (step 1), not the Response node (step 5).

## Guardrails

- **Read-only.** These helpers only GET. They never re-run, patch, or delete a flow.
- **Eventual consistency.** Run history can lag a few seconds after a turn; if the latest run isn't there yet, wait and re-read.
- **Your own flow, your own env.** You are inspecting a flow you authored in an environment you have access to.
