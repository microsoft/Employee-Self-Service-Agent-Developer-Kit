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
they're saved. `--complete` marks the Task done — **and every other plan task this
run fully produced**: a single `/setup` run records the environment *and* clones
the agent, so it also completes the base-agent task when the plan splits them (one
run → one *or more* tasks closed). (Artifacts a skill writes
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

## Reconcile a first-run setup that already ran

On a shared agent the Power Platform admin usually runs `/setup` as their
**first-run experience** — before, or outside, any planner session. So by the
time anyone engages the planner the environment can already exist in
`.local/config.json` while the plan's setup task still reads **Not started**.
Fold that finished setup into the plan automatically — but **only once**. The
guard is a read-only status probe:

```
python scripts/planner/cli.py setup-status
```

It prints JSON: `setupTaskOpen` (the plan has a setup task that isn't Completed),
`environmentPinned` (a reusable environment **URL** is on the plan), and the
pinned `environment`. When **`setupTaskOpen` is true** *and* `.local/config.json`
shows setup finished — `setup` is `"complete"` with a `dataverseEndpoint`
recorded (`setup.py` writes those on a normal first run; it does **not** write an
`environmentId`) — the setup already ran but was never captured — reconcile it:
preview with `capture-setup --dry-run`, confirm the detected environment with the
person, then pin + complete it:

```
python scripts/planner/cli.py capture-setup --complete
```

That records `primaryEnvironment` (and the cloned agent) and marks the setup
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

### When `/setup` is blocked before it records the environment

`/setup` only writes the environment into `.local/config.json` once it finishes
connecting to the deployed agent. If it's blocked **earlier** — most often because
the ESS agent (the Marketplace declarative agent) isn't available for the tenant
yet, so the install can't complete — nothing lands in `config.json`, so
`capture-setup` has nothing to observe and the environment the maker **did**
create would be lost from the plan. Don't let that happen. When the Power
Platform admin tells you they created (or decided) the environment but setup
couldn't finish, persist it from what they tell you via the **ask** path — pin
`primaryEnvironment` directly, and **without** `--complete`:

```
python scripts/planner/cli.py pin-output --task <setupTaskId> --key primaryEnvironment \
  --kind Environment --attr environmentUrl=<org-url> [--attr environmentId=<guid>] --source User
```

(`setupTaskId` comes from `setup-status`; confirm the environment URL with them
first.) This records `primaryEnvironment` on the plan — so `setup-status` now
reports it and every *other* persona's `task-brief` can nudge them to `/setup`
into **that** environment — while the setup task stays **open**. Never pass
`--complete` here: the agent still isn't installed, so the setup task's work isn't
done. Keep it moving but unfinished:
`python scripts/planner/cli.py set-state --task <setupTaskId> --state InProgress`.
When the install is later unblocked and `/setup` finishes for real, the normal
observed capture (`capture-setup --complete`) pins the cloned agent and closes the
task.

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

## Progress

- Advance Task state as work happens:
  `python scripts/planner/cli.py set-state --task <T#> --state InProgress|Completed`.
- Completing a Task whose `produces` keys are now pinned can unblock downstream
  Tasks that `consume` them — point that out to the sponsor.
- Show `python scripts/planner/cli.py summary` so "where are we" is answerable
  at a glance.
