# Planner — Editing the plan (the Markdown round-trip)

The Plan's human view — `workspace/plan/ESS-scenario-plan.md` — is not just a
read-out. It is the **editable surface** the maker works with. The CLI
regenerates it from `plan.json` after every change, and the maker can revise it
and have those revisions **reconciled back into the plan**. `plan.json` stays the
source of truth; the Markdown is how a human edits it.

**It reads as a document, not a data dump.** The view is generated from
`plan.json` — the local cache of the shared WeveNova plan, hydrated on pull
(`src/skills/planner/sync.md`), so it always reflects the persisted plan (the
header shows the live **Status**, the connected **Agent**, and whether it is
**synced**). Instead of listing the raw context bag as `group → key: value`
bullets, it groups the sponsor's intent into readable sections:

- **Overview** — market/rollout wave, audience, jobs-to-be-done, business goals,
  and the definition of done (pilot bar).
- **Scenarios in scope** — one subsection per scenario with its capabilities, the
  system that backs it, and its dependencies in plain language.
- **Systems** — which system backs each area.
- **Scenario dependencies**, **Tasks**, **Produced outputs** — the ledgers.

**Enriched from Learn at render time.** When a Learn-research corpus is present
alongside the plan (`workspace/plan/research-context.json`), the render/refresh
step folds its grounding links into the view (a per-scenario *Learn:* line and a
**Learn references** section). This is best-effort: the plan renders fully without
it, and the setup *detail* still comes from Learn live at brief time
(`src/skills/planner/mytasks.md`) — the view links to the source, it never freezes
steps. Keep grounding a Learn link, not a copy.

## Present it as an editable file

Whenever you've created or changed the plan, show the editor the Markdown plan and
tell them they can edit it. Refer to it as the **"ESS scenario plan"** (its file is
`workspace/plan/ESS-scenario-plan.md`) — a file they can open, read, and edit, or
download and re-upload. Offer the two ways to change it:

1. **Edit the Markdown directly** — open `ESS-scenario-plan.md`, change it (add a
   task, tick one off, retitle, delete), save (or re-upload an edited copy), then
   tell me *"I edited the plan"*.
2. **Just say what to change** in chat — *"add a task to bring in the parental-leave
   knowledge source"*, *"mark Workday SSO done"*, *"drop the veteran-info write"*.

Speak in terms of the plan and its tasks — never mention `plan.json`, the CLI, or
which files you read.

After any change lands, re-render with `python scripts/planner/cli.py summary` and
surface the result the same way a fresh plan is presented — the downloadable link
**then** the grouped task checklist inline (see `SKILL.md` → "Building the plan"),
never a bare count — so the editor sees exactly what changed.

> **Editing our view vs. importing their plan.** This file reconciles a re-upload
> of the kit's **own** `ESS-scenario-plan.md` (diffed by task id) into a plan that
> **already exists**. A maker attaching a plan in **their own** shape when no plan
> exists yet is the other bookend — make sense of it and create the plan from it
> (`src/skills/planner/import.md`), then continue the phases.

## Reconcile a direct Markdown edit back into the plan

When the editor says they edited the Markdown (or re-uploads it), reconcile it —
**do this before running any command that regenerates the file, so you never
overwrite their edits**:

1. **Read both.** Read the edited `ESS-scenario-plan.md` and the current plan
   (`python scripts/planner/cli.py summary`). The Tasks table is keyed by task
   **id** (the `#` column) — use it to line rows up.
2. **Diff by id.** Work out, per task, what changed. The Tasks table shows
   **title**, **role / owner**, and **state** (plus the Overview, Scenarios in
   scope, Systems, and Scenario dependencies sections) — those are what a direct
   file edit can change:
   - **Added** row (no existing id / a new one) → a new task.
   - **Removed** row → a deletion.
   - **Retitled** → a title edit.
   - **Role / owner** column changed → a reassignment.
   - **State** column changed (e.g. a ticked checkbox → Completed) → a state change.
   - Changes under **Overview**, **Scenarios in scope**, **Systems**, or
     **Scenario dependencies** (goals, persona, a scenario's capabilities or its
     backing system, an added/removed scenario or dependency edge) → context edits.

   A task's **description / produces / consumes are not columns in the table**,
   so they can't be edited in the file — to change those, have the editor say so
   in chat (the chat-intent path) and apply `update-task`.
3. **Apply each change through the CLI** so writes stay atomic and validated —
   never hand-edit `plan.json`:

   ```
   python scripts/planner/cli.py add-task --id <next T#> --title "..." --description "..." --role <grounded-role> [--produces ...] [--consumes ...]
   python scripts/planner/cli.py update-task --id <T#> [--title "..."] [--description "..."] [--produces a,b] [--consumes a,b]
   python scripts/planner/cli.py remove-task --id <T#>
   python scripts/planner/cli.py assign --task <T#> --role <role> [--person <oid>]
   python scripts/planner/cli.py set-state --task <T#> --state Completed
   python scripts/planner/cli.py add-scenario --id <id> --label "..."
   python scripts/planner/cli.py set-context --key <k> --value "..." --group <group> --description "..." --source User
   python scripts/planner/cli.py remove-context --key <scenario-id | system.<area> | "A -> B">
   ```

4. **Re-render and show it back.** Applying a change regenerates
   `ESS-scenario-plan.md` — but first make the plan *whole* again (next section),
   then `validate`, then show the refreshed plan — *"I saw your changes and updated
   the plan — here it is again"*, calling out what changed (e.g. "added *Add
   parental-leave knowledge source*").

## Keep the plan coherent, sequenced, and complete — after every edit

An edit is never just a local row change. However it arrives — **said in chat**, a
**direct Markdown edit / re-upload** of `ESS-scenario-plan.md`, or a **fresh attach**
(`src/skills/planner/import.md`) — once you've applied the literal change, make the
plan *whole* again **before** you show it back. A plan that lost a system's tasks, or
kept a scenario no task serves, or left a task waiting on an output nothing produces,
is **not** a valid plan to hand back.

**1. Re-model what the edit changed the *scope* of — don't stop at one row.** Some
edits change *what is in scope*, and a scope change changes the **task set**, not a
single line. Treat these as a re-run of Phase-3 modelling (`model.md`) for the
affected area:

- **A scenario/system came *into* scope, or a system was swapped *in*** — e.g.
  *"use SuccessFactors instead of Workday"*, *"also add IT ticketing"*. Emit that
  system's **exhaustive** task set: its grounded checklist when one exists
  (`python scripts/planner/cli.py setup-tasks --system <sys> --commands`), otherwise
  the research-grounded, role-split set `model.md` prescribes. Wire each task into
  the `produces`/`consumes` ledger and tag it with the right `--stream`. Not one
  placeholder — the *whole* set, exactly as a first-time build would emit it.
- **A scenario/system went *out* of scope, or a system was swapped *out*** — remove
  **all** of its work, not just the row the maker deleted:

  ```
  python scripts/planner/cli.py remove-task --id <T#>         # each task in that stream (drops the outputs it produced too)
  python scripts/planner/cli.py remove-context --key <scenario-id>   # the scope entry itself
  python scripts/planner/cli.py remove-context --key system.<area>   # its Systems label
  python scripts/planner/cli.py remove-context --key "<A> -> <B>"    # any scenario-dependency edge that named it
  ```

A **swap** is simply an out-of-scope removal of the old system *and* an in-scope
emission of the new one — reuse the assignments/roles that still apply, and
re-point each affected scenario's Systems label (`add-system`). You never need a
system-specific script; it's always the same remove-then-emit on the stream.

**2. Repair the graph — never leave a task dangling.** After applying, run:

```
python scripts/planner/cli.py check-deps
python scripts/planner/cli.py validate
```

- **`check-deps` → "Task-graph gaps"** lists any task that now **consumes** a key
  nothing on the plan produces (a *dangling consume* — blocked forever). Fix each:
  re-add the producer the edit wrongly dropped, or remove/repoint the consumer that
  is now out of scope. Re-run until it reports *"Task graph is coherent."*
- **`validate`** must pass. (`remove-task` already clears the outputs the removed
  task produced, so you won't be left with an output pointing at a deleted task —
  but still validate.)
- **`check-deps` → unmet scenario dependencies** — honour the interview rule: bring
  the prerequisite scenario into scope or flag it to the sponsor.

Don't hand-sequence the tasks: **ordering falls out of the `produces`/`consumes`
wiring** — the view lists each producer before its consumer — so wiring the ledger
correctly in step 1 *is* how the plan stays in the right order and its waves hold.

**3. Completeness — an in-scope scenario carries its *whole* task set.** Don't leave
a scenario half-modelled. If the edit left (or brought) a scenario in scope, it must
have the full set — foundation (if not already present), connect/author, and
evaluation — the same exhaustiveness Phase 3 enforces, so no in-scope capability
ships without the tasks that build it.

**4. Propagate to the shared plan when it's live — then confirm cascades and show it
back.** Only once `check-deps` reports a coherent graph and `validate` passes:

- **If the plan is on the shared planner** (it has a plan id and reads as shared,
  not `(local, not synced)`), the edit is **not** finished when the local cache is
  written — every applied change must also reach the service, or other owners (and a
  later pull) never see it, and the next re-hydrate can quietly revert it. Route
  each change through its matching task tool **and then re-hydrate** so the local
  view and Markdown match the server — this is the *Ongoing edits* loop in
  `src/skills/planner/sync.md` (state → `set_project_plan_task_state`; content →
  `update_project_plan_task`; added task → `create_project_plan_task` /
  `create_role_assigned_project_plan_task`; removed task → its delete tool; a
  completion with its outputs → `complete_project_plan_task` via the `pending-sync`
  backlog). Guard each call with **that task's own etag** (never the plan's
  activation etag — that 412s), and walk the sync.md sign-in ladder on any failure;
  a change that can't be pushed stays local and re-syncs on the next successful entry.
- **If it's still a local draft** (`(local, not synced)`, no plan id), stay local —
  there's nothing to push until the sponsor shares it (`src/skills/planner/sync.md`
  → *Share*).

Removing a stream can orphan work the maker didn't explicitly name — confirm before
deleting (the "Ask where ambiguous" rule below). Then re-render (`summary`) and
present the refreshed plan the usual way — the download link **then** the grouped
checklist — calling out what changed (tasks added/removed, system re-pointed, new
ordering/waves).

> **Why this matters.** The maker edits a readable plan, not a dependency graph — the
> Markdown can't express `produces`/`consumes`, and a one-word swap ("use
> SuccessFactors") hides a dozen task changes. Re-modelling the affected scope and
> re-checking the graph is what keeps every edit coherent, sequenced, and complete
> instead of a broken half-swap.

## Ask where ambiguous — do not guess

Grounding and the plan's rules still hold when reconciling. Stop and ask the editor
a targeted question (rather than inventing) when an edit is unclear, for example:

- A **new task with no clear role** — the role is Learn-grounded, not invented; ask
  which role, or assign it to a role you can ground, but don't fabricate one.
- A **retitled row you can't map** to an existing id — ask whether it's a rename of
  an existing task or a brand-new one.
- A task **marked Completed that still has unmet dependencies**, or whose
  `produces` were never captured — confirm it's really done.
- A **deletion that would orphan** a dependency (something else consumes what it
  produced) — confirm before removing.
- A **new scenario / system** that maps to no ESS category, or a write with
  governance implications — confirm scope, per the interview rules.
- An **Intent line you can't classify** into a group — ask what it means.

Only assign new ids the plan doesn't already use (next `T#`); **reuse the id shown
in the row** for edits so you change the right task. Keep the plan valid after every
reconcile.

## Chat-intent edits

If the editor states the change in chat instead of editing the file, apply it the
same way (the matching CLI command above), **run the same "Keep the plan coherent,
sequenced, and complete" loop** — re-model any scope the change touched, repair the
graph (`check-deps` + `validate`), confirm destructive cascades — then show the
refreshed plan. Same grounding and same "ask where ambiguous" rule. A chat intent
like *"use SuccessFactors instead of Workday"* or *"drop manager self-service"* is a
scope change, not a one-line edit: it triggers the full remove-then-emit, not a
single `set-system`.
