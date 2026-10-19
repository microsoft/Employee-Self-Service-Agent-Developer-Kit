# Planner — Status & deployment reports (where the rollout stands)

When someone asks **"what's the latest status on the ESS deployment?"**, "how's
the rollout going?", or "what's been done so far?", don't re-interview them and
don't rebuild the plan — **read the plan and report where it stands**: the
milestone reached, what was recently completed and by whom, and what comes next.
On request, hand them a **downloadable snapshot report**.

The plan is the shared source of truth, so anyone on the deployment team can see
where things stand. Status is a **read** — surface it in plain language; never
mention files, the CLI, or these skills to the person asking.

**Only people on the deployment team can see the plan.** There are no dedicated
plan-viewer or plan-editor roles — access comes from holding **any** assigned
rollout role. So if the shared planner reports the person asking has no access (or
they tell you they aren't assigned to the deployment), don't fabricate a status:
explain plainly that viewing the plan needs a rollout role, and they should ask
someone on the deployment team to assign them one. Don't read the plan out to
someone the service won't show it to.

## Step 1 — Read the current state (don't reconstruct it)

Pull the latest plan and read its state off the ledger — every number and state
must come from the plan, never guessed:

```
python scripts/planner/cli.py summary
python scripts/planner/cli.py check-deps
```

`summary` gives the objective, every task with its **state** (NotStarted /
InProgress / Completed / Blocked) and owner, the scenario dependencies, and what each
task has **produced** so far. `check-deps` shows which scenario prerequisites are
met vs missing. (If the shared planner is reachable, pull first — `sync.md` — so
you're reporting the shared truth, not a stale local cache.)

Keep local completion and shared confirmation separate. Do not count a
`pendingSync` task as confirmed shared completion; label it "Complete locally -
awaiting shared confirmation." Name `pendingOutputs` as saved partial work, not
completed work. If refresh failed, label the report as the last retrieved copy.
For every blocked task, use `task-brief` to name the missing input/decision and
the owner or role that can resolve it. Include deferred systems and nominations
without asking the maker the same questions again.

## Step 2 — Report it in plain language

Summarise, don't dump the table. Cover three things:

- **Milestone — where in the rollout we are.** Derive it from task states across
  the streams (setup → connect → author → evaluate → publish): the furthest stage
  with completed work, and what's in flight. E.g. *"Environment is set up and
  ServiceNow is connected; HR knowledge authoring is in progress."*
- **Recent tasks completed — and who did them.** List the tasks now `Completed` and the
  person/role that owns each (from the assignment on the task). E.g. *"Priya
  connected Workday; Sam finished the HR knowledge source."* If a task is `Completed`
  but has no owner recorded, say it's done without inventing a name.
- **What's next.** The tasks that can be picked up now — those whose state is
  **NotStarted** *and* whose dependencies are met (the summary's **State** column
  reads **⬜ Not started**, not **🔒 Not started**), and who they're waiting on. A
  cleared dependency alone isn't enough: an `InProgress`, `Completed`, or `Blocked`
  task can also show a clear dependency marker, so filter to **NotStarted** before
  presenting anything as "next". Call out anything **🔒 Blocked** and the upstream
  task it waits on, so nobody starts work whose inputs don't exist yet.
- **Vacant roles — flag them so they get filled.** A role the plan assigns work to
  but with **no active holder** — nobody was ever attested, or the person who held
  it was removed / is no longer linked to the plan — is a silent stall: vacancies
  can't be announced proactively, so a status read is the one moment to catch them.
  Read the plan's role assignments (`list_plan_role_assignments` — active holders
  only) against the roles its tasks need; for any attestable role with no
  active holder, name it and the work waiting on it (*"Heads up — the Workday admin
  role is vacant, so the Workday connection tasks can't start until someone holds
  it. Want to assign it?"*) and route filling it through role assignment
  (`src/skills/roles/nudge.md` → `src/skills/roles/attest.md`). Read who's missing
  off the plan — never guess a name.

Keep it to a short readout the sponsor can act on, then offer the snapshot report.

## Step 3 — Offer a static snapshot report (timestamped, downloadable)

If they want something to share or keep, write a **static markdown snapshot** of
the status — a picture of this moment, not a live document:

- Write it to **`workspace/plan/reports/`** as
  **`<YYYYMMDD-HHMMSS>-ESSdeploymentReport.md`** (e.g.
  `workspace/plan/reports/20260703-142530-ESSdeploymentReport.md`). Create the
  `reports/` folder if it doesn't exist. The **time** component matters: every
  request must produce a **new** file, and a date-only name would collide when two
  snapshots are taken the same day. If a file with that exact timestamp somehow
  already exists, append a short numeric suffix (`-2`, `-3`, …) so an existing
  snapshot is never overwritten.
- This folder is **only for deployment-plan reports**. It is deliberately separate
  from FlightCheck's readiness output (`workspace/flightcheck/`) so the two report
  kinds never mix.
- The report is **static**: once written it is **not** updated over time. A later
  status request writes a **new** timestamped file; it never rewrites an old one.
  That's the point — each file is a snapshot you can compare against.

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

Then **surface it as a downloadable link in chat** — a clickable Markdown link to
the file you just wrote, so they can open or save it, e.g.

```
📄 [20260703-142530-ESSdeploymentReport.md](workspace/plan/reports/20260703-142530-ESSdeploymentReport.md) — download your status report
```

(use the real filename you wrote). Say it in their terms too ("I've saved a status
report you can share") — the link carries the file, so you never paste a bare path
in prose.

## Do / don't

- **Do** read the plan every time — status is always the *current* ledger, pulled
  fresh, never remembered from earlier in the conversation.
- **Do** name who completed each task from the plan's assignments; **don't**
  attribute work to a person the plan doesn't record.
- **Don't** change the plan while reporting status — this flow is **read-only**
  (plus writing the snapshot file). Task state changes go through capture
  (`src/skills/planner/capture.md`), not here.
- **Don't** update or overwrite an existing timestamped report; each request is a
  new snapshot.
- **Don't** put deployment reports in the FlightCheck folder, or FlightCheck
  results in `workspace/plan/reports/` — keep the two separate.
