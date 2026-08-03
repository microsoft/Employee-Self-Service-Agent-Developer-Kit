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

## (b) Ask — the assignee tells you

For manual/portal/external Tasks, or any output not observable from local state
(e.g. an Entra app id registered in the portal), ask the assignee for the value
and pin it. Record it against the Task's produced key with provenance marked as
supplied by the person. (Set the values via a follow-up `set-context`/output
step or record them in the Task's notes; the environment case above is the one
with a built-in detector today.)

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
