# Planner — Status & deployment reports (where the rollout stands)

When someone asks **"what's the latest status on the ESS deployment?"**, "how's
the rollout going?", or "what's been done so far?", don't re-interview them and
don't rebuild the plan — **read the plan and report where it stands**: the
milestone reached, what was recently completed and by whom, and what comes next.
On request, hand them a **downloadable snapshot report**.

The plan is the shared source of truth, so anyone on the deployment team can see
where things stand. Status is a **read** — surface it in plain language; never
mention files, the CLI, or these skills to the person asking.

## Step 1 — Read the current state (don't reconstruct it)

Pull the latest plan and read its state off the ledger — every number and state
must come from the plan, never guessed:

```
python scripts/planner/cli.py summary
python scripts/planner/cli.py check-deps
```

`summary` gives the objective, every task with its **state** (NotStarted /
InProgress / Done / Blocked) and owner, the scenario dependencies, and what each
task has **produced** so far. `check-deps` shows which scenario prerequisites are
met vs missing. (If the shared planner is reachable, pull first — `sync.md` — so
you're reporting the shared truth, not a stale local cache.)

## Step 2 — Report it in plain language

Summarise, don't dump the table. Cover three things:

- **Milestone — where in the rollout we are.** Derive it from task states across
  the streams (setup → connect → author → evaluate → publish): the furthest stage
  with completed work, and what's in flight. E.g. *"Environment is set up and
  ServiceNow is connected; HR knowledge authoring is in progress."*
- **Recent tasks completed — and who did them.** List the tasks now `Done` and the
  person/role that owns each (from the assignment on the task). E.g. *"Priya
  connected Workday; Sam finished the HR knowledge source."* If a task is `Done`
  but has no owner recorded, say it's done without inventing a name.
- **What's next.** The tasks that can be picked up now (no unmet dependency — the
  summary's **Blocked by** column is `—`), and who they're waiting on. Call out
  anything **Blocked** and the upstream task it waits on, so nobody starts work
  whose inputs don't exist yet.

Keep it to a short readout the sponsor can act on, then offer the snapshot report.

## Step 3 — Offer a static snapshot report (timestamped, downloadable)

If they want something to share or keep, write a **static markdown snapshot** of
the status — a picture of this moment, not a live document:

- Write it to **`workspace/plan/reports/`** as
  **`<YYYYMMDD>-ESSdeploymentReport.md`** (e.g.
  `workspace/plan/reports/20260703-ESSdeploymentReport.md`). Create the `reports/`
  folder if it doesn't exist.
- This folder is **only for deployment-plan reports**. It is deliberately separate
  from FlightCheck's readiness output (`workspace/flightcheck/`) so the two report
  kinds never mix.
- The report is **static**: once written it is **not** updated over time. A later
  status request writes a **new** dated file; it never rewrites an old one. That's
  the point — each file is a snapshot you can compare against.

Compose the report yourself from what Step 1 read — do not invent content and do
not call a generator; this is a formatted view of the plan. Include:

```
# ESS deployment — status report (<human date>)

**Milestone:** <where the rollout is>
**Objective:** <the plan's objective>

## Recently completed
- <task> — <who> — <when, if known>

## In progress
- <task> — <owner>

## Next up (ready to start)
- <task> — <owner/role>

## Blocked
- <task> — waiting on <upstream task>

## Scenarios in scope
- <scenario> — <system> — <met / prerequisite missing>
```

Then tell them it's saved and where to find it — in their terms ("I've saved a
status report you can share"), never the raw path.

## Do / don't

- **Do** read the plan every time — status is always the *current* ledger, pulled
  fresh, never remembered from earlier in the conversation.
- **Do** name who completed each task from the plan's assignments; **don't**
  attribute work to a person the plan doesn't record.
- **Don't** change the plan while reporting status — this flow is **read-only**
  (plus writing the snapshot file). Task state changes go through capture
  (`src/skills/planner/capture.md`), not here.
- **Don't** update or overwrite an existing dated report; each request is a new
  snapshot.
- **Don't** put deployment reports in the FlightCheck folder, or FlightCheck
  results in `workspace/plan/reports/` — keep the two separate.
