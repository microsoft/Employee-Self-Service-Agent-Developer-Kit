# Test Workflow Skill

Guides a maker through debugging a Power Automate cloud flow (workflow) behind their agent — exercising it, reading its per-action run history, localizing a fault to a specific action, and fixing the flow (or the template config it reads).

**You do not drive a flow directly from this skill.** An ESS flow is triggered by Copilot Studio — a topic calls it — so you exercise it one of two ways (below) and then read the decisive surface: the **run history**, action by action. The bot reply tells you what the user saw; the flow source tells you what was authored; only the run-action view tells you what actually happened.

## The debug-and-validate loop

Debugging a flow is one loop, repeated until the run is clean:

1. **Identify the flow** — the workflow folder and its `workflowId` (the flow GUID).
2. **Exercise it** — in **isolation** (Power Automate manual Test with direct inputs) or **in context** (drive the topic that calls it). Isolation tells you if the fault is in the flow itself; in-context tells you if the fault is in how the topic calls it.
3. **Read the run history** — `flow_run_inspect.py` dumps the per-action cascade. This is read-only and the decisive "why" surface.
4. **Localize the fault** — the first `Failed` action + its statusCode, the scope-vs-handler trap, the skipped branch — then map the action name back to `workflow.json`.
5. **Fix the flow** — through the `workflows/update` skill (edit the local working copy **and** push), or fix the **template config** the orchestrator reads. Never hand-patch the deployed flow.
6. **Re-exercise** until the cascade is clean.

**The one invariant:** inspection is read-only; every fix lands in the **flow definition or its template config**, applied through `workflows/update` so the local working copy and the live environment stay in sync. A flow's output shape is a contract the calling topic consumes — don't change `Respond_to_Copilot` outputs or `workflowId` without checking the topic that depends on them.

## Rules

- **Read-only inspection.** `flow_run_inspect.py` only GETs run history — it never invokes, patches, or deletes a flow. The only mutation path is a fix applied via `workflows/update`.
- **Exercise before you inspect.** Run history only exists after the flow has run. If there is no recent run, exercise the flow first (isolated or in-context), then inspect — and allow a few seconds for eventual consistency.
- **A `Succeeded` handler is not a `Succeeded` flow.** Read scope status, not just handler status (see the interpretation reference). This is the trap that masks a connector 400 as a generic 500.
- **TRACK PROGRESS.** Use the todo list tool to track the loop so the maker can see where you are.

## Identify the flow

Read `.local/config.json` for `agent.folder` and `agent.slug`. List the workflow folders under `{agent.folder}/workflows/` — each holds a `metadata.yml` (with `workflowId`, `name`) and a `workflow.json`. Match the user's request to a folder by name or `metadata.yml` display name; if ambiguous, list them and ask. The **flow GUID** you pass to the inspector is `workflowId` from that `metadata.yml`.

## Exercise the flow

Pick the mode by the question you're answering:

- **Isolated — is the fault in the flow itself?** Have the maker open the flow in Power Automate (make.powerautomate.com → the agent's environment → Solutions → the solution containing the flow), open it, and click **Test → Manually**, supplying the inputs the flow's trigger expects. This removes the topic from the picture — a failure here is purely the flow (or the backend it calls).
- **In context — is the fault in how the topic calls it?** Drive the topic that invokes the flow with the `topics/test` skill (`scripts/drive_topic.py`). This exercises the real request the topic builds and passes in. Use this when the flow tests clean in isolation but the topic still misbehaves.

Either way, the flow produces a run you then inspect.

**Exercise the failure inputs, not just the happy path.** By default, drive the flow with a **set** of inputs that includes its error conditions — a **missing record** (an id/key that doesn't exist), an **unauthorized / needs-consent** call, and a **malformed / out-of-range** input the connector rejects — alongside the valid request. These are the runs where the scope-vs-handler trap below actually bites, and they are the ones skipped when testing by hand. Derive them from the flow's trigger inputs and the scenario's template config; run the failure inputs first.

## Read the run history (the decisive surface)

Dump the latest run's action cascade:

```
python scripts/flow_run_inspect.py --flow <workflowId>
```

The **environment id** is resolved automatically from the active agent's Dataverse org URL — pass `--environment <env-guid>` only to override. The tool acquires a Flow-scoped token automatically via the kit's sign-in (set `FLOW_API_TOKEN` only to bring your own). Add `--run <run-guid>` to inspect a specific earlier run instead of the latest.

Interpret the cascade with **`src/reference/ess-docs/operations/flow-run-inspection.md`** — read it before drawing a conclusion. The essentials:

- **The first `Failed` action is usually the real fault**; everything after it is fallout. Its **statusCode** localizes why — `400` bad request body, `401`/`403` auth/consent, `404` wrong table or missing record, `429`/`5xx` throttling or transient backend.
- **A `Failed` scope with a `Succeeded` catch handler** commonly routes to a catch-all Response that returns a generic 500 and discards the handler's error body — so the user's "something went wrong (500)" is often a masked 400. Look at scope status, not just handler status.
- **`Skipped` actions show the path not taken** — a skipped success branch alongside a run error branch confirms the flow took its failure path.

## Localize and fix

Map the failing action's `name` back to `workflow.json` and compare the intended path to the actual path — the gap is the bug. Then fix at the right layer:

- **Bad request body (a `400` from the orchestrator's connector call)** — for the ESS common-orchestrator flows, the request is built from a **template config** read by `scenarioName`, not hardcoded in the flow. A missing or mis-mapped field is usually a template-config fault, not a `workflow.json` fault. Check the scenario's template config mappings first.
- **Auth (`401`/`403`)** — the connection reference isn't consented, is stale, or lacks entitlement; re-check the agent's `connectionreferences.mcs.yml` and re-consent in the environment. This is a connection fix, not a flow-logic fix.
- **Flow logic (wrong branch, wrong mapping, missing action)** — apply the edit through the `workflows/update` skill so the local working copy and Copilot Studio stay in sync, then re-exercise.

## Report

Summarize for the maker:

- How the flow was exercised (isolated / in-context) and whether a run was produced.
- The **first failing action + statusCode**, and whether the fault is in the flow, its template config, the connection, or the calling topic.
- The concrete fix and where it belongs (`workflow.json`, template config, connection reference), and a reminder to **publish** after pushing.
