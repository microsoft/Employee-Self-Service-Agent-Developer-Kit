# Planner — Phase 6: Capture what a Task produced

A Task declares the output **keys** it should yield (`produces`, grounded from
Learn). When an assignee finishes a Task, fill a value for each key — then
**confirm with the person who did it** before pinning it onto the Plan. Two
ways to fill a value:

## (a) Observe — read it from what the action changed

Preferred for kit-skill Tasks that leave a signal. The canonical case is the
setup hand-off: after `/setup` runs (onboarding the ADK to the deployed agent),
it **records ids + names into `.local/config.json`** — the environment it
connected to (id/URL), the agent it clones into the workspace (`botId`,
`schemaName`, name, folder/slug), and anything else the run wrote. It doesn't
create the environment. `capture-setup` is **generic**: it diffs the whole
`config.json` and pins **every** id + name (and any other artifact a skill
recorded), not just a single value:

```
python scripts/planner/cli.py capture-setup --complete
```

`--task` is optional — with it omitted the CLI **auto-detects the plan's setup
task** (the task that produces `primaryEnvironment`) and completes it. **You (the
planner) run this after `/setup` returns** — the unchanged setup/onboarding flow
does not call it, so confirm the detected values with the assignee and invoke
`capture-setup` yourself (use `--dry-run` first to preview, then re-run to pin).

This reads the current `.local/config.json` and prints **every** artifact it will
pin from what changed — e.g. an `Environment` (the `environmentId` + URL), an
`Agent` (the cloned agent's `botId`, `schemaName`, name, folder), and any other
id + name object a skill wrote (a `Connection`, an `EntraApp`, or an unknown
shape captured as `Custom`). Known shapes get a nice kind/key; everything else is
captured generically. Show the assignee the detected values and confirm before
they're saved. `--complete` also marks the Task done. (Artifacts a skill writes
*outside* `config.json` are handled by ask-mode `pin-output` or their own
detectors — see below.)

Do **not** trust the agent's narration ("I created env X"); the value is read
from real state the action changed.

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

## Guide the assignee with what earlier tasks produced

Before an assignee starts a task, brief them — this back-propagates the details
setup (and earlier tasks) produced:

```
python scripts/planner/cli.py task-brief --task <T#>
```

It prints which skill to run, their role, the **values to use** (e.g.
`primaryEnvironment: environmentId=<id>` from setup), and the outputs to capture.
So the Workday assignee is told "use env `<id>`, run `/connect`, then we'll pin
the connection" — no re-discovery.

**Every non-setup persona connects their own kit first.** The environment id is a
*plan* fact once the Power Platform admin's `/setup` pins `primaryEnvironment`,
but each assignee's own kit still has to connect to that same environment before
their task's skill will work. `task-brief` handles the nudge: for a kit-skill task
that isn't setup, once the plan has an environment pinned it prints **"First
connect your kit: run /setup and choose environment `<envId>`"**. So the
Workday / topics / eval assignee is nudged to `/setup` into the *plan's*
environment — never to pick or create a different one. If the plan has **no**
environment pinned yet, the admin's setup task hasn't run — that task is the
prerequisite, so don't nudge others to setup; tell them it's blocked on setup.

## Downstream reads it off the Plan

Once pinned, a later Task reads the value straight from the Plan — no
re-discovery. Example: the eval author's Task consumes `primaryEnvironment`, so
they read the `environmentId` from the summary/plan rather than hunting for it.

## How completion persists outputs to WeveNova

With `--store mcp`, completing a Task that produced outputs is a **single bulk
call**: the CLI transitions `NotStarted → InProgress` if needed, then calls
WeveNova's `complete_project_plan_task` carrying **all** the Task's pinned
(`Active`) outputs in one array — WeveNova records outputs only at completion, so
this one call both finishes the Task and persists its artifacts (it is not one
call per output, and outputs are never pushed by a plain state change). The
output `kind` is clamped to WeveNova's enum (`Environment`, `Connection`,
`KnowledgeSource`, `Custom`); richer local kinds like `EntraApp`/`Agent` fold to
`Custom` on the wire while the local plan keeps the precise kind. After the push
the CLI re-fetches the authoritative plan and re-renders `plan.json` +
`ESS-scenario-plan.md`. A pinned output whose producing Task isn't `Completed`
yet stays local until that Task completes.

## Progress

- With `--store mcp`, confirm the WeveNova plan is **Active** before starting,
  completing, or cancelling a task. If it is Draft, stop and have the plan
  resource owner activate it; do not retry the task mutation as an ETag conflict.
- Advance Task state as work happens:
  `python scripts/planner/cli.py set-state --task <T#> --state InProgress|Completed|Cancelled`.
- Completing a Task whose `produces` keys are now pinned can unblock downstream
  Tasks that `consume` them — point that out to the sponsor.
- Show `python scripts/planner/cli.py summary` so "where are we" is answerable
  at a glance.
