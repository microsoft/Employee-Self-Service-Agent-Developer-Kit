# Planner — Editing the plan (the Markdown round-trip)

The Plan's human view — `workspace/plan/ESS-scenario-plan.md` — is not just a
read-out. It is the **editable surface** a Plan editor works with. The CLI
regenerates it from `plan.json` after every change, and the editor can revise it
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
   ```

4. **Re-render and show it back.** Applying a change regenerates
   `ESS-scenario-plan.md`; run `validate`, then show the refreshed plan — *"I saw
   your changes and updated the plan — here it is again"*, calling out what changed
   (e.g. "added *Add parental-leave knowledge source*").

## Ask where ambiguous — do not guess

Grounding and the plan's rules still hold when reconciling. Stop and ask the editor
a targeted question (rather than inventing) when an edit is unclear, for example:

- A **new task with no clear role** — the role is Learn-grounded, not invented; ask
  which role, or pool it to a role you can ground, but don't fabricate one.
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
same way (the matching CLI command above), confirm, and show the refreshed plan.
Same grounding and same "ask where ambiguous" rule.
