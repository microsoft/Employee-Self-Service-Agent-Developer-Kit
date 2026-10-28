# Planner — Status & deployment reports (where the rollout stands)

> **Planner session entry:** Follow `src/skills/planner/SKILL.md` -> **Intent gate**,
> then **Gate** for the workspace bootstrap on first Planner use. Reuse its successful result
> in the same chat and workspace before continuing this flow.
> Apply its **Communication rules** to every reply and next-step handoff.

When someone asks **"what's the latest status on the ESS deployment?"**, "how's
the rollout going?", or "what's been done so far?", don't re-interview them and
don't rebuild the plan — **read the plan and report where it stands**: the
milestone reached, what was recently completed and by whom, and the requesting
person's next action. Team readiness is context, not a personal assignment.
On request, hand them a **downloadable snapshot report**.

The plan is the shared source of truth, so anyone on the deployment team can see
where things stand. Status is a **read** — surface it in plain language; never
mention files, the CLI, or these skills to the person asking.

**Only people on the deployment team can see the shared plan.** There are no dedicated
plan-viewer or plan-editor roles — access comes from holding **any** assigned
rollout role. So if the shared planner reports the person asking has no access (or
they tell you they aren't assigned to the deployment), don't fabricate a status:
explain plainly that viewing the plan needs a rollout role, and they should ask
someone on the deployment team to assign them one. Don't read the plan out to
someone the service won't show it to.

A maker can review their own unshared local draft without a shared role
assignment. This is not a workaround for **403/access denied** on a shared plan.

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

## Choose the requesting person's next step

**Your next step** must be actionable by the requesting person, not the first
ready task in the overall plan. Reuse the known maker/sponsor context and
confirmed responsibilities from the conversation. Do not ask for a role that is
already known, infer the caller from the project's owner ID, or assume they hold
the role on an arbitrary ready task.

For a shared plan, use **`list_project_plan_tasks_for_caller`** when selecting
the caller's execution work (`sync.md`, Flow 2), not the project-wide task list.
For a local draft with **no shared plan ID**, do not make caller-task or role
assignment calls. When the service is unavailable, use only known local
assignments as the best-effort fallback (`mytasks.md`) and label the status as
the last retrieved copy. An empty caller-task result is not proof of missing
access or a vacant role; it only means no open work was returned for this caller.
If responsibility is still unknown, report the authorized overview and say the
personal next step needs a confirmed responsibility; do not guess who the
requester is or force a role interview just to show status.

Choose one primary recommendation from the actual plan lifecycle:

| Requester | Plan state / task state | Your next step |
|-----------|------------------------|----------------|
| Maker / sponsor | Local draft | Review/refine the draft; when ready, share it so colleagues with access can review it. **Prompt:** "Share this plan." |
| Maker / sponsor | Shared draft | If you own the plan, activate it to enable assignments and tracked task updates. **Prompt:** "Activate this plan." Otherwise, ask the plan owner to activate it. Activation does not run tasks or deploy ESS automatically. |
| Maker / sponsor | Active | Fill a relevant vacant role for unfinished work (**Prompt:** "Assign people to the roles."), resolve a decision you own, or coordinate with the owner of a blocking task. If coordination is not needed, offer your own eligible task using caller-scoped results. |
| Assignee | Shared draft | Ask the plan owner to activate it before tracked task execution. A shared draft remains read-only even when a task's inputs are present. |
| Assignee | Active, own in-progress or ready task | Continue unblocked work already in progress before starting another task. Name the task and how to do it. For environment provisioning/selection or ESS installation, recommend `/setup`: "Start my environment setup task." or "Continue setup." Reuse the plan's environment if one is already pinned. |
| Assignee | Blocked tasks or no open assignments | Name the missing prerequisite and who can resolve it. Suggest unrelated eligible work only if it belongs to this caller; never substitute another person's ready work. If nothing is assigned, their next step is to ask the maker to assign the relevant role or task. |

If the maker chose **local-only drafting**, recommend the next local review or
decision; do not keep prompting them to share. Unknown systems or owners remain
pending decisions, not blanket blockers to sharing or activation. With multiple
roles, use the capacity in which the person is asking; do not silently switch
from maker coordination to admin execution.
If no unfinished work remains, say so instead of inventing a task or vacancy.
For an active plan, the maker can review the acceptance criteria and coordinate
closeout. A Completed or Archived plan must not trigger a suggestion to restart
work; a new version is a separate, explicit request.

Before recommending execution, read `task-brief` for the selected task. An
`InProgress` task is a **continue** action, not a new start; otherwise select a
`NotStarted` task with an empty `blockedBy`. A task explicitly `Blocked`, or
waiting on dependencies, is not ready even if it appears in the caller's list.
Follow `mytasks.md` for the owning workflow, including `/setup` for foundation
work and binding this person's workspace to the existing environment when needed.
Give the action, its purpose, and a concrete prompt or supported kit command.
Keep it brief; load the full walkthrough only if they ask to start.

**Status recommends; it does not execute.** Never share, activate, assign, claim,
or run a skill merely because its example prompt appears in the status readout.

## Refresh after progress

After a requested action changes task state, outputs, dependencies, assignments,
or the plan lifecycle, recompute the next action for the **same requester** in
the same flow. This includes successful, partial, or blocked setup and other
task runs, sharing, activation, role assignment, and resolving pending decisions.
Do not reuse the previous recommendation or make the person ask for status again.

1. Capture only verified outcomes using `capture.md`; one setup run can finish
   several tasks, but starting the skill or binding a workspace is not proof that
   every task finished. Preserve partial progress and the remaining blocker.
   If this run was already captured by the owning skill's handoff, do not capture
   it again or reopen its completed tasks.
2. For an already-shared Active plan, sync completed work and read back state
   **and outputs** before treating dependencies as cleared. Keep `pendingSync`
   visible if confirmation is missing. A failed refresh does not erase local
   progress or justify rerunning finished work; use the labeled fallback.
3. Read the updated summary and, when personal execution work is relevant, call
   `list_project_plan_tasks_for_caller` again. Keep that assignment scope, but
   reconcile state with the current ledger: a locally completed task awaiting
   confirmation is not a new task to start even if a stale service result lists
   it. Use fresh `task-brief` results and the current workspace config for
   remaining candidates, not a brief saved before the action.
4. Apply the requester/lifecycle policy above to that fresh state. Continue
   unfinished work, offer a newly ready task belonging to this person, or name
   the remaining blocker and its owner. If they have **no open work**, say so;
   another role's newly unblocked task is a handoff, not their next assignment.
   Stop recommending Share, Activate, or a role nomination once it is done.

Close with what changed and the updated **Your next step**, using the prominent
handoff in `src/reference/ui-formatting-guidelines.md`: a separate heading, a
bold action sentence, and its own continuation line. Recommend the next task;
**do not automatically start** it. A role assignment
does not prove the colleague's workspace is bound, and a completed workspace
binding does not require the same person to run `/setup` again.

### After activation

Use this example only when readback confirms the plan is Active and the roles for
unfinished work still have no owners. Derive any task count from that readback;
do not label activation as a completed rollout task.

> Your rollout plan is **Active**, confirmed on the shared plan.
> Activation did not run tasks or deploy ESS.
>
> ## Your next step
>
> **Assign people to the rollout roles.**
>
> The roles do not have owners yet, so their work is waiting for assignment.
>
> **Say:** "Assign people to the roles."

Use the same layout after sharing, editing, assigning, completing a task, or
reporting status, including blocked or pending-sync outcomes. Change the action
and continuation to fit the current requester and state; do not copy the vacancy
example when owners already exist. For an eligible admin setup task, bold the
task outcome and put **Run:** `/setup` on its own line. If setup was already
requested, continue it rather than asking the user to repeat the command.

## Step 2 — Report it in plain language

Summarise, don't dump the table. Include the relevant points:

- **Plan state.** Say whether this is a local draft, shared draft, or active plan,
  and whether shared status was refreshed. Dependency readiness alone does not
  mean the plan has been activated or its work assigned.
- **Milestone — where in the rollout we are.** Derive it from task states across
  the streams (setup → connect → author → evaluate → publish): the furthest stage
  with completed work, and what's in flight. E.g. *"Environment is set up and
  ServiceNow is connected; HR knowledge authoring is in progress."*
- **Recent tasks completed — and who did them.** List the tasks now `Completed` and the
  person/role that owns each (from the assignment on the task). E.g. *"Priya
  connected Workday; Sam finished the HR knowledge source."* If a task is `Completed`
  but has no owner recorded, say it's done without inventing a name.
- **Team readiness** (when useful as context). The tasks whose prerequisites are
  met — those whose state is
  **NotStarted** *and* whose dependencies are met (the summary's **State** column
  reads **⬜ Not started**, not **🔒 Not started**), and who they're waiting on. A
  cleared dependency alone isn't enough: an `InProgress`, `Completed`, or `Blocked`
  task can also show a clear dependency marker, so filter to **NotStarted** before
  presenting anything as ready. Call out anything **🔒 Blocked** and the upstream
  task it waits on. Another role's ready work belongs here or in the plan, not
  under the requesting person's next step.
- **Vacant roles — flag them so they get filled.** A role the plan assigns work to
  but with **no active holder** — nobody was ever attested, or the person who held
  it was removed / is no longer linked to the plan — is a silent stall: vacancies
  can't be announced proactively, so a status read is the one moment to catch them.
  For a shared plan, read its role assignments (`list_plan_role_assignments` —
  active holders only) against the roles its unfinished tasks need; for any attestable role with no
  active holder, name it and the work waiting on it (*"Heads up — the Workday admin
  role is vacant, so the Workday connection work has no owner."*) For the maker,
  recommend filling that vacancy through role assignment
  (`src/skills/roles/nudge.md` → `src/skills/roles/attest.md`). Read who's missing
  off the plan — never guess a name. For a local draft, report nominations from
  the local plan instead of querying shared role assignments.
- **Your next step**. Render this as the separate heading and bold action block
  above, not another bullet in the summary. End with the one requester-specific
  action, its purpose, and continuation. Do not replace it with a generic task
  list or a blocking "what would you like to do next?" question.

Keep it to a short readout the sponsor can act on. If offering a snapshot report,
put that secondary option before the next-step handoff, not after it.

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

**Plan state:** <local draft / shared draft / active / completed / archived>
**Milestone:** <where the rollout is>
**Objective:** <the plan's objective>

## Recently completed
- <task> — <who> — <when, if known>

## In progress
- <task> — <owner>

## Team readiness (prerequisites met)
- <task> — <owner/role>

## Blocked
- <task> — waiting on <upstream task>

## Next action for <requesting person's role>
**<one action, or no action needed>**
<purpose or waiting condition>
**Say / Run / Open:** <the relevant continuation, if action is needed>

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
