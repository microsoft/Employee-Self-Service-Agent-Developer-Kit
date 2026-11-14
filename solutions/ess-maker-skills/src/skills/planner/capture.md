# Planner — Phase 6: Capture what a Task produced

> **Planner session entry:** Follow `src/skills/planner/SKILL.md` -> **Intent gate**,
> then **Gate** for the workspace bootstrap on first Planner use. Reuse its successful result
> in the same chat and workspace before continuing this flow.
> Apply its **Communication rules** to every reply and next-step handoff.

A Task declares the output **keys** it should yield (`produces`, grounded from
Learn). When an assignee finishes a Task, fill a value for each key — then
**confirm with the person who did it** before pinning it onto the Plan. Two
ways to fill a value:

## (a) Observe — read it from what the action changed

Preferred for kit-skill Tasks that leave a signal. The canonical case is the
setup hand-off: when `/setup` finishes creating or connecting the ESS agent, it
**records ids + names into `.local/config.json`** — the environment it selected
(its `environmentId`), the agent it creates or connects and brings into the
workspace (`botId`, `schemaName`, name, folder/slug), and anything else the run
wrote. `/setup` selects an environment but never creates one. `capture-setup` is
**generic**: it diffs the whole `config.json` and pins **every** id + name (and
any other artifact a skill recorded), not just a single value:

```
python scripts/planner/cli.py capture-setup --complete
```

`--task` is optional — with it omitted the CLI **auto-detects the plan's setup
task** from `primaryEnvironment` or `provisionedEnvironment`, choosing the first
unfinished producer in dependency order. The environment is pinned under that
task's **declared output key**, including when `--task` is supplied; `--key` is an
explicit override, not required for provisioning. `setup-status` reports the
selected `setupTaskId` and `setupEnvironmentKey`. Do not relabel a provisioned
environment as a completed workspace binding. **You (the
planner) run this after `/setup` returns** — the setup handoff returns control
here; `/setup` itself never writes the plan. Confirm the detected
values with the assignee and invoke
`capture-setup` yourself (use `--dry-run` first to preview, then re-run to pin).
Add `--complete` only when `setup-status` reports `workspaceSetupReady: true`.
If `/setup` returned before every foundation step finished (for example a
required connection or FlightCheck is still outstanding), pin without
`--complete` and leave the task open.

This reads the current `.local/config.json` and prints **every** artifact it will
pin from what changed — e.g. an `Environment` (the `environmentId`, plus the URL
when the config records one), an `Agent` (the recorded agent's `botId`,
`schemaName`, name, folder), and any other
id + name object a skill wrote (a `Connection`, an `EntraApp`, or an unknown
shape captured as `Custom`). Local `Agent` and `EntraApp` artifacts are mapped to
the supported remote `Custom` kind with `artifactType` metadata by the sync adapter.
Known shapes get a nice kind/key; everything else is
captured generically. Show the assignee the detected values and confirm before
they're saved. `--complete` marks the Task done — **and every other plan task this
run fully produced**: a single `/setup` run records the environment *and* the
agent it creates or connects, so it also completes the agent task when the plan
splits them (one run → one *or more* tasks closed). (Artifacts a skill writes
*outside* `config.json` are handled by ask-mode `pin-output` or their own
detectors — see below.)

Do **not** trust the agent's narration ("I created env X"); the value is read
from real state the action changed.

### `/discover` closes its own inventory task

`tenantInventory` is observed too, but from a different signal than `capture-setup`
diffs. `/discover` writes the durable mirror `.local/inventory.json` and a per-run
`workspace/discover/results.json` — not the `config.json` id + name objects the
generic sweep pins. So the discover skill runs its own detector when a run finishes:

```
python scripts/planner/cli.py capture-discover --complete
```

It auto-detects the plan's discover task (the one that produces `tenantInventory`),
summarizes `results.json` into a single `Custom` artifact — the per-kind resource
counts, the write path, and a pointer to `.local/inventory.json` — and completes the
task. It's a safe no-op (exit 1, nothing written) when the workspace has no plan or no
task produces `tenantInventory`, so a standalone `/discover` leaves the plan untouched.
You never pin `tenantInventory` by hand.

## Sync each local complete to the shared plan — in the same flow

`capture-setup --complete`, `capture-discover --complete`, `pin-output
--complete`, and `set-state --state Completed` mark the task **Completed in the local cache and flag it
`pendingSync`** — "done locally, not yet on the shared plan". That flag is a
durable retry marker, not confirmation. For an already-shared **Active** plan,
sync in the same turn. A local draft remains local until explicit first-share
consent; a Shared draft waits for explicit activation. Never publish or activate
merely to drain the queue:

1. Read the sync arguments — `python scripts/planner/cli.py pending-sync` prints
   `{projectId, planId, tasks:[{taskId, etag, outputs}, …]}` for every pending
   task, including its `operation`. `pendingOutputs` lists partial artifacts
   separately; these are not completion requests.
2. Process the payload in dependency order, upstream tasks first. After each
   upstream readback, refresh readiness for its dependents. For each task,
   verify the parent is **Active**, the task has no unmet inputs, and
   there is no reported conflict. If the remote task is NotStarted, transition it
   to InProgress only for work the assignee actually performed, using its matching
   ETag; use the new task ETag from that response for completion. Never use the
   plan's activation ETag. A 412 requires reconciliation, not blind retry.
   Call **`complete_project_plan_task`** (`projectId`, `planId`,
   `taskId`, `outputs`, `etag`) — the Ongoing-edits tool in
   `src/skills/planner/sync.md`. The `outputs` `pending-sync` hands you are
   already compact — a key, a kind, a few value-add attributes (id, name, counts)
   and an `inventoryRef` pointer. **Pass them through as-is; never swap in bulk
   detail** (e.g. a full `/discover` crawl or an inventory dump). The service
   stores a task's outputs in a small fixed budget and rejects an oversized
   completion outright — the detail belongs in its durable record, which the
   `inventoryRef` points at.
   If the payload names `set_project_plan_task_state` because the task has no
   outputs, use that operation with `state: Completed`; the output-completion
   endpoint correctly rejects an empty output list.
3. **On success**, re-hydrate (`get_project_plan` + `list_project_plan_tasks` →
   `import-remote-plan`) so the cache carries the server's confirmation — that
   clears `pendingSync` only when the completed state **and the expected output
   values** are present. Do not clear it merely because a tool call was attempted.
4. **On failure**, walk the sign-in ladder at the top of `sync.md` (401 → one MCP
   restart + one retry → then local). If it still can't reach the shared plan the
   completion stays saved locally as `pendingSync` and can be retried on the next
   successful entry. Say "Completed locally; the shared plan hasn't confirmed it
   yet." On a conflict, preserve the original ETag and ask to reconcile; do not
   replay automatically with a newer tag.

You never have to be asked to sync, and the sponsor never triggers it. The task
reads **Complete locally - awaiting shared confirmation** until readback proves
otherwise. A later pull preserves the completion and its outputs. The initial
share associates the draft using its successful create response
(`import-remote-plan --created-plan-file`, as described in `sync.md`) before
mapping unique task titles to the server's new IDs. A normal pull cannot infer
that association. Missing proof or ambiguous/missing matches preserve the draft
and stop for reconciliation, never create duplicate tasks silently.

## Reconcile a first-run setup that already ran

Makers often run `/setup` as their **first-run experience** — before, or
outside, any planner session. So by the time anyone engages the planner the
environment (and agent) can already be recorded in `.local/config.json` while
the plan's setup task still reads **Not started**.
Fold that finished setup into the plan automatically — but **only once**. The
guard is a read-only status probe:

```
python scripts/planner/cli.py setup-status
```

It prints JSON: `setupTaskId` and `setupEnvironmentKey` (the selected task and its
declared environment output), `setupTaskOpen` (that task isn't Completed),
`environmentPinned` (a reusable environment **URL** is on the plan), the pinned
`environment`, and `workspaceSetupReady` (canonical per-agent readiness:
`.local/setup/config.json` has `schema_version: 4` and the `agents` entry for the
`.local/config.json` `activeAgent` reports `connect_ready: true`). When
**`setupTaskOpen` is true** *and* **`workspaceSetupReady` is true**, with a
verified `environmentId` recorded in `.local/config.json`, the setup already ran
but was never captured. The `setup` field in `.local/config.json` is not
evidence: `/setup` writes it when it brings the agent into the workspace, before
every foundation step is done. When `workspaceSetupReady` is false, leave the
setup task open. Guided setup records the
`environmentId` and the agent identity without a `dataverseEndpoint`; when an
older workspace config also records a `dataverseEndpoint`, the `environmentId`
must belong to that URL. If the ID is missing, resolve it first; a URL alone is
not a shareable Environment completion. Reconcile it:
preview with `capture-setup --dry-run`, confirm the detected environment with the
person, then pin + complete it:

```
python scripts/planner/cli.py capture-setup --complete
```

That records the selected task's `setupEnvironmentKey` (and the recorded agent) and marks the setup
task — plus every other task this run fully produced — Complete, so from now on
everyone sees that environment on the plan. When **`setupTaskOpen` is false** (no
setup task, or it's already Completed) there is nothing to reconcile — **skip
silently**; never re-run `capture-setup`, or it would re-pin the same environment
on every engagement. This is the automatic complement to the manual "run this
after `/setup` returns" above: the **same** command, fired by the `setup-status`
guard on planner engagement instead of by a just-finished `/setup`.

## (b) Ask — the assignee tells you, then commit it

For Tasks whose output isn't observable from local state — a Workday connection,
an Entra app registered in the portal, an eval suite — ask the assignee for the
value(s) and **commit them to the plan** with `pin-output`:

```
python scripts/planner/cli.py pin-output --task <T#> --key <producedKey> \
  --kind Connection|EntraApp|KnowledgeSource|Custom \
  --attr <name>=<value> [--attr <name>=<value> ...] --complete
```

Example — the Workday connect assignee committing what they created:

```
python scripts/planner/cli.py pin-output --task T2 --key workdayConnection \
  --kind Connection --attr connectionId=<id> --attr connector=shared_workdaysoap --complete
```

Use `capture-setup` for the environment (observed); use `pin-output` for
connections / apps / suites an assignee created (asked). Confirm the values with
the person before committing.

### When the environment exists before `/setup` records it

`/setup` never creates environments, and it writes `.local/config.json` only
after it creates or connects the ESS agent. So the environment usually exists
**before** anything lands in `config.json`: the Power Platform admin creates or
chooses it in the Power Platform admin center before any maker runs `/setup`, or
`/setup` stopped before its agent step. Either way `capture-setup` has nothing to
observe, and the environment would be missing from the plan. Don't let that
happen. When the Power Platform admin tells you the environment is ready, persist
it from what they tell you via the **ask** path. Use the selected task's declared
`setupEnvironmentKey`, initially **without** `--complete`:

```
python scripts/planner/cli.py pin-output --task <setupTaskId> --key <setupEnvironmentKey> \
  --kind Environment --attr environmentId=<verified-guid> --source User
```

(`setupTaskId` and `setupEnvironmentKey` come from `setup-status`. The
environment ID is shown in the environment's details in the Power Platform admin
center; confirm it with them first.) This saves the declared environment output
**locally** as `pendingOutputs`, while the setup task stays **open**. It is not
yet visible to other workspaces: the service has no partial-output write endpoint.
For a **combined environment-and-agent task**, never pass `--complete` while the
agent is still missing: the task's work isn't done. Keep it moving but unfinished:
`python scripts/planner/cli.py set-state --task <setupTaskId> --state InProgress`.
When a maker later runs `/setup` into that environment and it finishes, the
normal observed capture (`capture-setup --complete`) pins the agent and closes
the task.

For an **environment-only task** (a provision-only task under
`provisionedEnvironment`, or the Power Platform admin's `primaryEnvironment` task
when agent setup is its own task, as in the Workday reference), confirm that its
own acceptance criteria and all declared outputs are satisfied: the environment
exists and the maker has the Environment Maker role in it. It can then be
completed with `pin-output --complete`, even before workspace config exists.
Keep the separate agent setup and binding tasks open until their own work and
prerequisites are satisfied; do not pin their outputs (such as a binding task's
`primaryEnvironment`) just to close them.

For new plans, split the environment task and the agent setup task at their
role/milestone boundary (`model.md`). A genuinely finished environment task can
then be completed and shared while the agent setup task remains open. For an
existing combined task, retain its partial output and explain the limitation;
split it only with approval. Never fake completion to make metadata shareable.

## Guide the assignee with what earlier tasks produced

Before an assignee starts a task, brief them — this back-propagates the details
setup (and earlier tasks) produced:

```
python scripts/planner/cli.py task-brief --task <T#>
```

It prints which skill to run, their role, the **values to use** (e.g.
`primaryEnvironment: environmentId=<id>` from setup), and the outputs to capture.
For a shared plan, pending metadata is not an execution-ready shared input.
Complete the upstream sync and read back its outputs before starting dependent
work. A blocker naming **shared confirmation** is not a request to provision
another environment. Already-finished offline work may still be captured locally;
its pending status remains visible until reconciliation.
So the Workday assignee is told "use env `<id>`, run `/connect-workday`, then we'll
pin the connection" — no re-discovery.

**Check this person's workspace, not just their role.** The environment id is a
*plan* fact once the Power Platform admin's environment task pins
`primaryEnvironment`, but each assignee's own kit still has to connect to that
same environment before their task's skill will work. `task-brief` reads the
workspace's canonical setup state and config, and suppresses the nudge when the
active agent reports `connect_ready: true` and `.local/config.json` records the
plan's environment and agent. Do not repeat `/setup` for a person whose
workspace is already bound.
For a ready task that needs the environment and an unbound workspace, it prints **"First
connect your kit: run /setup and choose environment `<envId>`"**. So the
Workday / topics / eval assignee is nudged to `/setup` into the *plan's*
environment — never to pick or create a different one. If a required environment
is missing or unconfirmed, name that blocker instead. Work that does not consume
an environment does not gain an extra setup prerequisite.

## Downstream reads it off the Plan

Once pinned (and confirmed shared on a shared plan), a later Task reads the value straight from the Plan — no
re-discovery. Example: the eval author's Task consumes `primaryEnvironment`, so
they read the `environmentId` from the summary/plan rather than hunting for it.

## Progress

- Advance Task state as work happens:
  `python scripts/planner/cli.py set-state --task <T#> --state InProgress|Completed`.
- Whenever a `--complete` (or `set-state ... Completed`) closes a task, **sync it
  to the shared plan in the same turn** — see *Sync each local complete to the
  shared plan* above; don't leave a completion sitting `pendingSync`.
- Completing a Task whose `produces` keys are now pinned can unblock downstream
  Tasks that `consume` them — point that out to the sponsor.
- After capture and any shared readback, follow `status.md` →
  **Refresh after progress**. Refresh the same caller's remaining work and brief its next action;
  do not stop at a completion checkmark or reuse the pre-action recommendation.
  If confirmation is still pending, show that without repeating the finished work.
- When topic outputs become available during the selected build task, continue
  the in-flow evaluation generation in `evaluate.md`. Preserve its review/push
  gates; do not tell the maker to discover and invoke a separate eval command.
