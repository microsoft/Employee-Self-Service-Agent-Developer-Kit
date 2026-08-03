# Planner — Phase 5: Capture what a Task produced

A Task declares the output **keys** it should yield (`produces`, grounded from
Learn). When an assignee finishes a Task, fill a value for each key — then
**confirm with the person who did it** before pinning it onto the Plan. Two
ways to fill a value:

## (a) Observe — read it from what the action changed

Preferred for kit-skill Tasks that leave a signal. The canonical case is the
setup hand-off: after `/setup` runs (onboarding the ADK to the deployed agent),
it **records** the environment & agent details into `.local/config.json` — it
connects to the environment and records its id/URL; it doesn't create it. Detect
and pin the environment:

```
python scripts/planner/cli.py capture-setup --task <T#> --complete
```

This reads the current `.local/config.json`, and — if an environment appeared
that wasn't there before — prints the artifact it will pin (the `environmentId`
and URL). Show the assignee the detected value and confirm before it's saved.
`--complete` also marks the Task done.

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
